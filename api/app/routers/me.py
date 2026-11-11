"""`GET /api/me`: who the caller is. Proves token, context and repository end to end."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.context import RequestContext
from app.data.database import Database
from app.deps import get_database, get_request_context
from app.enums import Role

router = APIRouter(prefix="/api", dependencies=[Depends(get_request_context)])


class MeResponse(BaseModel):
    user_id: uuid.UUID
    partner_id: uuid.UUID
    partner_name: str
    email: str
    display_name: str | None
    roles: list[Role]


@router.get("/me")
def me(
    ctx: Annotated[RequestContext, Depends(get_request_context)],
    db: Annotated[Database, Depends(get_database)],
) -> MeResponse:
    with db.tenant(ctx) as repos:
        user = repos.users.get(ctx.user_id)
        partner = repos.partner.get()
        return MeResponse(
            user_id=ctx.user_id,
            partner_id=ctx.partner_id,
            partner_name=partner.name,
            email=user.email,
            display_name=user.display_name,
            roles=sorted(ctx.roles),
        )
