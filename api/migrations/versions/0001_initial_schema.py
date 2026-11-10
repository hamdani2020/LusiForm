"""initial schema: 19 tables, constraints, immutability and append-only triggers

Revision ID: 0001
Revises:
Create Date: 2026-11-10 13:12:22.295848
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Immutable version/result tables and append-only history tables: any UPDATE, DELETE or
# TRUNCATE is rejected by the database, even if a stray query bypasses the data layer.
IMMUTABLE_TABLES = ("project_versions", "estimates", "architecture_graphs")
APPEND_ONLY_TABLES = ("audit_events", "plan_approvals", "artifacts", "validation_runs")


def _create_guard_functions() -> None:
    op.execute(
        """
        CREATE FUNCTION lusiform_reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is immutable or append-only: % is not allowed',
                TG_TABLE_NAME, TG_OP USING ERRCODE = 'restrict_violation';
        END;
        $$
        """
    )
    # template_versions: content is immutable; only the forward status move is allowed
    # (draft -> published -> retired), so a template can be published and retired.
    op.execute(
        """
        CREATE FUNCTION lusiform_template_versions_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'template_versions is immutable: DELETE is not allowed'
                    USING ERRCODE = 'restrict_violation';
            END IF;
            IF (NEW.id, NEW.template_id, NEW.version, NEW.schema_json, NEW.created_at)
                IS DISTINCT FROM
               (OLD.id, OLD.template_id, OLD.version, OLD.schema_json, OLD.created_at) THEN
                RAISE EXCEPTION 'template_versions is immutable: only status may change'
                    USING ERRCODE = 'restrict_violation';
            END IF;
            IF NEW.status <> OLD.status AND NOT (
                (OLD.status = 'draft' AND NEW.status IN ('published', 'retired'))
                OR (OLD.status = 'published' AND NEW.status = 'retired')
            ) THEN
                RAISE EXCEPTION 'template_versions: invalid status move % -> %',
                    OLD.status, NEW.status USING ERRCODE = 'restrict_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    # deployment_plans: identity and hash fields are fixed once created; only status moves.
    op.execute(
        """
        CREATE FUNCTION lusiform_deployment_plans_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'deployment_plans is immutable: DELETE is not allowed'
                    USING ERRCODE = 'restrict_violation';
            END IF;
            IF (NEW.id, NEW.partner_id, NEW.project_version_id, NEW.sandbox_account_id,
                NEW.action, NEW.plan_hash, NEW.plan_output_s3_key, NEW.state_serial,
                NEW.created_at)
                IS DISTINCT FROM
               (OLD.id, OLD.partner_id, OLD.project_version_id, OLD.sandbox_account_id,
                OLD.action, OLD.plan_hash, OLD.plan_output_s3_key, OLD.state_serial,
                OLD.created_at) THEN
                RAISE EXCEPTION 'deployment_plans is immutable: only status may change'
                    USING ERRCODE = 'restrict_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )


def upgrade() -> None:
    op.create_table(
        "partners",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('active', 'suspended')", name=op.f("ck_partners_status")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_partners")),
        sa.UniqueConstraint("name", name=op.f("uq_partners_name")),
    )
    op.create_table(
        "template_versions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("template_id", sa.String(length=100), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("schema_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'retired')", name=op.f("ck_template_versions_status")
        ),
        sa.CheckConstraint(
            "version ~ '^\\d+\\.\\d+\\.\\d+$'", name=op.f("ck_template_versions_semver")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_template_versions")),
        sa.UniqueConstraint(
            "template_id", "version", name=op.f("uq_template_versions_template_id_version")
        ),
    )
    op.create_table(
        "sandbox_accounts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("partner_id", sa.UUID(), nullable=False),
        sa.Column("aws_account_id", sa.String(length=12), nullable=False),
        sa.Column("role_arn", sa.String(length=2048), nullable=False),
        sa.Column("external_id_ref", sa.String(length=2048), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "aws_account_id ~ '^\\d{12}$'", name=op.f("ck_sandbox_accounts_aws_account_id_format")
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'verified', 'failed', 'disabled')",
            name=op.f("ck_sandbox_accounts_status"),
        ),
        sa.ForeignKeyConstraint(
            ["partner_id"], ["partners.id"], name=op.f("fk_sandbox_accounts_partner_id_partners")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sandbox_accounts")),
        sa.UniqueConstraint("id", "partner_id", name=op.f("uq_sandbox_accounts_id_partner_id")),
        sa.UniqueConstraint("partner_id", name=op.f("uq_sandbox_accounts_partner_id")),
    )
    op.create_index(
        op.f("ix_sandbox_accounts_partner_id"), "sandbox_accounts", ["partner_id"], unique=False
    )
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("partner_id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("cognito_sub", sa.String(length=128), nullable=True),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="invited", nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('invited', 'active', 'deactivated')", name=op.f("ck_users_status")
        ),
        sa.CheckConstraint("email = lower(email)", name=op.f("ck_users_email_lowercase")),
        sa.ForeignKeyConstraint(
            ["partner_id"], ["partners.id"], name=op.f("fk_users_partner_id_partners")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("cognito_sub", name=op.f("uq_users_cognito_sub")),
        sa.UniqueConstraint("id", "partner_id", name=op.f("uq_users_id_partner_id")),
        sa.UniqueConstraint("partner_id", "email", name=op.f("uq_users_partner_id_email")),
    )
    op.create_index(op.f("ix_users_partner_id"), "users", ["partner_id"], unique=False)
    op.create_table(
        "audit_events",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("partner_id", sa.UUID(), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("target_type", sa.String(length=100), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=True),
        sa.Column("before_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("action <> ''", name=op.f("ck_audit_events_action_not_empty")),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], name=op.f("fk_audit_events_actor_user_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["partner_id"], ["partners.id"], name=op.f("fk_audit_events_partner_id_partners")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(
        op.f("ix_audit_events_partner_id"), "audit_events", ["partner_id"], unique=False
    )
    op.create_table(
        "projects",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("partner_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_projects_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["partner_id"], ["partners.id"], name=op.f("fk_projects_partner_id_partners")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
        sa.UniqueConstraint("id", "partner_id", name=op.f("uq_projects_id_partner_id")),
    )
    op.create_index(op.f("ix_projects_partner_id"), "projects", ["partner_id"], unique=False)
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=30), nullable=False),
        sa.Column("partner_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "role IN ('partner_admin', 'consultant', 'platform_operator')",
            name=op.f("ck_user_roles_role"),
        ),
        sa.ForeignKeyConstraint(
            ["partner_id"], ["partners.id"], name=op.f("fk_user_roles_partner_id_partners")
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "partner_id"],
            ["users.id", "users.partner_id"],
            name=op.f("fk_user_roles_user_id_partner_id_users"),
        ),
        sa.PrimaryKeyConstraint("user_id", "role", name=op.f("pk_user_roles")),
    )
    op.create_index(op.f("ix_user_roles_partner_id"), "user_roles", ["partner_id"], unique=False)
    op.create_table(
        "intake_drafts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("partner_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("intake_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["partner_id"], ["partners.id"], name=op.f("fk_intake_drafts_partner_id_partners")
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "partner_id"],
            ["projects.id", "projects.partner_id"],
            name=op.f("fk_intake_drafts_project_id_partner_id_projects"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_intake_drafts")),
        sa.UniqueConstraint("project_id", name=op.f("uq_intake_drafts_project_id")),
    )
    op.create_index(
        op.f("ix_intake_drafts_partner_id"), "intake_drafts", ["partner_id"], unique=False
    )
    op.create_table(
        "project_versions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("partner_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("template_version_id", sa.UUID(), nullable=False),
        sa.Column("intake_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("parameters_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("number >= 1", name=op.f("ck_project_versions_number_positive")),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_project_versions_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["partner_id"], ["partners.id"], name=op.f("fk_project_versions_partner_id_partners")
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "partner_id"],
            ["projects.id", "projects.partner_id"],
            name=op.f("fk_project_versions_project_id_partner_id_projects"),
        ),
        sa.ForeignKeyConstraint(
            ["template_version_id"],
            ["template_versions.id"],
            name=op.f("fk_project_versions_template_version_id_template_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_versions")),
        sa.UniqueConstraint("id", "partner_id", name=op.f("uq_project_versions_id_partner_id")),
        sa.UniqueConstraint(
            "project_id", "number", name=op.f("uq_project_versions_project_id_number")
        ),
    )
    op.create_index(
        op.f("ix_project_versions_partner_id"), "project_versions", ["partner_id"], unique=False
    )
    op.create_index(
        op.f("ix_project_versions_project_id"), "project_versions", ["project_id"], unique=False
    )
    op.create_table(
        "architecture_graphs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("partner_id", sa.UUID(), nullable=False),
        sa.Column("project_version_id", sa.UUID(), nullable=False),
        sa.Column("graph_json_s3_key", sa.String(length=1024), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_architecture_graphs_sha256_format")
        ),
        sa.ForeignKeyConstraint(
            ["partner_id"], ["partners.id"], name=op.f("fk_architecture_graphs_partner_id_partners")
        ),
        sa.ForeignKeyConstraint(
            ["project_version_id", "partner_id"],
            ["project_versions.id", "project_versions.partner_id"],
            name=op.f("fk_architecture_graphs_project_version_id_partner_id_project_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_architecture_graphs")),
        sa.UniqueConstraint(
            "project_version_id", name=op.f("uq_architecture_graphs_project_version_id")
        ),
    )
    op.create_index(
        op.f("ix_architecture_graphs_partner_id"),
        "architecture_graphs",
        ["partner_id"],
        unique=False,
    )
    op.create_table(
        "artifacts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("partner_id", sa.UUID(), nullable=False),
        sa.Column("project_version_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("s3_key", sa.String(length=1024), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("kind <> ''", name=op.f("ck_artifacts_kind_not_empty")),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_artifacts_sha256_format")),
        sa.ForeignKeyConstraint(
            ["partner_id"], ["partners.id"], name=op.f("fk_artifacts_partner_id_partners")
        ),
        sa.ForeignKeyConstraint(
            ["project_version_id", "partner_id"],
            ["project_versions.id", "project_versions.partner_id"],
            name=op.f("fk_artifacts_project_version_id_partner_id_project_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artifacts")),
    )
    op.create_index(op.f("ix_artifacts_partner_id"), "artifacts", ["partner_id"], unique=False)
    op.create_index(
        op.f("ix_artifacts_project_version_id"), "artifacts", ["project_version_id"], unique=False
    )
    op.create_table(
        "assumption_sets",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("partner_id", sa.UUID(), nullable=False),
        sa.Column("project_version_id", sa.UUID(), nullable=False),
        sa.Column("values_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_assumption_sets_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["partner_id"], ["partners.id"], name=op.f("fk_assumption_sets_partner_id_partners")
        ),
        sa.ForeignKeyConstraint(
            ["project_version_id", "partner_id"],
            ["project_versions.id", "project_versions.partner_id"],
            name=op.f("fk_assumption_sets_project_version_id_partner_id_project_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assumption_sets")),
        sa.UniqueConstraint("id", "partner_id", name=op.f("uq_assumption_sets_id_partner_id")),
    )
    op.create_index(
        op.f("ix_assumption_sets_partner_id"), "assumption_sets", ["partner_id"], unique=False
    )
    op.create_index(
        op.f("ix_assumption_sets_project_version_id"),
        "assumption_sets",
        ["project_version_id"],
        unique=False,
    )
    op.create_table(
        "deployment_plans",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("partner_id", sa.UUID(), nullable=False),
        sa.Column("project_version_id", sa.UUID(), nullable=False),
        sa.Column("sandbox_account_id", sa.UUID(), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("plan_hash", sa.String(length=64), nullable=False),
        sa.Column("plan_output_s3_key", sa.String(length=1024), nullable=False),
        sa.Column("state_serial", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="ready", nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('apply', 'destroy')", name=op.f("ck_deployment_plans_action")
        ),
        sa.CheckConstraint(
            "plan_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_deployment_plans_plan_hash_format")
        ),
        sa.CheckConstraint(
            "status IN ('ready', 'approved', 'superseded')", name=op.f("ck_deployment_plans_status")
        ),
        sa.CheckConstraint(
            "state_serial >= 0", name=op.f("ck_deployment_plans_state_serial_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["partner_id"], ["partners.id"], name=op.f("fk_deployment_plans_partner_id_partners")
        ),
        sa.ForeignKeyConstraint(
            ["project_version_id", "partner_id"],
            ["project_versions.id", "project_versions.partner_id"],
            name=op.f("fk_deployment_plans_project_version_id_partner_id_project_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["sandbox_account_id", "partner_id"],
            ["sandbox_accounts.id", "sandbox_accounts.partner_id"],
            name=op.f("fk_deployment_plans_sandbox_account_id_partner_id_sandbox_accounts"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deployment_plans")),
        sa.UniqueConstraint(
            "id",
            "partner_id",
            "plan_hash",
            name=op.f("uq_deployment_plans_id_partner_id_plan_hash"),
        ),
        sa.UniqueConstraint("id", "partner_id", name=op.f("uq_deployment_plans_id_partner_id")),
    )
    op.create_index(
        op.f("ix_deployment_plans_partner_id"), "deployment_plans", ["partner_id"], unique=False
    )
    op.create_index(
        op.f("ix_deployment_plans_project_version_id"),
        "deployment_plans",
        ["project_version_id"],
        unique=False,
    )
    op.create_table(
        "diagram_artifacts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("partner_id", sa.UUID(), nullable=False),
        sa.Column("project_version_id", sa.UUID(), nullable=False),
        sa.Column("drawio_s3_key", sa.String(length=1024), nullable=True),
        sa.Column("svg_s3_key", sa.String(length=1024), nullable=True),
        sa.Column(
            "validation_status", sa.String(length=20), server_default="pending", nullable=False
        ),
        sa.Column("parity_status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "parity_status IN ('pending', 'passed', 'failed')",
            name=op.f("ck_diagram_artifacts_parity_status"),
        ),
        sa.CheckConstraint(
            "validation_status IN ('pending', 'passed', 'failed')",
            name=op.f("ck_diagram_artifacts_validation_status"),
        ),
        sa.ForeignKeyConstraint(
            ["partner_id"], ["partners.id"], name=op.f("fk_diagram_artifacts_partner_id_partners")
        ),
        sa.ForeignKeyConstraint(
            ["project_version_id", "partner_id"],
            ["project_versions.id", "project_versions.partner_id"],
            name=op.f("fk_diagram_artifacts_project_version_id_partner_id_project_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_diagram_artifacts")),
    )
    op.create_index(
        op.f("ix_diagram_artifacts_partner_id"), "diagram_artifacts", ["partner_id"], unique=False
    )
    op.create_index(
        op.f("ix_diagram_artifacts_project_version_id"),
        "diagram_artifacts",
        ["project_version_id"],
        unique=False,
    )
    op.create_table(
        "generation_jobs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("partner_id", sa.UUID(), nullable=False),
        sa.Column("project_version_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="queued", nullable=False),
        sa.Column("started_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("finished_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name=op.f("ck_generation_jobs_status"),
        ),
        sa.ForeignKeyConstraint(
            ["partner_id"], ["partners.id"], name=op.f("fk_generation_jobs_partner_id_partners")
        ),
        sa.ForeignKeyConstraint(
            ["project_version_id", "partner_id"],
            ["project_versions.id", "project_versions.partner_id"],
            name=op.f("fk_generation_jobs_project_version_id_partner_id_project_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_generation_jobs")),
    )
    op.create_index(
        op.f("ix_generation_jobs_partner_id"), "generation_jobs", ["partner_id"], unique=False
    )
    op.create_index(
        op.f("ix_generation_jobs_project_version_id"),
        "generation_jobs",
        ["project_version_id"],
        unique=False,
    )
    op.create_table(
        "validation_runs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("partner_id", sa.UUID(), nullable=False),
        sa.Column("project_version_id", sa.UUID(), nullable=False),
        sa.Column("tool", sa.String(length=50), nullable=False),
        sa.Column("tool_version", sa.String(length=50), nullable=False),
        sa.Column("exit_code", sa.BigInteger(), nullable=False),
        sa.Column("severity_counts_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["partner_id"], ["partners.id"], name=op.f("fk_validation_runs_partner_id_partners")
        ),
        sa.ForeignKeyConstraint(
            ["project_version_id", "partner_id"],
            ["project_versions.id", "project_versions.partner_id"],
            name=op.f("fk_validation_runs_project_version_id_partner_id_project_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_validation_runs")),
    )
    op.create_index(
        op.f("ix_validation_runs_partner_id"), "validation_runs", ["partner_id"], unique=False
    )
    op.create_index(
        op.f("ix_validation_runs_project_version_id"),
        "validation_runs",
        ["project_version_id"],
        unique=False,
    )
    op.create_table(
        "deployments",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("partner_id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="queued", nullable=False),
        sa.Column("started_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("finished_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("outputs_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("action IN ('apply', 'destroy')", name=op.f("ck_deployments_action")),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name=op.f("ck_deployments_status"),
        ),
        sa.ForeignKeyConstraint(
            ["partner_id"], ["partners.id"], name=op.f("fk_deployments_partner_id_partners")
        ),
        sa.ForeignKeyConstraint(
            ["plan_id", "partner_id"],
            ["deployment_plans.id", "deployment_plans.partner_id"],
            name=op.f("fk_deployments_plan_id_partner_id_deployment_plans"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deployments")),
    )
    op.create_index(op.f("ix_deployments_partner_id"), "deployments", ["partner_id"], unique=False)
    op.create_index(op.f("ix_deployments_plan_id"), "deployments", ["plan_id"], unique=False)
    op.create_table(
        "estimates",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("partner_id", sa.UUID(), nullable=False),
        sa.Column("project_version_id", sa.UUID(), nullable=False),
        sa.Column("assumption_set_id", sa.UUID(), nullable=False),
        sa.Column("price_snapshot_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("monthly_total", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("annual_total", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("line_items_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "monthly_total >= 0 AND annual_total >= 0",
            name=op.f("ck_estimates_totals_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["assumption_set_id", "partner_id"],
            ["assumption_sets.id", "assumption_sets.partner_id"],
            name=op.f("fk_estimates_assumption_set_id_partner_id_assumption_sets"),
        ),
        sa.ForeignKeyConstraint(
            ["partner_id"], ["partners.id"], name=op.f("fk_estimates_partner_id_partners")
        ),
        sa.ForeignKeyConstraint(
            ["project_version_id", "partner_id"],
            ["project_versions.id", "project_versions.partner_id"],
            name=op.f("fk_estimates_project_version_id_partner_id_project_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_estimates")),
    )
    op.create_index(op.f("ix_estimates_partner_id"), "estimates", ["partner_id"], unique=False)
    op.create_index(
        op.f("ix_estimates_project_version_id"), "estimates", ["project_version_id"], unique=False
    )
    op.create_table(
        "plan_approvals",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("partner_id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("plan_hash", sa.String(length=64), nullable=False),
        sa.Column("approved_by", sa.UUID(), nullable=False),
        sa.Column(
            "approved_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"], ["users.id"], name=op.f("fk_plan_approvals_approved_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["partner_id"], ["partners.id"], name=op.f("fk_plan_approvals_partner_id_partners")
        ),
        sa.ForeignKeyConstraint(
            ["plan_id", "partner_id", "plan_hash"],
            ["deployment_plans.id", "deployment_plans.partner_id", "deployment_plans.plan_hash"],
            name=op.f("fk_plan_approvals_plan_id_partner_id_plan_hash_deployment_plans"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan_approvals")),
        sa.UniqueConstraint("plan_id", name=op.f("uq_plan_approvals_plan_id")),
    )
    op.create_index(
        op.f("ix_plan_approvals_partner_id"), "plan_approvals", ["partner_id"], unique=False
    )

    _create_guard_functions()
    for table in IMMUTABLE_TABLES + APPEND_ONLY_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_no_mutation BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION lusiform_reject_mutation()"
        )
    for table in IMMUTABLE_TABLES + APPEND_ONLY_TABLES + ("template_versions", "deployment_plans"):
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION lusiform_reject_mutation()"
        )
    op.execute(
        "CREATE TRIGGER template_versions_guard BEFORE UPDATE OR DELETE ON template_versions "
        "FOR EACH ROW EXECUTE FUNCTION lusiform_template_versions_guard()"
    )
    op.execute(
        "CREATE TRIGGER deployment_plans_guard BEFORE UPDATE OR DELETE ON deployment_plans "
        "FOR EACH ROW EXECUTE FUNCTION lusiform_deployment_plans_guard()"
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_plan_approvals_partner_id"), table_name="plan_approvals")
    op.drop_table("plan_approvals")
    op.drop_index(op.f("ix_estimates_project_version_id"), table_name="estimates")
    op.drop_index(op.f("ix_estimates_partner_id"), table_name="estimates")
    op.drop_table("estimates")
    op.drop_index(op.f("ix_deployments_plan_id"), table_name="deployments")
    op.drop_index(op.f("ix_deployments_partner_id"), table_name="deployments")
    op.drop_table("deployments")
    op.drop_index(op.f("ix_validation_runs_project_version_id"), table_name="validation_runs")
    op.drop_index(op.f("ix_validation_runs_partner_id"), table_name="validation_runs")
    op.drop_table("validation_runs")
    op.drop_index(op.f("ix_generation_jobs_project_version_id"), table_name="generation_jobs")
    op.drop_index(op.f("ix_generation_jobs_partner_id"), table_name="generation_jobs")
    op.drop_table("generation_jobs")
    op.drop_index(op.f("ix_diagram_artifacts_project_version_id"), table_name="diagram_artifacts")
    op.drop_index(op.f("ix_diagram_artifacts_partner_id"), table_name="diagram_artifacts")
    op.drop_table("diagram_artifacts")
    op.drop_index(op.f("ix_deployment_plans_project_version_id"), table_name="deployment_plans")
    op.drop_index(op.f("ix_deployment_plans_partner_id"), table_name="deployment_plans")
    op.drop_table("deployment_plans")
    op.drop_index(op.f("ix_assumption_sets_project_version_id"), table_name="assumption_sets")
    op.drop_index(op.f("ix_assumption_sets_partner_id"), table_name="assumption_sets")
    op.drop_table("assumption_sets")
    op.drop_index(op.f("ix_artifacts_project_version_id"), table_name="artifacts")
    op.drop_index(op.f("ix_artifacts_partner_id"), table_name="artifacts")
    op.drop_table("artifacts")
    op.drop_index(op.f("ix_architecture_graphs_partner_id"), table_name="architecture_graphs")
    op.drop_table("architecture_graphs")
    op.drop_index(op.f("ix_project_versions_project_id"), table_name="project_versions")
    op.drop_index(op.f("ix_project_versions_partner_id"), table_name="project_versions")
    op.drop_table("project_versions")
    op.drop_index(op.f("ix_intake_drafts_partner_id"), table_name="intake_drafts")
    op.drop_table("intake_drafts")
    op.drop_index(op.f("ix_user_roles_partner_id"), table_name="user_roles")
    op.drop_table("user_roles")
    op.drop_index(op.f("ix_projects_partner_id"), table_name="projects")
    op.drop_table("projects")
    op.drop_index(op.f("ix_audit_events_partner_id"), table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index(op.f("ix_users_partner_id"), table_name="users")
    op.drop_table("users")
    op.drop_index(op.f("ix_sandbox_accounts_partner_id"), table_name="sandbox_accounts")
    op.drop_table("sandbox_accounts")
    op.drop_table("template_versions")
    op.drop_table("partners")

    op.execute("DROP FUNCTION lusiform_deployment_plans_guard()")
    op.execute("DROP FUNCTION lusiform_template_versions_guard()")
    op.execute("DROP FUNCTION lusiform_reject_mutation()")
