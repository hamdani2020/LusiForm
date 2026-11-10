"""Graphs, diagrams, sandbox accounts, plans, approvals, deployments, audit."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.data.models.base import (
    SHA256_RE,
    Base,
    created_at_col,
    in_check,
    partner_fk,
    tenant_fk,
    updated_at_col,
    uuid_pk,
)
from app.enums import CheckStatus, DeploymentAction, JobStatus, PlanStatus, SandboxStatus


class ArchitectureGraph(Base):
    """Immutable. Single source for Terraform and the diagram."""

    __tablename__ = "architecture_graphs"
    __table_args__ = (
        tenant_fk("project_versions", "project_version_id"),
        UniqueConstraint("project_version_id"),
        CheckConstraint(f"sha256 ~ '{SHA256_RE}'", name="sha256_format"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    partner_id: Mapped[uuid.UUID] = partner_fk()
    project_version_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    graph_json_s3_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = created_at_col()


class DiagramArtifact(Base):
    """One per rendered diagram. Status fields are mutable."""

    __tablename__ = "diagram_artifacts"
    __table_args__ = (
        tenant_fk("project_versions", "project_version_id"),
        in_check("validation_status", CheckStatus, "validation_status"),
        in_check("parity_status", CheckStatus, "parity_status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    partner_id: Mapped[uuid.UUID] = partner_fk()
    project_version_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    drawio_s3_key: Mapped[str | None] = mapped_column(String(1024))
    svg_s3_key: Mapped[str | None] = mapped_column(String(1024))
    validation_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=CheckStatus.PENDING.value, server_default="pending"
    )
    parity_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=CheckStatus.PENDING.value, server_default="pending"
    )
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class SandboxAccount(Base):
    """One per partner. `external_id_ref` is a Secrets Manager reference, never the value."""

    __tablename__ = "sandbox_accounts"
    __table_args__ = (
        UniqueConstraint("partner_id"),
        UniqueConstraint("id", "partner_id"),
        CheckConstraint(r"aws_account_id ~ '^\d{12}$'", name="aws_account_id_format"),
        in_check("status", SandboxStatus, "status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    partner_id: Mapped[uuid.UUID] = partner_fk()
    aws_account_id: Mapped[str] = mapped_column(String(12), nullable=False)
    role_arn: Mapped[str] = mapped_column(String(2048), nullable=False)
    external_id_ref: Mapped[str] = mapped_column(String(2048), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=SandboxStatus.PENDING.value, server_default="pending"
    )
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class DeploymentPlan(Base):
    """Identity and hash fields are immutable once created; only `status` may change."""

    __tablename__ = "deployment_plans"
    __table_args__ = (
        tenant_fk("project_versions", "project_version_id"),
        tenant_fk("sandbox_accounts", "sandbox_account_id"),
        # Targets of the approval/deployment FKs. The three-column one binds an
        # approval to this exact plan hash.
        UniqueConstraint("id", "partner_id", "plan_hash"),
        UniqueConstraint("id", "partner_id"),
        CheckConstraint(f"plan_hash ~ '{SHA256_RE}'", name="plan_hash_format"),
        CheckConstraint("state_serial >= 0", name="state_serial_non_negative"),
        in_check("action", DeploymentAction, "action"),
        in_check("status", PlanStatus, "status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    partner_id: Mapped[uuid.UUID] = partner_fk()
    project_version_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    sandbox_account_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    # A teardown needs its own plan, so the plan records which action it is for.
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_output_s3_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    state_serial: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PlanStatus.READY.value, server_default="ready"
    )
    created_at: Mapped[datetime] = created_at_col()


class PlanApproval(Base):
    """Append-only; one approval per plan, bound to the plan's hash."""

    __tablename__ = "plan_approvals"
    __table_args__ = (
        tenant_fk("deployment_plans", "plan_id", ("plan_hash", "plan_hash")),
        UniqueConstraint("plan_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    partner_id: Mapped[uuid.UUID] = partner_fk()
    plan_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    approved_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    approved_at: Mapped[datetime] = created_at_col()


class Deployment(Base):
    __tablename__ = "deployments"
    __table_args__ = (
        tenant_fk("deployment_plans", "plan_id"),
        in_check("action", DeploymentAction, "action"),
        in_check("status", JobStatus, "status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    partner_id: Mapped[uuid.UUID] = partner_fk()
    plan_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=JobStatus.QUEUED.value, server_default="queued"
    )
    started_at: Mapped[datetime | None] = mapped_column()
    finished_at: Mapped[datetime | None] = mapped_column()
    outputs_json: Mapped[dict[str, Any] | None] = mapped_column()  # non-secret outputs only
    created_at: Mapped[datetime] = created_at_col()


class AuditEvent(Base):
    """Append-only."""

    __tablename__ = "audit_events"
    __table_args__ = (CheckConstraint("action <> ''", name="action_not_empty"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    partner_id: Mapped[uuid.UUID] = partner_fk()
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str] = mapped_column(String(100), nullable=False)
    target_id: Mapped[uuid.UUID | None] = mapped_column()
    before_json: Mapped[dict[str, Any] | None] = mapped_column()
    after_json: Mapped[dict[str, Any] | None] = mapped_column()
    created_at: Mapped[datetime] = created_at_col()
