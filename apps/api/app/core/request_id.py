from contextvars import ContextVar, Token
from uuid import uuid4

_request_id: ContextVar[str | None] = ContextVar("mosaic_request_id", default=None)


def new_request_id() -> str:
    """Create a server-owned correlation ID.

    Client supplied IDs are deliberately not trusted at this boundary. A future
    edge proxy may pass a separately authenticated trace context, but arbitrary
    request headers must not be allowed to forge log correlation fields.
    """

    return str(uuid4())


def bind_request_id(request_id: str) -> Token[str | None]:
    return _request_id.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    _request_id.reset(token)


def current_request_id() -> str:
    return _request_id.get() or new_request_id()


def current_request_id_or_system() -> str:
    """Return the bound HTTP ID, or an honest low-cardinality system marker."""

    return _request_id.get() or "system"


__all__ = [
    "bind_request_id",
    "current_request_id",
    "current_request_id_or_system",
    "new_request_id",
    "reset_request_id",
]
