"""Internal-only metrics endpoint."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

from app.core.settings import settings
from app.infrastructure.database import update_db_pool_metrics
from app.observability.metrics import metrics_text, record_metrics_scrape

router = APIRouter()


@router.get("/internal/metrics", include_in_schema=False)
async def metrics(request: Request) -> PlainTextResponse:
    if not settings.metrics_enabled:
        record_metrics_scrape(outcome="disabled")
        raise HTTPException(status_code=404, detail="not found")
    expected = (
        settings.metrics_internal_token.get_secret_value()
        if settings.metrics_internal_token is not None
        else ""
    )
    provided = request.headers.get("x-mosaic-metrics-token", "")
    if not provided:
        authorization = request.headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            provided = authorization[7:].strip()
    if expected and not secrets.compare_digest(provided, expected):
        record_metrics_scrape(outcome="denied")
        raise HTTPException(status_code=404, detail="not found")
    update_db_pool_metrics()
    record_metrics_scrape(outcome="success")
    return PlainTextResponse(
        metrics_text(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


__all__ = ["metrics", "router"]
