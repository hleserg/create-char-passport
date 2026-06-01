---
name: verifier-gradio
description: >-
  Runtime verification for the create-char-passport Gradio wizard. Use when
  verifying a change to the wizard UI / screens / handlers (the /verify skill
  auto-discovers this for the GUI surface). Launches the REAL build_demo()
  server and drives it in a browser (Playwright), seeding a temp bucket so
  saved-character / persistence paths are exercised without touching ./data.
---

# verifier-gradio

The repo's evidence-capture protocol for the Gradio wizard. The wizard threads
`gr.State(WizardSession)` through every event, so the only honest surface is a
**real browser** driving the **real launched app** — not `gradio_client`
(can't carry the State) and not import-and-call (the app never runs).

## One-time setup (per machine / fresh venv)

```bash
uv pip install playwright
uv run playwright install chromium
```

(Not a project dependency on purpose — it's verification tooling, kept out of
`pyproject.toml`.)

## Free, no-key mechanism / regression check — one command

Run **from the project dir** (uv resolves the env from cwd):

```bash
uv run python .claude/skills/verifier-gradio/smoke.py
```

It seeds a temp bucket (one "in progress" + one "ready" character), launches
the app, and drives the paths that need **no paid LLM call**:

- saved-character list populated from the bucket on app open (`demo.load`),
- open-saved → resume to the right screen, prefilled from `state.json`,
- base outfit shown read-only; optional blocks render,
- toggle a block + edit a field → assert it lands in `state.json` on disk,
- navigation char-data → passport.

The one LLM path it touches (Extract) is checked only for **graceful failure**
with no key (screen stays up, no crash). Exit code is non-zero if any critical
mechanism check regressed; screenshots are written under a printed temp dir.

This is the check to run **on every PR for free** — it confirms the plumbing
and catches regressions, no API key, no cost.

## Paid, end-to-end generation check (real inputs + key)

Only meaningful once a generation phase exists (HLE-728+) and you want to judge
**output quality / character-identity consistency** — which a human must eye.
Provide:

- `APP_GEMINI_API_KEY` in `.env` (real, paid calls; data leaves the machine —
  respect the project's PII rule, use throwaway inputs),
- ~5 real style reference images for the style step,
- character text (or let the harness fabricate it).

Write a scenario that uploads the refs, drafts+approves style, fills the trait
table and FACE/BODY/OUTFIT prompts, generates, and screenshots the frames for
human review. Reuse `harness.py` helpers; don't re-invent the launch/seed.

## Extending for new phases

Import `harness.py` and write a small scenario (see `smoke.py`). Helpers:
`make_workdir`, `seed_character`, `launch_app`, `read_state`, `drive(url, shots)`
yielding a `Drive` with `goto / shot / fill / blur / click_button / check /
pick / dropdown_options / body / expect / note`, and `report`.

## Gotchas already handled (don't re-discover)

- **Run `uv` from the project dir** — `cd $TEMP` then `uv run` loses the project
  env and `create_char_passport` won't import.
- **UTF-8 stdout** — harness reconfigures it; the UI text has `—` / `✓` and the
  Windows console is cp1251.
- **No `wait_for_load_state("networkidle")`** — Gradio keeps an SSE channel
  open, so it never idles; wait for a concrete element (the harness waits on the
  Extract button) then a short sleep for `demo.load`.
- **gr.State** — drive via Playwright, never `gradio_client`.

## Known finding (as of HLE-727)

On the no-API-key Extract path the home "notice" Markdown did not visibly
render the "No characters extracted" message (server ran, dropdowns updated,
no crash). Non-blocking; re-confirm whether it's a render quirk or a real
wiring gap when a key is available.
