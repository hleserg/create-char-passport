# AGENTS.md

Canonical instructions for any coding agent (Claude Code, Cursor, Codex, …)
and humans working in this repo. Keep this file **lean and specific** — only
non-inferable facts. Style rules live in linters; deep detail lives in
`docs/development/DEVELOPMENT_STANDARD.md`.

## Overview

`create-char-passport` is a Gradio wizard deployed on Hugging Face Spaces that
guides users through building a character "passport" — a structured reference
set of images, descriptions, and traits — by orchestrating multi-turn calls to
the Gemini API. The single most important constraint: **character identity must
stay consistent across all generated assets** (every AI call must receive the
same canonical character descriptor), and because users upload real images the
app may process sensitive personal data — `sentry_sdk` must always run with
`send_default_pii=False` and raw user input must never be logged.

## Stack

- Python >= 3.12, `src/` layout, fully typed (ships `py.typed`).
- **uv** for env/deps (lockfile committed). **ruff** lint+format.
  **pyright** (standard). **pytest** (>=90% coverage). **Sentry** for monitoring.

## Commands (use these exactly)

```bash
uv sync --all-extras        # install everything into .venv
uv run <cmd>                # run anything inside the env
make check                  # THE quality gate — must be green
make test-fast              # quick unit loop while iterating
```

## Definition of Done (hard gate)

A change is **done** only when `make check` passes with **zero** errors:
`ruff check` + `ruff format --check` + `pyright` + `bandit` + `pip-audit` +
`pytest --cov --cov-fail-under=90`. No exceptions, no "fix later".

Also required:
- New/changed public functions have type hints and a one-line docstring.
- New behavior has a test. Bugfixes add a regression test.
- No new lint/type errors committed.

## Hard constraints (do not violate)

- **Sentry `send_default_pii=False`** always. This codebase may handle
  sensitive data — never weaken scrubbing or log raw user input.
- **Secrets only in `.env`** (git-ignored). Document new keys in `.env.example`.
  Never hardcode credentials; never read `os.environ` directly — use
  `create_char_passport.config.get_settings()`.
- **Conventional Commits** (`feat:`, `fix:`, `feat!:` …). Commits/comments in
  English. Versioning via Commitizen.
- **Docs are English-canonical**; user-facing docs add an `-ru.md` pair, edited
  English-first then synced.

## PLAYBOOK markers

When you introduce a *generalizable* engineering pattern (passes the
"substitution test" — still meaningful after removing project-specific nouns),
add a `# PLAYBOOK-START … # PLAYBOOK-END` block next to the code.
Spec: `docs/development/PLAYBOOK_MARKERS.md`. When unsure, add one with
`status: draft`. Pre-commit validates them.

## Issue / PR workflow (Linear)

- On taking an issue: set it **In Progress** *before* writing code.
- On finishing: set **Done** immediately and link the PR.
- PR body: `Closes …` / Changes / Testing / Notes / DoD checklist.
- After opening a PR: fix **every** review-bot comment and **every** red
  check. Do not merge until all checks are green and bots have signed off.

## Repo map

| Path | What |
|------|------|
| `app.py` | HF Spaces entry point — exposes `demo = build_demo()` |
| `src/create_char_passport/` | the package |
| `src/create_char_passport/gradio_app.py` | Gradio `build_demo()` factory |
| `src/create_char_passport/config.py` | typed settings (env access lives here only) |
| `src/create_char_passport/observability/` | Sentry init + component tagging |
| `tests/{unit,integration}/` | tests |
| `docs/` | architecture (ADRs), dev standard, PLAYBOOK spec |
| `plan/` | product specs and wireframes |
| `scripts/` | `init_template.py`, `extract_playbook.py` |
| `tools/check_instrumentation.py` | pre-commit guard for Sentry tagging |
