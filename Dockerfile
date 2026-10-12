# syntax=docker/dockerfile:1

# Build stage. uv resolves into /app/.venv, which the runtime stage copies wholesale.
FROM python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies before source: this layer survives every commit that does not touch the
# lockfile, which is almost all of them.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

COPY src ./src
COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev


# Runtime stage. No uv, no build cache, no source tree beyond the installed package.
FROM python:3.12-slim-bookworm

RUN groupadd --system app && useradd --system --gid app --no-log-init app

WORKDIR /app

COPY --from=builder --chown=app:app /app/.venv /app/.venv

# Put the venv first so `uvicorn` and `python` resolve to it without an activate step.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

USER app

EXPOSE 8000

# Hits the app's own readiness endpoint. A 503 here means a dependency is down, which is a
# real unhealthy state, so the status code is not discarded.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

# Shell form so $PORT expands: App Service injects its own port and expects the container
# to honour it.
CMD uvicorn ai_employee.api.main:app --host 0.0.0.0 --port ${PORT}