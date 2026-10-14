FROM python:3.12-slim

# uv para instalar rapido y respetar el lock
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

# Capa de dependencias aparte del codigo: cambia mucho menos seguido.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --extra server

COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra server
