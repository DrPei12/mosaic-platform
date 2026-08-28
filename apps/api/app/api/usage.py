from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import require_permission
from app.auth.repository import CurrentAuth
from app.contracts.usage import UsageSummaryResponse
from app.infrastructure.database import get_db_session
from app.usage.service import UsageService

router = APIRouter(prefix="/api/v1/usage", tags=["usage"])
require_usage_permission = require_permission("usage:read")


@router.get("", response_model=UsageSummaryResponse)
async def get_usage_summary(
    response: Response,
    auth: Annotated[CurrentAuth, Depends(require_usage_permission)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> UsageSummaryResponse:
    response.headers["Cache-Control"] = "no-store"
    return await UsageService(session).summary(
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        role=auth.role,
    )


__all__ = ["get_usage_summary", "router"]
