FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
WORKDIR /app

# Dependencies first, so this layer is cached until the lockfile changes.
COPY pyproject.toml uv.lock README.md ./
ARG EXTRAS="--extra ui --extra local-embeddings"
RUN uv sync --frozen --no-dev --no-install-project ${EXTRAS}

COPY src ./src
COPY data ./data
RUN uv sync --frozen --no-dev ${EXTRAS}

# The local embedding model is baked into the image: no download at start-up, no external dependency.
ARG PRELOAD_LOCAL_MODEL=true
ENV FASTEMBED_CACHE_PATH=/opt/fastembed
RUN if [ "$PRELOAD_LOCAL_MODEL" = "true" ]; then \
      /app/.venv/bin/python -c "from fastembed import TextEmbedding; TextEmbedding('intfloat/multilingual-e5-large')"; fi

# Files stay root-owned and world-readable (a recursive chown would duplicate the whole venv layer).
RUN useradd --system --uid 10001 --no-create-home app
USER app
ENV PATH="/app/.venv/bin:$PATH" HOME=/tmp
EXPOSE 8000 8501
CMD ["cvsearch", "api"]
