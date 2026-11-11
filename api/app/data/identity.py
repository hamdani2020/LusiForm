"""Identity lookup by Cognito subject.

This is the one query that cannot go through the partner-scoped repositories: it
runs *before* a `RequestContext` exists, and its job is to discover which partner
the verified caller belongs to. It reads by `cognito_sub` only, never by anything
the client sends other than the verified token subject, and it is the sole
sanctioned unscoped read of tenant tables outside the operator repositories.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data.models import Partner, User, UserRole
from app.enums import PartnerStatus, Role, UserStatus


@dataclass(frozen=True)
class Identity:
    user_id: uuid.UUID
    partner_id: uuid.UUID
    roles: frozenset[Role]
    user_status: UserStatus
    partner_status: PartnerStatus

    @property
    def is_active(self) -> bool:
        return self.user_status is UserStatus.ACTIVE and self.partner_status is PartnerStatus.ACTIVE


def resolve_identity(session: Session, cognito_sub: str) -> Identity | None:
    row = session.execute(
        select(User.id, User.partner_id, User.status, Partner.status)
        .join(Partner, Partner.id == User.partner_id)
        .where(User.cognito_sub == cognito_sub)
    ).one_or_none()
    if row is None:
        return None
    user_id, partner_id, user_status, partner_status = row
    roles = session.execute(
        select(UserRole.role).where(UserRole.user_id == user_id, UserRole.partner_id == partner_id)
    ).scalars()
    return Identity(
        user_id=user_id,
        partner_id=partner_id,
        roles=frozenset(Role(r) for r in roles),
        user_status=UserStatus(user_status),
        partner_status=PartnerStatus(partner_status),
    )
