---
title: Create Char Passport
emoji: 🎭
colorFrom: purple
colorTo: blue
sdk: gradio
sdk_version: "4.0"
app_file: app.py
pinned: false
license: mit
---

# create-char-passport

> Gradio wizard that builds a character "passport" reference set via the Gemini API

[![CI](https://github.com/hleserg/create-char-passport/actions/workflows/ci.yml/badge.svg)](https://github.com/hleserg/create-char-passport/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)

[Русская версия](README-ru.md)

`create-char-passport` is a Gradio application deployed on Hugging Face Spaces that guides
users through building a structured character "passport" — a consistent set of images,
descriptions, and traits — by orchestrating calls to the Gemini API.

---

## Quickstart (local)

```bash
uv sync --all-extras        # create .venv and install everything
cp .env.example .env        # fill in secrets (never commit)
# edit .env: APP_GEMINI_API_KEY=<your-key>
uv run python app.py        # launches Gradio on http://127.0.0.1:7860
make check                  # Definition-of-Done gate (lint + types + tests)
```

## HF Spaces secrets

On Hugging Face Spaces, configure these as Space Secrets (Settings → Variables and secrets):

| Secret | Description |
|--------|-------------|
| `APP_GEMINI_API_KEY` | Google Gemini API key |
| `APP_HF_DATASET_BUCKET` | HF dataset repo for asset storage (`owner/repo`) |

pydantic-settings reads them from the environment automatically — no `.env` file needed on Spaces.

## Project layout

| Path | Purpose |
|------|---------|
| `app.py` | HF Spaces entry point — exposes `demo` |
| `src/create_char_passport/` | the package (src-layout, fully typed, ships `py.typed`) |
| `src/create_char_passport/gradio_app.py` | Gradio `build_demo()` factory |
| `src/create_char_passport/config.py` | typed settings via `pydantic-settings` |
| `src/create_char_passport/observability/` | Sentry init (`send_default_pii=False`) |
| `tests/` | `unit/` + `integration/`, pytest ≥ 90 % coverage gate |
| `docs/` | architecture (ADRs), development standard, PLAYBOOK marker spec |
| `plan/` | product specs and wireframes |
| `AGENTS.md` | canonical agent/human instructions |

## Make targets

```
make install     # uv sync --all-extras + pre-commit install
make check       # lint + fmt-check + type + security + tests  (DoD gate)
make test        # full test suite with coverage
make test-fast   # unit tests only, parallel, no coverage
make lint        # ruff check
make fmt         # ruff format
make type        # pyright
```

## Tooling

- **uv** — environment & dependency management (lockfile committed)
- **ruff** — lint + format
- **pyright** — static type checking (standard mode)
- **pytest** — tests, ≥ 90 % coverage
- **bandit / pip-audit** — security scanning
- **pre-commit** — local commit gate
- **commitizen** — conventional commits → version bump + changelog
- **Sentry** — error monitoring, `send_default_pii=False`

## License

MIT — see [LICENSE](LICENSE).
