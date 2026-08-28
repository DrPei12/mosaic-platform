from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Literal

from fastapi import Depends

from app.auth.dependencies import (
    current_auth,
    current_auth_allow_restricted,
    require_authenticated_csrf,
)
from app.auth.errors import AuthError
from app.auth.repository import CurrentAuth

Permission = Literal[
    "catalog:read",
    "conversation:use",
    "generation:use",
    "usage:read",
    "session:manage_self",
    "tenant:manage",
]

_ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "owner": frozenset(
        {
            "catalog:read",
            "conversation:use",
            "generation:use",
            "usage:read",
            "session:manage_self",
            "tenant:manage",
        }
    ),
    "admin": frozenset(
        {
            "catalog:read",
            "conversation:use",
            "generation:use",
            "usage:read",
            "session:manage_self",
            "tenant:manage",
        }
    ),
    "member": frozenset(
        {
            "catalog:read",
            "conversation:use",
            "generation:use",
            "usage:read",
            "session:manage_self",
        }
    ),
    "billing_viewer": frozenset({"catalog:read", "usage:read", "session:manage_self"}),
}

_TENANT_USAGE_ROLES = frozenset({"owner", "admin", "billing_viewer"})


def has_permission(role: str, permission: Permission) -> bool:
    return permission in _ROLE_PERMISSIONS.get(role, frozenset())


def can_view_tenant_usage(role: str) -> bool:
    """Return whether a role may see tenant-wide usage and ledger detail."""

    return role in _TENANT_USAGE_ROLES


def require_permission(permission: Permission) -> Callable[..., Awaitable[CurrentAuth]]:
    async def dependency(
        auth: Annotated[CurrentAuth, Depends(current_auth)],
    ) -> CurrentAuth:
        if not has_permission(auth.role, permission):
            raise AuthError(
                status_code=403,
                code="AUTHORIZATION_DENIED",
                message="无权执行该操作",
            )
        return auth

    return dependency


def require_permission_allow_restricted(
    permission: Permission,
) -> Callable[..., Awaitable[CurrentAuth]]:
    async def dependency(
        auth: Annotated[CurrentAuth, Depends(current_auth_allow_restricted)],
    ) -> CurrentAuth:
        if not has_permission(auth.role, permission):
            raise AuthError(
                status_code=403,
                code="AUTHORIZATION_DENIED",
                message="无权执行该操作",
            )
        return auth

    return dependency


def require_csrf_permission(permission: Permission) -> Callable[..., Awaitable[CurrentAuth]]:
    async def dependency(
        auth: Annotated[CurrentAuth, Depends(require_authenticated_csrf)],
    ) -> CurrentAuth:
        if not has_permission(auth.role, permission):
            raise AuthError(
                status_code=403,
                code="AUTHORIZATION_DENIED",
                message="无权执行该操作",
            )
        return auth

    return dependency


__all__ = [
    "Permission",
    "can_view_tenant_usage",
    "has_permission",
    "require_csrf_permission",
    "require_permission",
    "require_permission_allow_restricted",
]
