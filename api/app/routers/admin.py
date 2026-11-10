"""Role-gated router factories.

Factories (not module-level routers) so tests can mount probe routes on their own
instance. The module-level routers are the ones the app mounts.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.context import RequestContext
from app.data.database import Database
from app.deps import get_database, get_request_context, require_roles
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


class PartnerOut(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    created_at: datetime


@operator_router.get("/partners")
def list_partners(
    ctx: Annotated[RequestContext, Depends(get_request_context)],
    db: Annotated[Database, Depends(get_database)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[PartnerOut]:
    """Cross-partner read. The access is audited in the same transaction as the read:
    if the audit row cannot be written, the request fails and nothing is returned."""
    with db.operator(ctx) as repos:
        partners = repos.partners.list_all(limit=limit, offset=offset)
        repos.audit.add(
            "operator.partners.list",
            "partner",
            after={"limit": limit, "offset": offset, "returned": len(partners)},
        )
        return [
            PartnerOut(id=p.id, name=p.name, status=p.status, created_at=p.created_at)
            for p in partners
        ]
