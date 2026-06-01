# HLE-726 — Contracts K1–K4

Canonical surface shared by the rest of the epic (HLE-727…HLE-731). These
contracts are produced by the foundation task (HLE-726) and consumed
**verbatim** by tasks 2–6. Any change here is a contract change — bump
the task and notify the dependents.

The canonical project rules (`AGENTS.md`) still apply on top: `make check`
is the DoD gate, all secrets through `get_settings()`, Conventional
Commits, Sentry `send_default_pii=False`, PLAYBOOK markers near reusable
patterns.

---

## K1 — `step_key` vocabulary

Keys are used as identifiers in `state.steps{}`, `current_step`, the
`&шаг&` markers of the Edit-with-AI reply parser, and the `need_regen`
gate.

| Pattern | Meaning |
| --- | --- |
| `passport_face` | step 1 — front portrait |
| `passport_body` | step 2 — front full-length |
| `passport_profile` | step 3 — profile portrait |
| `passport_back` | step 4 — back full-length |
| `passport_3q` | step 5 — three-quarter full-length |
| `base_emotion` | base-emotion portrait |
| `emotion_<value>` | emotion series — `<value>` is `slugify(label)` |
| `outfit_<id>` | outfit phase step — `<id>` from `outfits[].id` |
| `outfit_<id>_detail_<n>` | costume close-up `n` of outfit `<id>` |
| `prop_<id>_shot_<n>` | prop frame `n` of prop `<id>` |
| `dataset_<idx>` | composition `idx` of the dataset array |

Helpers (`create_char_passport.state`):

* `PASSPORT_STEPS: tuple[str, ...]` — the five passport keys in canonical order.
* `BASE_EMOTION_STEP: str = "base_emotion"`.
* `slugify(value)` — lower-case ASCII, `_`-separated. Used for emotion suffixes.
* `emotion_step(value)` / `outfit_step(id)` / `outfit_detail_step(id, n)`
  / `prop_shot_step(id, n)` / `dataset_step(idx)` — constructors. Never
  build keys by hand.
* `classify_step(step_key) -> StepKind` — bucket into
  `PASSPORT / BASE_EMOTION / EMOTION / OUTFIT / OUTFIT_DETAIL / PROP / DATASET`.
* `ordered_step_keys(state)` — every key that *could* exist for `state`,
  in canonical pipeline order. Dynamic suffixes follow array order, NOT
  lexical (so `emotion_neutral` precedes `emotion_angry_furious`). This
  is the order the `need_regen` gate iterates.

---

## K2 — Generation engine (`create_char_passport.gen.engine`)

```python
from create_char_passport.gen import Ref, GenerationResult, generate_image, call_llm

Ref(path="refs/passport_face.png", role="face")  # role ∈ {face, body, style, outfit}

generate_image(
    prompt_layers={"style": ..., "face": ..., ...},   # see K3
    refs=[Ref(...), Ref(...)],
    outfit_conflict=False,
    output_path="…/refs/<step_key>.png",
    model=None,                                       # default: settings.image_model
) -> GenerationResult                                 # {image_path, ok, error}

call_llm(prompt="…", image_b64=None, model=None) -> str   # default: settings.llm_model
```

Behaviour:

* The Gemini client is built by a lazy `_get_client()` factory; **tests
  monkeypatch the factory**, never the module-level state.
* `IMAGE_MODEL` and `LLM_MODEL` are pure config (`APP_IMAGE_MODEL`,
  `APP_LLM_MODEL` in `.env.example`):
  * default image — `gemini-3.1-flash-image-preview` (Nano Banana 2);
  * swap target — `gemini-3-pro-image-preview` (Nano Banana Pro) when
    identity drifts;
  * cheap test runs — `gemini-2.5-flash-image`.
  * default LLM — `gemini-2.5-flash`.
* Multi-ref roles ride on the text part:
  `"image 1 = face reference; image 2 = body reference; …"` plus the
  optional `outfit_conflict` rule that tells the generator to ignore
  clothing in the references (§3.5 of `plan/proekt_zametki.md`).
* Errors (`429`, timeout, generator failure) **never** raise — they come
  back as `GenerationResult(ok=False, error=<friendly text>)` so the UI
  shows a Retry button and the user prompt is preserved.
* Extension point for cost counting (HLE-664): the engine is the single
  call site, so a future decorator can wrap `_get_client().models.…`.

---

## K3 — Prompt builder (`create_char_passport.gen.prompt`)

```python
build_prompt_layers(state, step_key, overrides=None) -> dict[str, str]
render_prompt_text(layers) -> str           # joins layers in canonical order
LAYER_NAMES == ("style", "face", "body", "outfit", "expression", "composition")
```

Rules:

* Layer order is **always** STYLE → FACE → BODY → OUTFIT → EXPRESSION →
  COMPOSITION; empty layers are dropped at render time but always
  present as keys in the returned dict.
* OUTFIT resolves from `state.active_outfit_id` — `"base"` → `base_outfit`,
  otherwise the matching entry in `state.outfits[]`.
* EXPRESSION resolution (Decision 5 of HLE-661):
  * `passport_*` → `"neutral"` forced; base emotion is **ignored**.
  * `emotion_<value>` → the series value (slug → label by replacing `_`).
  * Everything else → `base_emotion.value` if `enabled and value.strip()`,
    else `"neutral"`. The default applies even if the emotions block
    itself is off.
* `overrides={"composition": "<text>"}` swaps a single layer (used by
  passport screens to inject the canonical COMPOSITION template).
  EXPRESSION overrides are only honoured on non-passport / non-emotion
  steps; the rule above always wins for those.

---

## K4 — AI-assist slots (`create_char_passport.ai`)

```python
from create_char_passport.ai import build_ai_check_slot, build_ai_edit_slot

ai_check = build_ai_check_slot(step_key, prompt_textbox)        # all step screens
ai_edit  = build_ai_edit_slot(step_key, prompt_textbox)         # passport + dataset
```

Each step-generation screen renders an empty `ai_check_slot` (`gr.Group`)
next to its prompt field. Passport and dataset screens additionally
render an `ai_edit_slot`. Foundation work only **reserves** the slot —
task 6 of the epic fills it with the actual Check/Edit logic.

The slot exposes:

* `step_key: str` — drives the check-list type (passport / emotion / outfit
  / detail / prop / composition).
* `prompt_field: gr.Component` — where task 6 writes back any accepted
  `[новый промт]` from the LLM reply.
* `container: gr.Group` — the empty container task 6 fills.

The reply parser format (`{обоснование}[новый промт]`) is shared across
both check and edit buttons; the Edit slot additionally honours the
multi-step `&шаг&` marker (see `plan/proekt_zametki.md` §5).
