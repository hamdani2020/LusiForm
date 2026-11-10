"""FastAPI dependencies: database, token verifier, request context, role gating."""

import uuid
from collections.abc import Callable
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from lusiform_common import bind_log_context

from app.config import get_settings
from app.context import RequestContext
from app.data.database import Database
from app.enums import Role
from app.errors import NotAuthorized
from app.jwt_verifier import AuthUnavailable, JwtVerifier, TokenError

_bearer = HTTPBearer(auto_error=False)


@lru_cache
def get_database() -> Database:
    return Database.from_settings(get_settings())


@lru_cache
def get_verifier() -> JwtVerifier:
    try:
        return JwtVerifier.from_settings(get_settings())
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Authentication is not configured") from exc


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"}
    )


def get_request_context(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    verifier: Annotated[JwtVerifier, Depends(get_verifier)],
    db: Annotated[Database, Depends(get_database)],
) -> RequestContext:
    """Verify the bearer token and build the caller's `RequestContext`.

    Roles and partner come from the database for the verified `sub`, never from any
    claim or header the client controls (Requirement 5.3).
    """
    if credentials is None:
        raise _unauthorized()
    try:
        claims = verifier.verify(credentials.credentials)
    except TokenError:
        raise _unauthorized() from None
    except AuthUnavailable:
        raise HTTPException(status_code=503, detail="Authentication unavailable") from None

    identity = db.resolve_identity(claims.sub)
    if identity is None or not identity.is_active:
        # No record, deactivated/invited user, or suspended partner: same answer.
        raise NotAuthorized

    request_id = getattr(request.state, "request_id", None) or uuid.uuid4().hex
    bind_log_context(partner_id=str(identity.partner_id), user_id=str(identity.user_id))
    return RequestContext(
        user_id=identity.user_id,
        partner_id=identity.partner_id,
        roles=identity.roles,
        request_id=request_id,
    )


def require_roles(*roles: Role) -> Callable[..., RequestContext]:
    """Dependency factory: the caller must hold at least one of `roles`, else 403."""
    if not roles:
        raise ValueError("require_roles needs at least one role")

    def dependency(ctx: Annotated[RequestContext, Depends(get_request_context)]) -> RequestContext:
        if not ctx.has_role(*roles):
            raise NotAuthorized
        return ctx

    return dependency
