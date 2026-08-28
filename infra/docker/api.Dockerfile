# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:0.11.28 AS uv
FROM python:3.12-slim AS runtime

ARG MOSAIC_BUILD_REVISION=local
COPY --from=uv /uv /uvx /usr/local/bin/

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV PATH="/app/apps/api/.venv/bin:${PATH}"
ENV PYTHONPATH=/app/apps/api
ENV HOME=/home/mosaic
ENV MOSAIC_SOURCE_COMMIT=${MOSAIC_BUILD_REVISION}
ENV MOSAIC_SOURCE_TREE_CLEAN=true
WORKDIR /app

LABEL org.opencontainers.image.revision=${MOSAIC_BUILD_REVISION}

COPY apps/api/pyproject.toml apps/api/uv.lock /app/apps/api/
RUN uv sync --project /app/apps/api --frozen --no-dev --no-install-project

RUN groupadd --gid 10001 mosaic \
    && useradd --uid 10001 --gid 10001 --create-home --no-log-init mosaic
COPY --chown=mosaic:mosaic apps/api /app/apps/api
RUN uv sync --project /app/apps/api --frozen --no-dev --no-editable \
    && chown -R mosaic:mosaic /app/apps/api

USER mosaic
WORKDIR /app
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=10s --timeout=4s --start-period=20s --retries=6 \
  CMD /app/apps/api/.venv/bin/python -c "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=2); raise SystemExit(0 if r.status == 200 else 1)"
CMD ["/app/apps/api/.venv/bin/uvicorn", "app.main:app", "--app-dir", "/app/apps/api", "--host", "0.0.0.0", "--port", "8000"]
