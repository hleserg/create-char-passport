# create-char-passport

> Gradio-мастер для создания «паспорта» персонажа через Gemini API

[English version](README.md)

`create-char-passport` — Gradio-приложение, развёрнутое на Hugging Face Spaces.
Проводит пользователя через пошаговый сбор структурированного «паспорта»
персонажа: согласованного набора изображений, описаний и черт — с помощью Gemini API.

---

## Быстрый старт (локально)

```bash
uv sync --all-extras        # создаёт .venv и устанавливает всё
cp .env.example .env        # заполни секреты (никогда не коммитить)
# отредактируй .env: APP_GEMINI_API_KEY=<твой ключ>
uv run python app.py        # запускает Gradio на http://127.0.0.1:7860
make check                  # ворота качества (линт + типы + тесты)
```

## Секреты для HF Spaces

На Hugging Face Spaces выставь через Space Secrets (Settings → Variables and secrets):

| Секрет | Описание |
|--------|----------|
| `APP_GEMINI_API_KEY` | Ключ Google Gemini API |
| `APP_HF_DATASET_BUCKET` | HF-датасет-репо для хранения ассетов (`owner/repo`) |

pydantic-settings читает их из окружения — файл `.env` на Spaces не нужен.

## Структура проекта

| Путь | Что |
|------|-----|
| `app.py` | Точка входа для HF Spaces |
| `src/create_char_passport/` | Пакет (src-layout, полная типизация, `py.typed`) |
| `src/create_char_passport/gradio_app.py` | Фабрика `build_demo()` |
| `src/create_char_passport/config.py` | Типизированные настройки через pydantic-settings |
| `src/create_char_passport/observability/` | Sentry (`send_default_pii=False`) |
| `tests/` | `unit/` + `integration/`, покрытие ≥ 90 % |
| `plan/` | Спецификации и вайрфреймы |
| `AGENTS.md` | Контракт для агентов и людей |

## Инструменты

uv (окружение/зависимости), ruff (линт+формат), pyright (типы),
pytest (тесты, ≥ 90 %), bandit/pip-audit (безопасность), pre-commit,
commitizen (conventional commits → версия + changelog), Sentry.

## Лицензия

MIT — см. [LICENSE](LICENSE).
