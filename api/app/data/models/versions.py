"""Template and project versions, assumptions, estimates, jobs, artifacts, validation."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.data.models.base import (
    SHA256_RE,
    Base,
    JobStatus,
    TemplateStatus,
    created_at_col,
    in_check,
    partner_fk,
    tenant_fk,
    updated_at_col,
    uuid_pk,
)


class TemplateVersion(Base):
    """Platform-global (no partner_id). Immutable except the forward status move."""

    __tablename__ = "template_versions"
    __table_args__ = (
        UniqueConstraint("template_id", "version"),
        CheckConstraint(r"version ~ '^\d+\.\d+\.\d+$'", name="semver"),
        in_check("status", TemplateStatus, "status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    template_id: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)  # semver, e.g. 1.0.4
    schema_json: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TemplateStatus.DRAFT.value, server_default="draft"
    )
    created_at: Mapped[datetime] = created_at_col()


class ProjectVersion(Base):
    """Immutable. Rendered as v{number}."""

    __tablename__ = "project_versions"
    __table_args__ = (
        tenant_fk("projects", "project_id"),
        UniqueConstraint("project_id", "number"),
        UniqueConstraint("id", "partner_id"),
        CheckConstraint("number >= 1", name="number_positive"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    partner_id: Mapped[uuid.UUID] = partner_fk()
    project_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    template_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("template_versions.id"), nullable=False
    )
    intake_json: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    parameters_json: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = created_at_col()


class AssumptionSet(Base):
    """Editable copies per version."""

    __tablename__ = "assumption_sets"
    __table_args__ = (
        tenant_fk("project_versions", "project_version_id"),
        UniqueConstraint("id", "partner_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    partner_id: Mapped[uuid.UUID] = partner_fk()
    project_version_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    values_json: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class Estimate(Base):
    """Immutable result. Changing an assumption creates a new row."""

    __tablename__ = "estimates"
    __table_args__ = (
        tenant_fk("project_versions", "project_version_id"),
        tenant_fk("assumption_sets", "assumption_set_id"),
        CheckConstraint("monthly_total >= 0 AND annual_total >= 0", name="totals_non_negative"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    partner_id: Mapped[uuid.UUID] = partner_fk()
    project_version_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    assumption_set_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    price_snapshot_at: Mapped[datetime] = mapped_column(nullable=False)
    monthly_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    annual_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    line_items_json: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = created_at_col()


class GenerationJob(Base):
    __tablename__ = "generation_jobs"
    __table_args__ = (
        tenant_fk("project_versions", "project_version_id"),
        in_check("status", JobStatus, "status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    partner_id: Mapped[uuid.UUID] = partner_fk()
    project_version_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=JobStatus.QUEUED.value, server_default="queued"
    )
    started_at: Mapped[datetime | None] = mapped_column()
    finished_at: Mapped[datetime | None] = mapped_column()
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()


class Artifact(Base):
    """Append-only: zip, manifest, validation report."""

    __tablename__ = "artifacts"
    __table_args__ = (
        tenant_fk("project_versions", "project_version_id"),
        CheckConstraint("kind <> ''", name="kind_not_empty"),
        CheckConstraint(f"sha256 ~ '{SHA256_RE}'", name="sha256_format"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    partner_id: Mapped[uuid.UUID] = partner_fk()
    project_version_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    s3_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = created_at_col()


class ValidationRun(Base):
    """Append-only: one row per tool per version."""

    __tablename__ = "validation_runs"
    __table_args__ = (tenant_fk("project_versions", "project_version_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    partner_id: Mapped[uuid.UUID] = partner_fk()
    project_version_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    tool: Mapped[str] = mapped_column(String(50), nullable=False)
    tool_version: Mapped[str] = mapped_column(String(50), nullable=False)
    exit_code: Mapped[int] = mapped_column(BigInteger, nullable=False)
    severity_counts_json: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()
