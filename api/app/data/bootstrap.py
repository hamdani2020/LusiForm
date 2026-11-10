"""Create the first platform operator (foundation task 11.2).

This is the one privileged write outside the request path: there is no operator yet, so
there is no `RequestContext` to authorise it. It is therefore deliberately narrow:

- it only ever creates a partner, one active user, the `platform_operator` role and an
  audit event, in one transaction;
- it refuses to run if any platform operator already exists, so it is safe to run twice
  and cannot be used to mint extra operators later (use the admin routes for that);
- concurrent runs are serialised with a transaction-scoped advisory lock.

Migrations stay data-free; this runs as its own one-off task.
"""

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import Engine, exists, select, text
from sqlalchemy.orm import Session

from app.data.audit_payload import sanitize
from app.data.models import AuditEvent, Partner, User, UserRole
from app.enums import Role, UserStatus

# Arbitrary constant for pg_advisory_xact_lock; unique to this operation.
_BOOTSTRAP_LOCK_KEY = 0x4C55_5349_424F_4F54  # "LUSIBOOT"

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class BootstrapError(Exception):
    """The bootstrap was refused; nothing was written."""


@dataclass(frozen=True)
class BootstrapResult:
    partner_id: uuid.UUID
    user_id: uuid.UUID


def bootstrap_platform_operator(
    engine: Engine,
    *,
    partner_name: str,
    email: str,
    cognito_sub: str,
    display_name: str | None = None,
) -> BootstrapResult:
    partner_name = partner_name.strip()
    email = email.strip().lower()
    cognito_sub = cognito_sub.strip()
    if not partner_name or len(partner_name) > 200:
        raise BootstrapError("partner name must be 1-200 characters")
    if not _EMAIL.match(email) or len(email) > 320:
        raise BootstrapError("email is not a valid address")
    if not cognito_sub or len(cognito_sub) > 128:
        raise BootstrapError("cognito sub must be 1-128 characters")

    with Session(engine) as session, session.begin():
        session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _BOOTSTRAP_LOCK_KEY})

        operator_exists = session.execute(
            select(exists().where(UserRole.role == Role.PLATFORM_OPERATOR.value))
        ).scalar_one()
        if operator_exists:
            raise BootstrapError(
                "a platform operator already exists; add more through the admin routes"
            )
        if session.execute(select(exists().where(User.cognito_sub == cognito_sub))).scalar_one():
            raise BootstrapError("that Cognito user is already linked to a Lusiform user")
        if session.execute(select(exists().where(Partner.name == partner_name))).scalar_one():
            raise BootstrapError("a partner with that name already exists")

        partner = Partner(name=partner_name)
        session.add(partner)
        session.flush()
        user = User(
            partner_id=partner.id,
            email=email,
            cognito_sub=cognito_sub,
            display_name=display_name,
            status=UserStatus.ACTIVE.value,
        )
        session.add(user)
        session.flush()
        session.add(
            UserRole(user_id=user.id, role=Role.PLATFORM_OPERATOR.value, partner_id=partner.id)
        )
        session.add(
            AuditEvent(
                partner_id=partner.id,
                actor_user_id=None,  # system action: there is no operator yet
                action="bootstrap.platform_operator.create",
                target_type="user",
                target_id=user.id,
                after_json=sanitize(
                    {"partner_name": partner_name, "email": email, "role": "platform_operator"}
                ),
            )
        )
        session.flush()
        return BootstrapResult(partner_id=partner.id, user_id=user.id)
