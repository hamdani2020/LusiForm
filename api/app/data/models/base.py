"""Declarative base, shared column helpers, and the value sets used by CHECK constraints."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, MetaData, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint names so migrations are stable and triggers/tests can refer to them.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

SHA256_RE = "^[0-9a-f]{64}$"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {
        datetime: TIMESTAMP(timezone=True),
        uuid.UUID: PG_UUID(as_uuid=True),
        dict[str, Any]: JSONB,
    }


def in_check(column: str, values: type[StrEnum], name: str) -> CheckConstraint:
    """CHECK (column IN (...)) built from a StrEnum's values (never user input)."""
    allowed = ", ".join(f"'{m.value}'" for m in values)
    return CheckConstraint(f"{column} IN ({allowed})", name=name)


def tenant_fk(table: str, column: str, *extra: tuple[str, str]) -> ForeignKeyConstraint:
    """Composite FK (column, partner_id) -> table(id, partner_id).

    Makes a cross-partner reference impossible at the database level. `extra` adds
    further (local, remote) column pairs, e.g. ("plan_hash", "plan_hash").
    """
    local = [column, "partner_id", *(e[0] for e in extra)]
    remote = [f"{table}.id", f"{table}.partner_id", *(f"{table}.{e[1]}" for e in extra)]
    return ForeignKeyConstraint(local, remote)


# --- column helpers ---


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )


def partner_fk() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("partners.id"), nullable=False, index=True)


def created_at_col() -> Mapped[datetime]:
    return mapped_column(nullable=False, server_default=text("now()"))


def updated_at_col() -> Mapped[datetime]:
    return mapped_column(nullable=False, server_default=text("now()"), onupdate=text("now()"))
