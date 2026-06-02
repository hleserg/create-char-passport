"""AI-assist review logic — contract use of K1/K2/K3 (HLE-731).

Two paid LLM helpers share ONE response grammar and a fault-tolerant parser:

* **Check with AI** (per step): reply ``{обоснование}[новый промт]`` — the
  justification is always shown; a non-empty ``[новый промт]`` is offered to
  write into the step's editable field.
* **Edit with AI** (whole character; passport + dataset only): reply is a run of
  ``&<step_key>&{обоснование}[новый промт]`` blocks — only changed steps;
  accepting a block writes the step prompt AND raises its ``need_regen`` gate.

Robustness (§В): a malformed reply never raises — it triggers ONE reminder
retry, then falls back to a friendly message with no field write; ``&step&``
markers outside the pipeline are ignored. ``call_llm`` returning ``""`` means the
API is down (no retry — a retry won't help), distinct from a well-formed
"no changes" reply.

This module is pure (no Gradio); the LLM call is injected so it is unit-tested
directly. ``ai.wiring`` fills the K4 slots and routes accepted prompts here.
"""

from __future__ import annotations

import base64
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from create_char_passport.gen import build_prompt_layers, call_llm
from create_char_passport.gen.prompt import render_prompt_text
from create_char_passport.state import (
    CharacterState,
    CostLedger,
    StepKind,
    classify_step,
    dataset_step,
    outfit_step,
)
from create_char_passport.state.steps import DATASET_PREFIX
from create_char_passport.wizard.dataset import edit_composition
from create_char_passport.wizard.forms import set_base_emotion
from create_char_passport.wizard.outfits import set_outfit_detail_prompt, set_outfit_prompt
from create_char_passport.wizard.passport import apply_layer_edit
from create_char_passport.wizard.props import set_prop_shot_prompt

# Signature of the injectable LLM call (matches gen.call_llm's public surface).
LlmCall = Callable[..., str]

_BRACE_RE = re.compile(r"\{(.*?)\}", re.DOTALL)
_SQUARE_RE = re.compile(r"\[(.*?)\]", re.DOTALL)
_MARKER_RE = re.compile(r"&([^&\n]+)&")

NO_RESPONSE = "ИИ не ответил — попробуйте ещё раз."
UNEXPECTED = "ИИ вернул ответ в неожиданном формате — попробуйте ещё раз."
NO_CHANGES = "ИИ не предложил правок — по его оценке всё в порядке."

_RESPONSE_HINT = (
    "Ответь СТРОГО в формате `{обоснование}[новый промт]`. В фигурных скобках — "
    "короткое объяснение для пользователя (по-русски). В квадратных — улучшенный "
    "промт этого шага (по-английски) ИЛИ пусто `[]`, если правок не нужно. Ничего "
    "вне скобок не пиши."
)
_EDIT_HINT = (
    "Для КАЖДОГО шага, который нужно поправить, выведи блок "
    "`&<step_key>&{обоснование}[новый полный промт шага]`. Только изменённые шаги; "
    "step_key бери ТОЧНО из списка ниже, не выдумывай. Если правок нет — короткий "
    "текст без скобок и маркеров."
)

# Per-StepKind acceptance criteria (plan §5 "Распространение на ВСЕ блоки"). Strict
# layer separation: each checklist guards only its own concern.
CHECKLISTS: dict[StepKind, str] = {
    StepKind.PASSPORT: (
        "Это паспортный кадр (идентичность). Проверь ИЗОЛЯЦИЮ слоёв: FACE/BODY "
        "описывают только анатомию/приметы и НЕ лезут в эмоцию, позу, одежду или "
        "фон. Кадр: нужный ракурс и кадрирование, нейтральное выражение, ровный "
        "серый фон, мягкий свет, без рамок/текста/надписей."
    ),
    StepKind.BASE_EMOTION: (
        "Это портрет эмоции. EXPRESSION — короткое читаемое выражение, НЕ проза и "
        "не описание позы/одежды/фона. Кадр портретный (голова и плечи), серый фон."
    ),
    StepKind.EMOTION: (
        "Это портрет эмоции. EXPRESSION — короткое читаемое выражение, НЕ проза и "
        "не описание позы/одежды/фона. Кадр портретный (голова и плечи), серый фон."
    ),
    StepKind.OUTFIT: (
        "Это кадр наряда. OUTFIT описывает ТОЛЬКО одежду. Нужен полный рост без "
        "обрезок для этой сцены, ровный серый фон, без рамок/текста."
    ),
    StepKind.OUTFIT_DETAIL: (
        "Это макро-деталь костюма (крупный план). Кадр — крупный план материала/"
        "застёжки/орнамента ЭТОГО наряда; без требований к лицу/телу/позе; серый фон."
    ),
    StepKind.PROP: (
        "Это product-shot предмета. Предмет в нужном стиле, на чистом сером фоне, "
        "БЕЗ персонажа/рук/частей тела, без рамок/текста."
    ),
    StepKind.DATASET: (
        "Это кадр датасета. Картинка должна соответствовать промту (поза/ракурс/"
        "кадрирование/фон); активный наряд и базовая эмоция на месте; серый фон."
    ),
}


@dataclass(slots=True)
class CheckOutcome:
    """Result of a per-step "Check with AI" call."""

    justification: str
    new_prompt: str | None  # None → leave the step's field untouched
    step_key: str
    ok: bool = True  # False → the API returned nothing (not merely "no change")


@dataclass(slots=True)
class EditBlock:
    """One step's proposed edit from a whole-character "Edit with AI" review."""

    step_key: str
    justification: str
    new_prompt: str


@dataclass(slots=True)
class EditOutcome:
    """Result of a whole-character "Edit with AI" call."""

    blocks: list[EditBlock]
    note: str  # shown when there are no actionable blocks (prose / friendly message)
    ok: bool = True


# --------------------------------------------------------------------------- #
# Parsing (never raises)
# --------------------------------------------------------------------------- #
def _has_braces(text: str) -> bool:
    return bool(_BRACE_RE.search(text))


def parse_check_reply(text: str) -> tuple[str | None, str | None]:
    """Split ``{обоснование}[новый промт]`` → ``(justification, new_prompt)``.

    Missing braces → ``justification`` is ``None``; missing/empty brackets →
    ``new_prompt`` is ``None`` (the field is left alone). Never raises.
    """
    brace = _BRACE_RE.search(text)
    justification = brace.group(1).strip() if brace else None
    square = _SQUARE_RE.search(text)
    new_prompt = square.group(1).strip() if square else None
    return justification or None, new_prompt or None


def parse_edit_reply(text: str, valid_keys: set[str]) -> list[EditBlock]:
    """Parse ``&step&{just}[prompt]`` blocks; drop unknown keys / empty prompts.

    Each ``&step&`` marker delimits a segment parsed by :func:`parse_check_reply`.
    A marker whose key is not in ``valid_keys`` is ignored (no phantom steps), as
    is a block with an empty ``[новый промт]``.
    """
    markers = list(_MARKER_RE.finditer(text))
    blocks: list[EditBlock] = []
    for i, marker in enumerate(markers):
        key = marker.group(1).strip()
        if key not in valid_keys:
            continue
        end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
        justification, new_prompt = parse_check_reply(text[marker.end() : end])
        if new_prompt:
            blocks.append(EditBlock(key, justification or "", new_prompt))
    return blocks


# --------------------------------------------------------------------------- #
# Prompt building
# --------------------------------------------------------------------------- #
def _image_b64(preview_path: str | Path | None) -> str | None:
    if not preview_path:
        return None
    path = Path(preview_path)
    if not path.is_file():
        return None
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _check_prompt(checklist: str, rendered_layers: str) -> str:
    return (
        "Ты ревизор промтов для генератора изображений персонажей. Проверь ТЕКУЩИЙ "
        "шаг по критериям и при необходимости предложи улучшенный промт.\n\n"
        f"Критерии шага:\n{checklist}\n\n"
        f"Текущий промт шага (по слоям):\n{rendered_layers}\n\n"
        f"{_RESPONSE_HINT}"
    )


def editable_step_keys(state: CharacterState) -> list[str]:
    """Steps the whole-character edit may rewrite + flag ``need_regen``.

    Restricted to gate-safe, self-clearing, ``state.steps``-backed steps: passport
    FACE/BODY, each outfit, and each dataset composition. Camera-only passport
    frames, emotions (re-key hazard / no record) and props/details (no record the
    gate can see) are intentionally excluded — flagging them would orphan a
    ``need_regen`` nobody clears.
    """
    keys = ["passport_face", "passport_body"]
    if state.outfits_enabled:
        keys.extend(outfit_step(outfit.id) for outfit in state.outfits)
    keys.extend(dataset_step(i) for i in range(len(state.dataset_compositions)))
    return keys


def _character_context(state: CharacterState) -> str:
    lines = [f"Имя: {state.name}"] if state.name else []
    for key, value in state.character_table.items():
        if str(value).strip():
            lines.append(f"{key}: {value}")
    base = state.emotions.base_emotion
    if base.enabled and base.value.strip():
        lines.append(f"Базовая эмоция: {base.value}")
    lines.append("\nШаги и их текущие промты:")
    for key in editable_step_keys(state):
        lines.append(f"&{key}&\n{render_prompt_text(build_prompt_layers(state, key))}")
    return "\n".join(lines)


def _edit_prompt(context: str, request: str, valid_keys: list[str]) -> str:
    return (
        "Ты ревизор всего персонажа для генератора изображений. Выполни запрос "
        "пользователя и проверь все шаги на критерии, изоляцию слоёв и оптимальность.\n\n"
        f"Запрос пользователя:\n{request.strip()}\n\n"
        f"Контекст персонажа:\n{context}\n\n"
        f"Допустимые step_key: {', '.join(valid_keys)}\n\n"
        f"{_EDIT_HINT}"
    )


# --------------------------------------------------------------------------- #
# LLM helpers (one reminder retry on a malformed reply)
# --------------------------------------------------------------------------- #
def check_step(
    state: CharacterState,
    step_key: str,
    preview_path: str | Path | None = None,
    *,
    meter: CostLedger | None = None,
    call: LlmCall = call_llm,
    model: str | None = None,
) -> CheckOutcome:
    """Run "Check with AI" for ``step_key`` and parse the reply."""
    checklist = CHECKLISTS[classify_step(step_key)]
    prompt = _check_prompt(checklist, render_prompt_text(build_prompt_layers(state, step_key)))
    image_b64 = _image_b64(preview_path)
    reply = call(prompt, image_b64, meter=meter, model=model)
    if not reply.strip():
        return CheckOutcome(NO_RESPONSE, None, step_key, ok=False)
    if not _has_braces(reply):
        reply = call(f"{prompt}\n\n{_RESPONSE_HINT}", image_b64, meter=meter, model=model)
        if not reply.strip() or not _has_braces(reply):
            return CheckOutcome(UNEXPECTED, None, step_key, ok=True)
    justification, new_prompt = parse_check_reply(reply)
    return CheckOutcome(justification or reply.strip(), new_prompt, step_key, ok=True)


def edit_character(
    state: CharacterState,
    request: str,
    preview_path: str | Path | None = None,
    *,
    meter: CostLedger | None = None,
    call: LlmCall = call_llm,
    model: str | None = None,
) -> EditOutcome:
    """Run the whole-character "Edit with AI" review and parse per-step blocks."""
    valid = set(editable_step_keys(state))
    prompt = _edit_prompt(_character_context(state), request, sorted(valid))
    image_b64 = _image_b64(preview_path)
    reply = call(prompt, image_b64, meter=meter, model=model)
    if not reply.strip():
        return EditOutcome([], NO_RESPONSE, ok=False)
    blocks = parse_edit_reply(reply, valid)
    if not blocks and not _MARKER_RE.search(reply):
        retry = call(f"{prompt}\n\n{_EDIT_HINT}", image_b64, meter=meter, model=model)
        if retry.strip():
            reply = retry
            blocks = parse_edit_reply(reply, valid)
    if not blocks:
        return EditOutcome([], reply.strip() or NO_CHANGES, ok=True)
    return EditOutcome(blocks, "", ok=True)


# --------------------------------------------------------------------------- #
# Write-back (routes through the per-phase setters)
# --------------------------------------------------------------------------- #
def _dataset_index(step_key: str) -> int | None:
    raw = step_key[len(DATASET_PREFIX) :]
    return int(raw) if raw.isdigit() else None


def apply_step_prompt(state: CharacterState, step_key: str, new_prompt: str) -> bool:
    """Write an accepted prompt into the step's source field (so the next generate uses it).

    Routes through the owning phase's setter. Returns ``False`` for a step with no
    writable field (e.g. a stray emotion key — its label is an identifier, not a
    prompt) so a bogus marker never mutates state.
    """
    kind = classify_step(step_key)
    text = new_prompt.strip()
    if kind is StepKind.PASSPORT:
        if step_key == "passport_body":
            apply_layer_edit(state, step_key, body=text)
        else:
            apply_layer_edit(state, step_key, face=text)
        return True
    if kind is StepKind.BASE_EMOTION:
        set_base_emotion(state, state.emotions.base_emotion.enabled, text)
        return True
    if kind is StepKind.OUTFIT:
        return set_outfit_prompt(state, step_key, text)
    if kind is StepKind.OUTFIT_DETAIL:
        return set_outfit_detail_prompt(state, step_key, text)
    if kind is StepKind.PROP:
        return set_prop_shot_prompt(state, step_key, text)
    if kind is StepKind.DATASET:
        idx = _dataset_index(step_key)
        if idx is None:
            return False
        edit_composition(state, idx, text)
        return True
    return False  # EMOTION series: rewriting the label re-keys the step — skip
