"""Repositories for the foundation entities.

Immutable and append-only tables (`audit_events` here) get repositories that
subclass `IdRepository` only: reads plus `add`, no update or delete. Other tables
get repositories in the specs that use them.
"""

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.context import RequestContext
from app.data.audit_payload import sanitize
from app.data.base import IdRepository, MutableRepository, OperatorRepository, TenantRepository
from app.data.models import (
    AuditEvent,
    IntakeDraft,
    Partner,
    Project,
    TemplateVersion,
    User,
    UserRole,
)
from app.enums import PartnerStatus, Role, TemplateStatus, UserStatus
from app.errors import NotFound

# --- tenant repositories (every query is scoped to ctx.partner_id) ---


class UserRepository(MutableRepository[User]):
    model = User

    def add(
        self,
        email: str,
        *,
        display_name: str | None = None,
        cognito_sub: str | None = None,
        status: UserStatus = UserStatus.INVITED,
    ) -> User:
        return self._add(
            email=email.strip().lower(),
            display_name=display_name,
            cognito_sub=cognito_sub,
            status=status.value,
        )

    def get_by_email(self, email: str) -> User:
        stmt = self._scoped().where(User.email == email.strip().lower())
        row = self._session.execute(stmt).scalar_one_or_none()
        if row is None:
            raise NotFound
        return row

    def set_status(self, id: uuid.UUID, status: UserStatus) -> User:  # noqa: A002
        return self._update(id, status=status.value)

    def set_display_name(self, id: uuid.UUID, display_name: str | None) -> User:  # noqa: A002
        return self._update(id, display_name=display_name)


class UserRoleRepository(TenantRepository[UserRole]):
    model = UserRole

    def roles_for(self, user_id: uuid.UUID) -> frozenset[Role]:
        stmt = self._scoped().where(UserRole.user_id == user_id)
        return frozenset(Role(r.role) for r in self._session.execute(stmt).scalars())

    def grant(self, user_id: uuid.UUID, role: Role) -> UserRole:
        owned = self._session.execute(
            select(User.id).where(User.id == user_id, User.partner_id == self._ctx.partner_id)
        ).scalar_one_or_none()
        if owned is None:
            raise NotFound  # another partner's user looks exactly like a missing one
        return self._add(user_id=user_id, role=role.value)

    def revoke(self, user_id: uuid.UUID, role: Role) -> None:
        stmt = delete(UserRole).where(
            UserRole.user_id == user_id,
            UserRole.role == role.value,
            UserRole.partner_id == self._ctx.partner_id,
        )
        result: CursorResult[Any] = self._session.execute(stmt)  # type: ignore[assignment]
        if result.rowcount == 0:
            raise NotFound


class ProjectRepository(MutableRepository[Project]):
    model = Project

    def add(self, name: str) -> Project:
        return self._add(name=name, created_by=self._ctx.user_id)

    def rename(self, id: uuid.UUID, name: str) -> Project:  # noqa: A002
        return self._update(id, name=name)


class IntakeDraftRepository(MutableRepository[IntakeDraft]):
    model = IntakeDraft

    def get_for_project(self, project_id: uuid.UUID) -> IntakeDraft:
        stmt = self._scoped().where(IntakeDraft.project_id == project_id)
        row = self._session.execute(stmt).scalar_one_or_none()
        if row is None:
            raise NotFound
        return row

    def save(self, project_id: uuid.UUID, intake_json: dict[str, Any]) -> IntakeDraft:
        """Create or replace the draft for a project owned by the caller's partner."""
        owned = self._session.execute(
            select(Project.id).where(
                Project.id == project_id, Project.partner_id == self._ctx.partner_id
            )
        ).scalar_one_or_none()
        if owned is None:
            raise NotFound  # another partner's project looks exactly like a missing one
        try:
            existing = self.get_for_project(project_id)
        except NotFound:
            return self._add(project_id=project_id, intake_json=intake_json)
        return self._update(existing.id, intake_json=intake_json)


class AuditEventRepository(IdRepository[AuditEvent]):
    """Insert only. No update or delete method exists, and the database rejects both."""

    model = AuditEvent

    def add(
        self,
        action: str,
        target_type: str,
        *,
        target_id: uuid.UUID | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> AuditEvent:
        return self._add(
            actor_user_id=self._ctx.user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            before_json=sanitize(before),
            after_json=sanitize(after),
        )


class CurrentPartnerRepository:
    """Read-only view of the caller's *own* partner row (e.g. its name for the app shell).

    `partners` is the tenant root and has no `partner_id` column, so this is not a
    `TenantRepository`; the scoping is `partners.id = ctx.partner_id`, fixed by the context.
    There is no way to ask for another partner.
    """

    def __init__(self, ctx: RequestContext, session: Session) -> None:
        self._ctx = ctx
        self._session = session

    def get(self) -> Partner:
        row = self._session.execute(
            select(Partner).where(Partner.id == self._ctx.partner_id)
        ).scalar_one_or_none()
        if row is None:
            raise NotFound
        return row


# --- operator repositories (non-tenant tables; platform_operator only) ---


class PartnerRepository(OperatorRepository):
    def add(self, name: str) -> Partner:
        row = Partner(name=name)
        self._session.add(row)
        self._session.flush()
        return row

    def get(self, id: uuid.UUID) -> Partner:  # noqa: A002
        row = self._session.get(Partner, id)
        if row is None:
            raise NotFound
        return row

    def list_all(self, *, limit: int = 100, offset: int = 0) -> list[Partner]:
        stmt = select(Partner).order_by(Partner.name, Partner.id).limit(limit).offset(offset)
        return list(self._session.execute(stmt).scalars())

    def set_status(self, id: uuid.UUID, status: PartnerStatus) -> Partner:  # noqa: A002
        row = self.get(id)
        row.status = status.value
        self._session.flush()
        return row


class TemplateVersionRepository(OperatorRepository):
    """`template_versions` is platform-global and immutable except its forward status move."""

    def add(self, template_id: str, version: str, schema_json: dict[str, Any]) -> TemplateVersion:
        row = TemplateVersion(template_id=template_id, version=version, schema_json=schema_json)
        self._session.add(row)
        self._session.flush()
        return row

    def get(self, id: uuid.UUID) -> TemplateVersion:  # noqa: A002
        row = self._session.get(TemplateVersion, id)
        if row is None:
            raise NotFound
        return row

    def list_all(self, *, limit: int = 100, offset: int = 0) -> list[TemplateVersion]:
        stmt = (
            select(TemplateVersion)
            .order_by(TemplateVersion.template_id, TemplateVersion.version)
            .limit(limit)
            .offset(offset)
        )
        return list(self._session.execute(stmt).scalars())

    def set_status(self, id: uuid.UUID, status: TemplateStatus) -> TemplateVersion:  # noqa: A002
        row = self.get(id)
        row.status = status.value
        self._session.flush()
        return row


class OperatorAuditRepository(OperatorRepository):
    """Insert-only audit for cross-partner operator access.

    Defaults to the operator's own partner. A route that reads one specific partner's
    data passes that partner's id so the event is attributable to the data owner.
    """

    def add(
        self,
        action: str,
        target_type: str,
        *,
        partner_id: uuid.UUID | None = None,
        target_id: uuid.UUID | None = None,
        after: dict[str, Any] | None = None,
    ) -> AuditEvent:
        row = AuditEvent(
            partner_id=partner_id or self._ctx.partner_id,
            actor_user_id=self._ctx.user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            after_json=sanitize(after),
        )
        self._session.add(row)
        self._session.flush()
        return row
