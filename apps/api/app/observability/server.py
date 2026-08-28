"""Optional internal metrics listener for relay and worker processes."""

from __future__ import annotations

import asyncio
import secrets
from contextlib import suppress

from app.core.settings import settings
from app.infrastructure.database import update_db_pool_metrics
from app.observability.metrics import metrics_text, record_metrics_scrape

_PATH = b"/internal/metrics"


async def _handle_metrics_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    try:
        request = await reader.readuntil(b"\r\n\r\n")
        lines = request.split(b"\r\n")
        request_line = lines[0].split(b" ", 2)
        headers: dict[bytes, bytes] = {}
        for line in lines[1:]:
            if b":" not in line:
                continue
            name, value = line.split(b":", 1)
            headers[name.strip().lower()] = value.strip()
        expected = (
            settings.metrics_internal_token.get_secret_value().encode("utf-8")
            if settings.metrics_internal_token is not None
            else b""
        )
        provided = headers.get(b"x-mosaic-metrics-token", b"")
        if not provided:
            authorization = headers.get(b"authorization", b"")
            if authorization.lower().startswith(b"bearer "):
                provided = authorization[7:].strip()
        authorized = (
            len(request_line) == 3
            and request_line[0] == b"GET"
            and request_line[1] == _PATH
            and (not expected or secrets.compare_digest(provided, expected))
        )
        if not authorized:
            outcome = "denied" if expected else "other"
            record_metrics_scrape(outcome=outcome)
            await _write_response(writer, 404, b"not found\n", "text/plain; charset=utf-8")
            return
        update_db_pool_metrics()
        record_metrics_scrape(outcome="success")
        await _write_response(
            writer,
            200,
            metrics_text().encode("utf-8"),
            "text/plain; version=0.0.4; charset=utf-8",
        )
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, OSError, UnicodeError):
        return
    finally:
        writer.close()
        with suppress(Exception):
            await writer.wait_closed()


async def _write_response(
    writer: asyncio.StreamWriter,
    status: int,
    body: bytes,
    content_type: str,
) -> None:
    reason = "OK" if status == 200 else "Not Found"
    writer.write(
        f"HTTP/1.1 {status} {reason}\r\n"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n\r\n".encode("ascii")
        + body
    )
    await writer.drain()


async def start_internal_metrics_server() -> asyncio.AbstractServer | None:
    if not settings.metrics_enabled or not settings.metrics_server_enabled:
        return None
    return await asyncio.start_server(
        _handle_metrics_connection,
        host=settings.metrics_bind_host,
        port=settings.metrics_port,
        limit=8192,
    )


async def stop_internal_metrics_server(server: asyncio.AbstractServer | None) -> None:
    if server is None:
        return
    server.close()
    await server.wait_closed()


__all__ = ["start_internal_metrics_server", "stop_internal_metrics_server"]
