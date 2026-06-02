"""Default free, no-key mechanism/regression check for the wizard.

Drives the real app end-to-end on the paths that DON'T need a paid LLM call:
saved-list-on-load, open-saved resume, char-data prefill, optional-block
toggles, persistence to state.json, and navigation. The one LLM path touched
(extract) is only checked for *graceful failure* with no API key.

Run from the project dir:
    uv run python .claude/skills/verifier-gradio/smoke.py

Exit code is non-zero if any critical mechanism check regressed.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from harness import (
    Drive,
    drive,
    launch_app,
    make_workdir,
    read_state,
    report,
    seed_character,
)


def run(d: Drive, bucket: Path, url: str) -> None:
    d.goto(url)
    d.shot("01_home")

    # 1) saved-characters list populated from the bucket on app open (demo.load)
    opts = d.dropdown_options("Saved characters (from bucket)")
    blob = " ".join(opts)
    d.expect("Conan" in blob and "in progress" in blob, "saved list: Conan shows 'in progress'")
    d.expect("Lucius" in blob and "ready" in blob, "saved list: Lucius shows 'ready'")

    # 2) extract with no API key must NOT crash the screen (graceful)
    d.fill("Story text", "Conan drew his sword and faced the beast.")
    d.click_button("Extract characters (LLM)")
    d.shot("02_extract_nokey")
    d.expect("home" in d.body().lower(), "no-key extract: home screen still functional (no crash)")

    # 3) open a saved (ready) character -> resume to char-data, prefilled
    d.pick("Saved characters (from bucket)", "Lucius — ready")
    d.click_button("Open saved")
    d.wait_for_text(
        "Character: Lucius"
    )  # resume fires a long chained refresh — wait, don't race it
    d.shot("03_chardata")
    body = d.body()
    d.expect("Character: Lucius" in body, "open-saved: resumed to char-data for Lucius")
    d.expect("set on the passport step" in body, "char-data: base outfit read-only")
    d.expect(
        "angry, furious" in body and "smiling warmly" in body,
        "char-data: emotion table rendered",
    )

    # 4) optional block toggle (free) + 5) edit persists to state.json (free)
    d.check("Emotions")
    d.fill("Gender", "female")
    d.blur()
    d.shot("04_emotions_on_edited")
    state = read_state(bucket, "lucius")
    d.expect(
        state["character_table"].get("gender") == "female",
        "persistence: gender written to state.json",
    )
    d.expect(
        state["emotions"]["enabled"] is True,
        "persistence: emotions.enabled written to state.json",
    )

    # 6) navigation char-data -> passport
    d.click_button("Next → passport")
    d.shot("05_passport")
    d.expect("passport" in d.body().lower(), "navigation: Next reaches the passport screen")


def main() -> int:
    _work, bucket, shots = make_workdir()
    seed_character(
        bucket,
        "Conan",
        current_step="passport_face",
        table={"gender": "male", "age": "~30", "build": "powerful", "details": "scar"},
    )
    seed_character(bucket, "Lucius", current_step=None, style="inked grim comic")
    print(f"seeded bucket: {sorted(p.name for p in bucket.iterdir())}")

    demo, url = launch_app(bucket)
    try:
        with drive(url, shots) as d:
            run(d, bucket, url)
            return report(d, shots)
    finally:
        demo.close()  # type: ignore[attr-defined]


if __name__ == "__main__":
    raise SystemExit(main())
