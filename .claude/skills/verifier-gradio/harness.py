"""Reusable runtime-verification harness for the Gradio wizard.

Why a browser and not ``gradio_client``: every wizard event threads
``gr.State(WizardSession)`` (a non-JSON dataclass) as an input/output, which
the API client can't carry. So the honest surface is the real browser — we
launch the actual ``build_demo()`` server and drive it with Playwright.

This module is pure plumbing; scenarios (e.g. ``smoke.py``) import it and
describe *what* to drive. Gotchas baked in here so nobody re-discovers them:

* Run ``uv run`` from the PROJECT dir — uv resolves the env from cwd.
* Reconfigure stdout to UTF-8 — the app/UI text has ``—`` and ``✓``.
* Never ``wait_for_load_state("networkidle")`` — Gradio holds an SSE channel
  open, so it never goes idle; wait for a concrete element instead.
* LLM paths need ``APP_GEMINI_API_KEY``. Without it they fail *gracefully*
  (no crash) — the free mechanism check asserts that, not generation quality.
"""

from __future__ import annotations

import contextlib
import socket
import sys
import time
from collections.abc import Iterator
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # pragma: no cover - setup guard
    sys.stderr.write(
        "Playwright is required for GUI verification. One-time setup:\n"
        "  uv pip install playwright\n"
        "  uv run playwright install chromium\n"
    )
    raise


def free_port() -> int:
    """An OS-assigned free TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def make_workdir(prefix: str = "verify_gradio_") -> tuple[Path, Path, Path]:
    """Create an isolated (work, bucket, screenshots) trio under the temp dir."""
    import tempfile

    work = Path(tempfile.mkdtemp(prefix=prefix))
    bucket = work / "bucket"
    shots = work / "shots"
    bucket.mkdir(parents=True, exist_ok=True)
    shots.mkdir(parents=True, exist_ok=True)
    return work, bucket, shots


def seed_character(
    bucket: Path,
    name: str,
    *,
    current_step: str | None = None,
    table: dict[str, str] | None = None,
    style: str = "",
) -> str:
    """Write a saved character into ``bucket`` and return its id.

    ``current_step`` set -> "in progress"; empty -> "ready". Uses an explicit
    ``root`` so seeding is independent of the app's env config.
    """
    from create_char_passport.state import blank_state
    from create_char_passport.storage import save_state

    state = blank_state(name)
    state.current_step = current_step
    if table:
        state.character_table = dict(table)
    if style:
        state.prompt_layers.style = style
    save_state(state, root=bucket)
    return state.character_id


def read_state(bucket: Path, character_id: str) -> dict:
    """Load a seeded/edited character's ``state.json`` as a dict (disk truth)."""
    import json

    return json.loads((bucket / character_id / "state.json").read_text(encoding="utf-8"))


def launch_app(bucket: Path, *, port: int | None = None) -> tuple[object, str]:
    """Point the app at ``bucket`` and launch the real ``build_demo()`` server.

    Returns ``(demo, url)``; call ``demo.close()`` when done.
    """
    import os

    os.environ["APP_BUCKET_PATH"] = str(bucket)
    os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"
    os.environ.setdefault("APP_GEMINI_API_KEY", "")  # no key -> LLM fails softly

    from create_char_passport.config import get_settings

    get_settings.cache_clear()
    from create_char_passport.gradio_app import build_demo

    port = port or free_port()
    demo = build_demo()
    demo.queue()
    demo.launch(
        server_name="127.0.0.1",
        server_port=port,
        prevent_thread_lock=True,
        quiet=True,
        show_error=True,
    )
    time.sleep(2.5)
    return demo, f"http://127.0.0.1:{port}/"


class Drive:
    """Gradio-aware Playwright wrapper + observation log."""

    def __init__(self, page: object, shots: Path) -> None:
        self.page = page
        self.shots = shots
        self.obs: list[tuple[bool, str, bool]] = []  # (ok, message, critical)

    # --- navigation / capture ------------------------------------------- #
    def goto(self, url: str, *, ready_button: str = "Extract characters (LLM)") -> None:
        self.page.goto(url)  # type: ignore[attr-defined]
        self.page.get_by_role("button", name=ready_button).wait_for(state="visible")  # type: ignore[attr-defined]
        time.sleep(3.0)  # let demo.load fire (e.g. saved-list population)

    def shot(self, name: str) -> Path:
        path = self.shots / f"{name}.png"
        self.page.screenshot(path=str(path), full_page=True)  # type: ignore[attr-defined]
        return path

    def body(self) -> str:
        return self.page.inner_text("body")  # type: ignore[attr-defined,no-any-return]

    # --- interactions ---------------------------------------------------- #
    def fill(self, label: str, value: str) -> None:
        box = self.page.get_by_label(label, exact=True)  # type: ignore[attr-defined]
        box.click()
        box.fill(value)

    def blur(self) -> None:
        self.page.keyboard.press("Tab")  # type: ignore[attr-defined]
        time.sleep(1.2)

    def click_button(self, name: str, *, settle: float = 1.5) -> None:
        self.page.get_by_role("button", name=name).click()  # type: ignore[attr-defined]
        time.sleep(settle)

    def wait_for_text(self, text: str, *, timeout: float = 90.0) -> bool:
        """Poll the page body until ``text`` appears (robust to slow renders under load).

        Heavy transitions (e.g. "Open saved" fires a long chained refresh) can take
        well over a second on a loaded machine; reading ``body()`` on a fixed sleep
        then races the render. Polling until the expected marker shows removes the
        flake without ever waiting on Gradio's never-idle SSE channel.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            if text in self.page.inner_text("body"):  # type: ignore[attr-defined]
                return True
            time.sleep(0.5)
        return False

    def check(self, label: str) -> None:
        self.page.get_by_label(label, exact=True).check()  # type: ignore[attr-defined]
        time.sleep(1.0)

    def dropdown_options(self, label: str) -> list[str]:
        self.page.get_by_label(label).click()  # type: ignore[attr-defined]
        time.sleep(0.5)
        opts = self.page.get_by_role("option").all_inner_texts()  # type: ignore[attr-defined]
        self.page.keyboard.press("Escape")  # type: ignore[attr-defined]
        return opts

    def pick(self, label: str, option: str) -> None:
        self.page.get_by_label(label).click()  # type: ignore[attr-defined]
        time.sleep(0.4)
        self.page.get_by_role("option", name=option).click()  # type: ignore[attr-defined]
        time.sleep(0.3)

    # --- assertions ------------------------------------------------------ #
    def expect(self, ok: bool, message: str, *, critical: bool = True) -> bool:
        self.obs.append((bool(ok), message, critical))
        mark = "PASS" if ok else ("FAIL" if critical else "WARN")
        print(f"  [{mark}] {message}")
        return bool(ok)

    def note(self, message: str) -> None:
        print(f"  [obs ] {message}")
        self.obs.append((True, message, False))


@contextlib.contextmanager
def drive(url: str, shots: Path) -> Iterator[Drive]:
    """Open a chromium page on ``url`` and yield a :class:`Drive` helper."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_default_timeout(30000)
        try:
            yield Drive(page, shots)
        finally:
            browser.close()


def report(driver: Drive, shots: Path) -> int:
    """Print a summary and return an exit code (1 if any critical check failed)."""
    failed = [m for ok, m, crit in driver.obs if crit and not ok]
    print("\n=== VERIFY SUMMARY ===")
    print(f"screenshots: {shots}")
    print(f"checks: {sum(1 for ok, _m, c in driver.obs if c)} critical, {len(failed)} failed")
    if failed:
        print("FAILED:")
        for m in failed:
            print(f"  - {m}")
        print("VERDICT: FAIL")
        return 1
    print("VERDICT: PASS")
    return 0
