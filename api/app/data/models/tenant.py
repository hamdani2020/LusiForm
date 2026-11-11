"""Partners, users, roles, projects, intake drafts."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.data.models.base import (
    Base,
    created_at_col,
    in_check,
    partner_fk,
    tenant_fk,
    updated_at_col,
    uuid_pk,
)
from app.enums import PartnerStatus, Role, UserStatus


class Partner(Base):
    """Tenant root."""

    __tablename__ = "partners"
    __table_args__ = (in_check("status", PartnerStatus, "status"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PartnerStatus.ACTIVE.value, server_default="active"
    )
    created_at: Mapped[datetime] = created_at_col()


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("partner_id", "email"),
        # Target of composite FKs from tenant children (see tenant_fk).
        UniqueConstraint("id", "partner_id"),
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        in_check("status", UserStatus, "status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    partner_id: Mapped[uuid.UUID] = partner_fk()
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    # Cognito subject; identity link used by request-context resolution (task 5).
    cognito_sub: Mapped[str | None] = mapped_column(String(128), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=UserStatus.INVITED.value, server_default="invited"
    )
    created_at: Mapped[datetime] = created_at_col()


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (
        tenant_fk("users", "user_id"),
        in_check("role", Role, "role"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    role: Mapped[str] = mapped_column(String(30), primary_key=True)
    partner_id: Mapped[uuid.UUID] = partner_fk()


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("id", "partner_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    partner_id: Mapped[uuid.UUID] = partner_fk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class IntakeDraft(Base):
    """Mutable draft before a version is cut. One per project."""

    __tablename__ = "intake_drafts"
    __table_args__ = (tenant_fk("projects", "project_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    partner_id: Mapped[uuid.UUID] = partner_fk()
    project_id: Mapped[uuid.UUID] = mapped_column(nullable=False, unique=True)
    intake_json: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = updated_at_col()


__all__ = ["IntakeDraft", "Partner", "Project", "User", "UserRole"]
