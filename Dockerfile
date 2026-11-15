# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
WORKDIR /app

# Dependencies first, so this layer is cached until the lockfile changes.
COPY pyproject.toml uv.lock README.md ./
ARG EXTRAS="--extra ui"
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project ${EXTRAS}

COPY src ./src
COPY data ./data
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev ${EXTRAS}

# The local embedding model is baked in only when the local extra is requested.
ARG PRELOAD_LOCAL_MODEL=false
ENV FASTEMBED_CACHE_PATH=/opt/fastembed
RUN if [ "$PRELOAD_LOCAL_MODEL" = "true" ]; then \
      /app/.venv/bin/python -c "from fastembed import TextEmbedding; TextEmbedding('intfloat/multilingual-e5-large')"; fi

RUN mkdir -p /opt/fastembed && useradd --system --uid 10001 app && chown -R app /app /opt/fastembed
USER app
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000 8501
CMD ["cvsearch", "api"]
