# Loopboard as one image: the frontend built to static files, served by the API.
#
#   docker build -t loopboard .
#   docker run -p 8000:8000 -v loopboard-data:/data loopboard
#
# Then open http://localhost:8000 (API docs at /docs).

# ---------------------------------------------------------------- frontend ---
FROM node:22-slim AS frontend

WORKDIR /frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
# A static SPA build (see vite.config.ts); an empty API URL makes the client
# call the API on the origin that served it.
ENV LOOPBOARD_SPA=1 \
    VITE_API_URL=""
RUN npm run build

# ----------------------------------------------------------------- backend ---
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.9 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first, so code changes don't reinstall them.
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY backend/app ./app
RUN uv sync --locked --no-dev

COPY --from=frontend /frontend/dist/client ./static

RUN useradd --system --create-home loopboard \
    && mkdir /data \
    && chown loopboard /data
USER loopboard

ENV PATH="/app/.venv/bin:$PATH" \
    LOOPBOARD_STATIC_DIR=/app/static \
    LOOPBOARD_DATABASE_URL=sqlite:////data/loopboard.db
VOLUME /data

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
