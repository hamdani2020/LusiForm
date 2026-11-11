"""Repository base classes.

Rules enforced here:
- Every query on a tenant table is built from `_scoped()`, which adds
  `WHERE partner_id = ctx.partner_id`. No method accepts a `partner_id` argument.
- `_add` takes `partner_id` from the context and refuses a caller-supplied one.
- A missing row and another partner's row both raise the same `NotFound`.
- Append-only/immutable repositories subclass `TenantRepository` only, so they
  expose reads and `add` but no update or delete. Only repositories that subclass
  `MutableRepository` can change or remove rows.
"""

import uuid
from typing import Any, Generic, TypeVar, cast

from sqlalchemy import Select, delete, inspect, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.context import RequestContext
from app.data.models.base import Base
from app.enums import Role
from app.errors import NotAuthorized, NotFound

M = TypeVar("M", bound=Base)

_PROTECTED_COLUMNS = frozenset({"id", "partner_id"})


class TenantRepository(Generic[M]):  # noqa: UP046 - TypeVar keeps mypy strict simple here
    """Read access plus a scoped insert for one tenant table."""

    model: type[M]

    def __init__(self, ctx: RequestContext, session: Session) -> None:
        self._ctx = ctx
        self._session = session

    def _col(self, name: str) -> Any:
        return getattr(self.model, name)

    def _scoped(self) -> Select[tuple[M]]:
        """The only way to start a query on this table."""
        return select(self.model).where(self._col("partner_id") == self._ctx.partner_id)

    def _order_by_pk(self, stmt: Select[tuple[M]]) -> Select[tuple[M]]:
        pk = inspect(self.model).primary_key
        return stmt.order_by(*pk)

    def list_all(self, *, limit: int = 100, offset: int = 0) -> list[M]:
        stmt = self._order_by_pk(self._scoped()).limit(limit).offset(offset)
        return list(self._session.execute(stmt).scalars())

    def _add(self, **values: Any) -> M:
        if "partner_id" in values:
            raise TypeError("partner_id comes from the request context, not the caller")
        obj = self.model(partner_id=self._ctx.partner_id, **values)
        self._session.add(obj)
        self._session.flush()
        return obj


class IdRepository(TenantRepository[M]):
    """Tenant table with a single `id` primary key."""

    def get(self, id: uuid.UUID) -> M:  # noqa: A002
        row = self._session.execute(
            self._scoped().where(self._col("id") == id)
        ).scalar_one_or_none()
        if row is None:
            raise NotFound
        return row


class MutableRepository(IdRepository[M]):
    """Scoped update/delete. Only repositories of mutable tables subclass this."""

    def _update(self, id: uuid.UUID, **values: Any) -> M:  # noqa: A002
        bad = _PROTECTED_COLUMNS & values.keys()
        if bad:
            raise TypeError(f"cannot update {sorted(bad)}")
        stmt = (
            update(self.model)
            .where(
                getattr(self.model, "id") == id,  # noqa: B009
                getattr(self.model, "partner_id") == self._ctx.partner_id,  # noqa: B009
            )
            .values(**values)
        )
        result = cast("CursorResult[Any]", self._session.execute(stmt))
        if result.rowcount == 0:
            raise NotFound
        reread = (
            self._scoped()
            .where(getattr(self.model, "id") == id)  # noqa: B009
            .execution_options(populate_existing=True)
        )
        return self._session.execute(reread).scalar_one()

    def _delete(self, id: uuid.UUID) -> None:  # noqa: A002
        stmt = delete(self.model).where(
            getattr(self.model, "id") == id,  # noqa: B009
            getattr(self.model, "partner_id") == self._ctx.partner_id,  # noqa: B009
        )
        result = cast("CursorResult[Any]", self._session.execute(stmt))
        if result.rowcount == 0:
            raise NotFound


class OperatorRepository:
    """Non-tenant tables (partners, template_versions). Platform operators only.

    Used only from operator routes; the role check here is a second line of defence
    behind `require_roles(platform_operator)` on the router.
    """

    def __init__(self, ctx: RequestContext, session: Session) -> None:
        if Role.PLATFORM_OPERATOR not in ctx.roles:
            raise NotAuthorized
        self._ctx = ctx
        self._session = session
