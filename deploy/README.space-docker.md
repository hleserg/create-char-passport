---
title: Паспорт героя
emoji: 📔
colorFrom: red
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
short_description: Конструктор референсов персонажа для графического романа
---

# Паспорт героя — новый интерфейс (Docker)

Redesigned FastAPI + SPA frontend for `create-char-passport` (HLE-834). Serves
the `web/` design SPA and a JSON API over the same pure core as the Gradio app.

This README is uploaded **as `README.md`** to the Docker Space by
`scripts/deploy_space.py`; the GitHub repo keeps its own (Gradio) README.

## Secrets / variables (set in Space settings)

- `APP_GEMINI_API_KEY` — Gemini API key (required for real generation).
- `APP_BUCKET_PATH` — defaults to `/app/data` (ephemeral). Add persistent
  storage and point this at `/data` to keep characters across restarts.

The container runs `uvicorn create_char_passport.webapp:app` on port 7860.
