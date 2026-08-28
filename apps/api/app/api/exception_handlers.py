from typing import cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.auth.errors import AuthError
from app.contracts.errors import ErrorBody, ErrorResponse
from app.core.request_id import current_request_id


async def unhandled_exception_handler(request: Request, _: Exception) -> JSONResponse:
    """Return a stable public error without exposing exception or Provider details."""

    request_id = getattr(request.state, "request_id", None) or current_request_id()
    body = ErrorResponse(
        error=ErrorBody(
            code="INTERNAL_SERVER_ERROR",
            message="服务暂时不可用",
            request_id=request_id,
            retryable=True,
        )
    )
    return JSONResponse(
        status_code=500,
        content=body.model_dump(),
        headers={"x-request-id": request_id},
    )


async def auth_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    auth_error = cast(AuthError, exc)
    request_id = getattr(request.state, "request_id", None) or current_request_id()
    body = ErrorResponse(
        error=ErrorBody(
            code=auth_error.code,
            message=auth_error.message,
            request_id=request_id,
            retryable=auth_error.retryable,
            details=auth_error.details,
        )
    )
    return JSONResponse(
        status_code=auth_error.status_code,
        content=body.model_dump(exclude_none=True),
        headers={"x-request-id": request_id, "Cache-Control": "no-store"},
    )


async def request_validation_exception_handler(
    request: Request,
    _: Exception,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None) or current_request_id()
    body = ErrorResponse(
        error=ErrorBody(
            code="REQUEST_VALIDATION_FAILED",
            message="请求参数无效",
            request_id=request_id,
            retryable=False,
        )
    )
    return JSONResponse(
        status_code=422,
        content=body.model_dump(),
        headers={"x-request-id": request_id},
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AuthError, auth_exception_handler)
    app.add_exception_handler(RequestValidationError, request_validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
