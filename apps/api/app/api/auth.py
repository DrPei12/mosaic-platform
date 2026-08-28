"""Native cookie-session authentication endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from app.audit.writer import AuditContext
from app.auth.dependencies import (
    CSRF_COOKIE_NAME,
    current_auth_optional,
    get_auth_service,
    require_authenticated_csrf_allow_restricted,
    require_public_auth_request,
    validate_same_site_request,
)
from app.auth.permissions import (
    require_csrf_permission,
    require_permission,
    require_permission_allow_restricted,
)
from app.auth.repository import CurrentAuth, SessionRecord
from app.auth.service import AuthService
from app.contracts.auth import (
    AuthSessionResponse,
    LoginRequest,
    PasswordChangeRequest,
    RegisterRequest,
    UserSessionListResponse,
    UserSessionResponse,
)
from app.core.settings import settings

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
require_session_management = require_permission("session:manage_self")
require_session_management_csrf = require_csrf_permission("session:manage_self")
require_session_management_allow_restricted = require_permission_allow_restricted(
    "session:manage_self"
)


def _request_ip(request: Request) -> str | None:
    return request.client.host if request.client is not None else None


def _audit_context(request: Request) -> AuditContext:
    raw_request_id = getattr(request.state, "request_id", None)
    try:
        request_id = UUID(str(raw_request_id)) if raw_request_id is not None else None
    except ValueError:
        request_id = None
    return AuditContext(
        request_id=request_id,
        ip_address=_request_ip(request),
        user_agent=request.headers.get("user-agent"),
    )


def _set_session_cookies(response: Response, session: SessionRecord) -> None:
    max_age = max(1, int((session.expires_at - datetime.now(UTC)).total_seconds()))
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session.session_token,
        max_age=max_age,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=session.csrf_token,
        max_age=max_age,
        httponly=False,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"


@router.get("/me", response_model=AuthSessionResponse)
async def me(
    auth: Annotated[CurrentAuth, Depends(require_session_management_allow_restricted)],
    response: Response,
) -> AuthSessionResponse:
    response.headers["Cache-Control"] = "no-store"
    return AuthSessionResponse(
        authenticated=True,
        password_change_required=auth.password_change_required,
    )


@router.post(
    "/login",
    response_model=AuthSessionResponse,
    dependencies=[Depends(require_public_auth_request)],
)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthSessionResponse:
    session = await service.login(
        payload,
        ip_address=_request_ip(request),
        user_agent=request.headers.get("user-agent"),
        audit_context=_audit_context(request),
    )
    _set_session_cookies(response, session)
    return AuthSessionResponse(
        authenticated=True,
        password_change_required=session.password_change_required,
    )


@router.post(
    "/register",
    response_model=AuthSessionResponse,
    status_code=201,
    dependencies=[Depends(require_public_auth_request)],
)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthSessionResponse:
    session = await service.register(
        payload,
        ip_address=_request_ip(request),
        user_agent=request.headers.get("user-agent"),
        audit_context=_audit_context(request),
    )
    _set_session_cookies(response, session)
    return AuthSessionResponse(
        authenticated=True,
        password_change_required=session.password_change_required,
    )


@router.post("/password/change", status_code=204)
async def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
    auth: Annotated[
        CurrentAuth,
        Depends(require_authenticated_csrf_allow_restricted),
    ],
) -> Response:
    session = await service.change_password(
        auth,
        current_password=payload.current_password,
        new_password=payload.new_password,
        ip_address=_request_ip(request),
        user_agent=request.headers.get("user-agent"),
        audit_context=_audit_context(request),
    )
    _set_session_cookies(response, session)
    response.status_code = 204
    return response


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
    auth: Annotated[CurrentAuth | None, Depends(current_auth_optional)],
) -> Response:
    session_token = request.cookies.get(settings.session_cookie_name)
    if auth is not None:
        validate_same_site_request(request, require_json=False)
        service.verify_csrf(
            auth,
            request.headers.get("X-CSRF-Token"),
            request.cookies.get(CSRF_COOKIE_NAME),
        )
        await service.logout(session_token, audit_context=_audit_context(request))
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(
        key=CSRF_COOKIE_NAME,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=False,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/sessions", response_model=UserSessionListResponse)
async def list_sessions(
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
    auth: Annotated[CurrentAuth, Depends(require_session_management)],
) -> UserSessionListResponse:
    records = await service.list_sessions(auth)
    response.headers["Cache-Control"] = "no-store"
    return UserSessionListResponse(
        items=[
            UserSessionResponse(
                session_id=str(record.session_id),
                current=record.session_id == auth.session_id,
                created_at=record.created_at,
                last_seen_at=record.last_seen_at,
                expires_at=record.expires_at,
                ip_address=record.ip_address,
                user_agent=record.user_agent,
            )
            for record in records
        ]
    )


@router.delete("/sessions/{session_id}", status_code=204)
async def revoke_session(
    session_id: UUID,
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
    auth: Annotated[CurrentAuth, Depends(require_session_management_csrf)],
) -> Response:
    await service.revoke_other_session(
        auth,
        session_id,
        audit_context=_audit_context(request),
    )
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


__all__ = ["router"]
