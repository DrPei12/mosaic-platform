import pytest

from app.auth.permissions import has_permission


@pytest.mark.parametrize(
    ("role", "permission", "allowed"),
    [
        ("owner", "tenant:manage", True),
        ("admin", "tenant:manage", True),
        ("member", "generation:use", True),
        ("member", "tenant:manage", False),
        ("billing_viewer", "usage:read", True),
        ("billing_viewer", "conversation:use", False),
        ("operator", "tenant:manage", False),
    ],
)
def test_permission_matrix(role: str, permission: str, allowed: bool) -> None:
    assert has_permission(role, permission) is allowed  # type: ignore[arg-type]
