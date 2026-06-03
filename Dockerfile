# Docker image for the redesigned FastAPI + SPA frontend (HLE-837, P3).
# Serves the web/ SPA and the JSON API via uvicorn. Deployed to a Hugging Face
# Docker Space (sdk: docker, app_port 7860). The legacy Gradio app (app.py) is
# unaffected — this is a separate entry point (create_char_passport.webapp:app).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN pip install --no-cache-dir uv

WORKDIR /app

# Install the package + deps first (better layer caching). pyproject references
# README.md, so it must be present for the build.
COPY pyproject.toml README.md ./
COPY src ./src
RUN uv pip install --system --no-cache .

# The SPA bundle (served statically) + a writable bucket for character state.
COPY web ./web
RUN useradd -m -u 1000 user && mkdir -p /app/data && chown -R user /app/data

ENV CPH_WEB_DIR=/app/web \
    APP_BUCKET_PATH=/app/data \
    GRADIO_SSR_MODE=false

USER user
EXPOSE 7860

# HF Spaces routes traffic to app_port (7860).
CMD ["uvicorn", "create_char_passport.webapp:app", "--host", "0.0.0.0", "--port", "7860"]
