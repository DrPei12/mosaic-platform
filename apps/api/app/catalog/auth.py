"""Small authentication seam used by the catalog router.

The identity worker owns session validation.  Keeping this module as a narrow
seam lets the catalog remain importable while that worker is being integrated:
the worker can re-export its ``CurrentAuth`` and dependency here, or the API
composition root can override ``get_current_auth``.  The fallback is fail
closed and intentionally never creates a demo tenant.
"""

from __future__ import annotations

# The auth worker is the owner of session validation.  The catalog depends on
# its real CurrentAuth dependency directly; keeping this import in one small
# adapter module gives the composition root one obvious seam if auth is moved.
from app.auth.dependencies import current_auth as get_current_auth
from app.auth.repository import CurrentAuth

__all__ = ["CurrentAuth", "get_current_auth"]
