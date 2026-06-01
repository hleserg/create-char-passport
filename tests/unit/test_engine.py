"""Tests for the generation engine.

The Gemini SDK is monkeypatched via the lazy ``_get_client`` factory so
tests never touch the network or need an API key.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from create_char_passport.gen import call_llm, generate_image
from create_char_passport.gen import engine as engine_mod
from create_char_passport.gen.engine import Ref


@dataclass
class FakePart:
    inline_data: Any = None
    text: str | None = None


@dataclass
class FakeContent:
    parts: list[FakePart]


@dataclass
class FakeCandidate:
    content: FakeContent


@dataclass
class FakeResponse:
    candidates: list[FakeCandidate]
    text: str | None = None


@dataclass
class FakeInline:
    data: Any


class FakeModels:
    def __init__(self, response: FakeResponse) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, **kwargs: Any) -> FakeResponse:
        self.calls.append(kwargs)
        return self._response


class FakeClient:
    def __init__(self, response: FakeResponse) -> None:
        self.models = FakeModels(response)


def _patch_client(monkeypatch: pytest.MonkeyPatch, response: FakeResponse) -> FakeClient:
    client = FakeClient(response)
    monkeypatch.setattr(engine_mod, "_get_client", lambda: client)
    return client


def test_generate_image_writes_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    response = FakeResponse(
        candidates=[
            FakeCandidate(
                content=FakeContent(
                    parts=[FakePart(inline_data=FakeInline(data=b"png-bytes"))],
                )
            )
        ],
    )
    _patch_client(monkeypatch, response)

    ref_file = tmp_path / "face.png"
    ref_file.write_bytes(b"reference-bytes")
    out = tmp_path / "refs" / "passport_face.png"

    result = generate_image(
        prompt_layers={"style": "grim", "face": "broad"},
        refs=[Ref(path=str(ref_file), role="face")],
        outfit_conflict=True,
        output_path=out,
    )

    assert result.ok is True
    assert result.image_path == str(out)
    assert out.read_bytes() == b"png-bytes"


def test_generate_image_decodes_base64_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import base64

    payload = base64.b64encode(b"decoded-bytes").decode("ascii")
    response = FakeResponse(
        candidates=[
            FakeCandidate(
                content=FakeContent(parts=[FakePart(inline_data=FakeInline(data=payload))])
            )
        ],
    )
    _patch_client(monkeypatch, response)
    out = tmp_path / "x.png"

    result = generate_image(prompt_layers={}, refs=[], output_path=out)
    assert result.ok is True
    assert out.read_bytes() == b"decoded-bytes"


def test_generate_image_handles_429_rate_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class RateLimitError(Exception):
        pass

    def boom() -> None:
        raise RateLimitError("HTTP 429 quota exceeded")

    class Client:
        @property
        def models(self) -> Any:
            class M:
                def generate_content(self, **_: Any) -> Any:
                    boom()

            return M()

    monkeypatch.setattr(engine_mod, "_get_client", lambda: Client())

    result = generate_image(prompt_layers={"style": "x"}, refs=[], output_path=tmp_path / "out.png")
    assert result.ok is False
    assert result.image_path is None
    assert "Rate limit" in (result.error or "")


def test_generate_image_handles_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class TimeoutError_(Exception):
        pass

    class Client:
        @property
        def models(self) -> Any:
            class M:
                def generate_content(self, **_: Any) -> Any:
                    raise TimeoutError_("connection timeout")

            return M()

    monkeypatch.setattr(engine_mod, "_get_client", lambda: Client())
    result = generate_image(prompt_layers={}, refs=[], output_path=tmp_path / "x.png")
    assert result.ok is False
    assert "timed out" in (result.error or "").lower()


def test_generate_image_handles_no_image_returned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    response = FakeResponse(candidates=[FakeCandidate(content=FakeContent(parts=[FakePart()]))])
    _patch_client(monkeypatch, response)
    result = generate_image(prompt_layers={}, refs=[], output_path=tmp_path / "x.png")
    assert result.ok is False
    assert "no image" in (result.error or "").lower()


def test_generate_image_handles_generic_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Client:
        @property
        def models(self) -> Any:
            class M:
                def generate_content(self, **_: Any) -> Any:
                    raise RuntimeError("internal")

            return M()

    monkeypatch.setattr(engine_mod, "_get_client", lambda: Client())
    result = generate_image(prompt_layers={}, refs=[], output_path=tmp_path / "x.png")
    assert result.ok is False
    assert "Generation failed" in (result.error or "")


def test_call_llm_returns_text(monkeypatch: pytest.MonkeyPatch) -> None:
    response = FakeResponse(
        candidates=[FakeCandidate(content=FakeContent(parts=[FakePart(text="hello world")]))],
    )
    _patch_client(monkeypatch, response)
    assert call_llm("describe the style", image_b64="aGVsbG8=") == "hello world"


def test_call_llm_sends_multiple_images_ahead_of_text(monkeypatch: pytest.MonkeyPatch) -> None:
    response = FakeResponse(
        candidates=[FakeCandidate(content=FakeContent(parts=[FakePart(text="style")]))],
    )
    client = _patch_client(monkeypatch, response)
    call_llm("describe the style", image_b64="single", images_b64=["a", "b"])

    contents = client.models.calls[0]["contents"]
    inline = [p["inline_data"]["data"] for p in contents if "inline_data" in p]
    # Single image first, then the list, all ahead of the trailing text part.
    assert inline == ["single", "a", "b"]
    assert contents[-1]["text"] == "describe the style"


def test_call_llm_uses_response_text_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    response = FakeResponse(candidates=[], text="direct-text")
    _patch_client(monkeypatch, response)
    assert call_llm("hi") == "direct-text"


def test_call_llm_returns_empty_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class Client:
        @property
        def models(self) -> Any:
            class M:
                def generate_content(self, **_: Any) -> Any:
                    raise RuntimeError("boom")

            return M()

    monkeypatch.setattr(engine_mod, "_get_client", lambda: Client())
    assert call_llm("anything") == ""


def test_text_part_includes_role_caption_and_conflict_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    response = FakeResponse(
        candidates=[
            FakeCandidate(
                content=FakeContent(
                    parts=[FakePart(inline_data=FakeInline(data=b"x"))],
                )
            )
        ],
    )
    client = _patch_client(monkeypatch, response)
    ref = tmp_path / "f.png"
    ref.write_bytes(b"r")

    generate_image(
        prompt_layers={"style": "grim", "face": "broad"},
        refs=[Ref(path=str(ref), role="face")],
        outfit_conflict=True,
        output_path=tmp_path / "out.png",
    )

    call = client.models.calls[0]
    contents = call["contents"]
    # Last part is the text composed by _build_text_part.
    text = contents[-1]["text"]
    assert "[STYLE]" in text
    assert "image 1 = face reference" in text
    assert "IGNORE the clothing" in text
