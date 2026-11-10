"""Role-gated router factories.

Factories (not module-level routers) so tests can mount probe routes on their own
instance. Task 6 adds the first operator route, `GET /api/admin/partners`.
"""

from fastapi import APIRouter, Depends

from app.deps import require_roles
from app.enums import Role


def make_admin_router() -> APIRouter:
    """Partner admins and platform operators."""
    return APIRouter(
        prefix="/api/admin",
        dependencies=[Depends(require_roles(Role.PARTNER_ADMIN, Role.PLATFORM_OPERATOR))],
    )


def make_operator_router() -> APIRouter:
    """Cross-partner routes: platform operators only."""
    return APIRouter(
        prefix="/api/admin",
        dependencies=[Depends(require_roles(Role.PLATFORM_OPERATOR))],
    )


admin_router = make_admin_router()
operator_router = make_operator_router()
