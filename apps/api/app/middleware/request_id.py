import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.request_id import bind_request_id, new_request_id, reset_request_id
from app.observability.logging import log_event
from app.observability.metrics import normalize_route, record_http_request


class RequestIdMiddleware:
    """Attach a server-generated request ID without buffering streaming bodies."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = new_request_id()
        scope.setdefault("state", {})["request_id"] = request_id
        token = bind_request_id(request_id)
        started = time.perf_counter()
        status_code = 500
        recorded = False

        def record_completed() -> None:
            nonlocal recorded
            if recorded:
                return
            recorded = True
            duration_seconds = max(0.0, time.perf_counter() - started)
            route = normalize_route(str(scope.get("path", "/other")))
            record_http_request(
                method=str(scope.get("method", "OTHER")),
                path=route,
                status_code=status_code,
                duration_seconds=duration_seconds,
            )
            log_event(
                "http.request.completed",
                method=str(scope.get("method", "OTHER")),
                route=route,
                status_code=status_code,
                duration_ms=round(duration_seconds * 1000, 3),
            )

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message.get("type") == "http.response.start":
                raw_status = message.get("status")
                if isinstance(raw_status, int):
                    status_code = raw_status
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() != b"x-request-id"
                ]
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": headers}
            if message.get("type") == "http.response.body" and not message.get("more_body", False):
                record_completed()
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            record_completed()
            reset_request_id(token)
