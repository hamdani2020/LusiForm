"""Schema constraints, immutability/append-only triggers, and the no-secrets rule."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.data.models import (
    ArchitectureGraph,
    Artifact,
    AssumptionSet,
    AuditEvent,
    Deployment,
    DeploymentPlan,
    Estimate,
    Partner,
    PlanApproval,
    Project,
    ProjectVersion,
    SandboxAccount,
    TemplateVersion,
    User,
    UserRole,
    ValidationRun,
)

SHA = "a" * 64
OTHER_SHA = "b" * 64


@dataclass
class Seed:
    partner_id: uuid.UUID
    user_id: uuid.UUID
    project_id: uuid.UUID
    template_id: uuid.UUID
    version_id: uuid.UUID
    assumption_id: uuid.UUID
    sandbox_id: uuid.UUID
    plan_id: uuid.UUID
    rows: dict[str, uuid.UUID]


def _partner(s: Session) -> Partner:
    p = Partner(name=f"partner-{uuid.uuid4().hex}")
    s.add(p)
    s.flush()
    return p


def _user(s: Session, partner_id: uuid.UUID, email: str | None = None) -> User:
    u = User(partner_id=partner_id, email=email or f"{uuid.uuid4().hex}@example.com")
    s.add(u)
    s.flush()
    return u


def _template(s: Session, version: str | None = None) -> TemplateVersion:
    t = TemplateVersion(
        template_id="startup",
        version=version or f"1.0.{uuid.uuid4().int % 100000}",
        schema_json={"type": "object"},
    )
    s.add(t)
    s.flush()
    return t


def seed_partner_graph(engine: Engine) -> Seed:
    """One partner with a row in every mutable/immutable/append-only table we test."""
    with Session(engine) as s:
        p = _partner(s)
        u = _user(s, p.id)
        s.add(UserRole(user_id=u.id, role="consultant", partner_id=p.id))
        t = _template(s)
        proj = Project(partner_id=p.id, name="proj", created_by=u.id)
        s.add(proj)
        s.flush()
        pv = ProjectVersion(
            partner_id=p.id,
            project_id=proj.id,
            number=1,
            template_version_id=t.id,
            intake_json={},
            parameters_json={},
            created_by=u.id,
        )
        s.add(pv)
        s.flush()
        aset = AssumptionSet(
            partner_id=p.id, project_version_id=pv.id, values_json={}, created_by=u.id
        )
        sandbox = SandboxAccount(
            partner_id=p.id,
            aws_account_id="123456789012",
            role_arn="arn:aws:iam::123456789012:role/lusiform-sandbox",
            external_id_ref="secretsmanager:lusiform/sandbox/ext-id",
        )
        s.add_all([aset, sandbox])
        s.flush()
        est = Estimate(
            partner_id=p.id,
            project_version_id=pv.id,
            assumption_set_id=aset.id,
            price_snapshot_at=datetime.now(UTC),
            monthly_total=Decimal("10.00"),
            annual_total=Decimal("120.00"),
            line_items_json={},
        )
        graph = ArchitectureGraph(
            partner_id=p.id, project_version_id=pv.id, graph_json_s3_key="g.json", sha256=SHA
        )
        art = Artifact(
            partner_id=p.id, project_version_id=pv.id, kind="zip", s3_key="a.zip", sha256=SHA
        )
        val = ValidationRun(
            partner_id=p.id,
            project_version_id=pv.id,
            tool="tflint",
            tool_version="0.1.0",
            exit_code=0,
            severity_counts_json={},
        )
        audit = AuditEvent(
            partner_id=p.id, actor_user_id=u.id, action="test", target_type="project"
        )
        plan = DeploymentPlan(
            partner_id=p.id,
            project_version_id=pv.id,
            sandbox_account_id=sandbox.id,
            action="apply",
            plan_hash=SHA,
            plan_output_s3_key="plan.txt",
            state_serial=3,
        )
        s.add_all([est, graph, art, val, audit, plan])
        s.flush()
        approval = PlanApproval(partner_id=p.id, plan_id=plan.id, plan_hash=SHA, approved_by=u.id)
        s.add(approval)
        s.flush()
        seed = Seed(
            partner_id=p.id,
            user_id=u.id,
            project_id=proj.id,
            template_id=t.id,
            version_id=pv.id,
            assumption_id=aset.id,
            sandbox_id=sandbox.id,
            plan_id=plan.id,
            rows={
                "project_versions": pv.id,
                "estimates": est.id,
                "architecture_graphs": graph.id,
                "artifacts": art.id,
                "validation_runs": val.id,
                "audit_events": audit.id,
                "plan_approvals": approval.id,
                "deployment_plans": plan.id,
                "template_versions": t.id,
            },
        )
        s.commit()
        return seed


# --- 3.3 email uniqueness ---


def test_email_unique_per_partner(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as s:
        a, b = _partner(s), _partner(s)
        _user(s, a.id, "dup@example.com")
        _user(s, b.id, "dup@example.com")  # same email, different partner: allowed
        s.commit()
        s.add(User(partner_id=a.id, email="dup@example.com"))
        with pytest.raises(IntegrityError, match="uq_users_partner_id_email"):
            s.flush()


def test_email_must_be_lowercase(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as s:
        p = _partner(s)
        s.add(User(partner_id=p.id, email="Mixed@Example.com"))
        with pytest.raises(IntegrityError, match="ck_users_email_lowercase"):
            s.flush()


# --- 3.4 roles ---


@pytest.mark.parametrize("role", ["partner_admin", "consultant", "platform_operator"])
def test_valid_roles_accepted(migrated_engine: Engine, role: str) -> None:
    with Session(migrated_engine) as s:
        p = _partner(s)
        u = _user(s, p.id)
        s.add(UserRole(user_id=u.id, role=role, partner_id=p.id))
        s.flush()


@pytest.mark.parametrize("role", ["admin", "owner", "", "Consultant"])
def test_invalid_role_rejected(migrated_engine: Engine, role: str) -> None:
    with Session(migrated_engine) as s:
        p = _partner(s)
        u = _user(s, p.id)
        s.add(UserRole(user_id=u.id, role=role, partner_id=p.id))
        with pytest.raises(IntegrityError, match="ck_user_roles_role"):
            s.flush()


# --- tenant integrity: cross-partner references are impossible ---


def test_role_partner_must_match_user_partner(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as s:
        a, b = _partner(s), _partner(s)
        u = _user(s, a.id)
        s.add(UserRole(user_id=u.id, role="consultant", partner_id=b.id))
        with pytest.raises(IntegrityError, match="fk_user_roles"):
            s.flush()


def test_version_cannot_reference_other_partners_project(migrated_engine: Engine) -> None:
    seed = seed_partner_graph(migrated_engine)
    with Session(migrated_engine) as s:
        other = _partner(s)
        s.add(
            ProjectVersion(
                partner_id=other.id,
                project_id=seed.project_id,  # belongs to the seeded partner
                number=2,
                template_version_id=seed.template_id,
                intake_json={},
                parameters_json={},
                created_by=seed.user_id,
            )
        )
        with pytest.raises(IntegrityError, match="fk_project_versions_project_id"):
            s.flush()


def test_approval_must_match_plan_hash(migrated_engine: Engine) -> None:
    seed = seed_partner_graph(migrated_engine)
    with Session(migrated_engine) as s:
        plan = DeploymentPlan(
            partner_id=seed.partner_id,
            project_version_id=seed.version_id,
            sandbox_account_id=seed.sandbox_id,
            action="destroy",
            plan_hash=OTHER_SHA,
            plan_output_s3_key="destroy.txt",
            state_serial=4,
        )
        s.add(plan)
        s.flush()
        s.add(
            PlanApproval(
                partner_id=seed.partner_id,
                plan_id=plan.id,
                plan_hash=SHA,  # not the plan's hash
                approved_by=seed.user_id,
            )
        )
        with pytest.raises(IntegrityError, match="fk_plan_approvals"):
            s.flush()


def test_one_approval_per_plan(migrated_engine: Engine) -> None:
    seed = seed_partner_graph(migrated_engine)
    with Session(migrated_engine) as s:
        s.add(
            PlanApproval(
                partner_id=seed.partner_id,
                plan_id=seed.plan_id,
                plan_hash=SHA,
                approved_by=seed.user_id,
            )
        )
        with pytest.raises(IntegrityError, match="uq_plan_approvals_plan_id"):
            s.flush()


def test_status_and_format_checks(migrated_engine: Engine) -> None:
    seed = seed_partner_graph(migrated_engine)
    with Session(migrated_engine) as s:
        s.add(Deployment(partner_id=seed.partner_id, plan_id=seed.plan_id, action="apply"))
        s.flush()
        s.add(Deployment(partner_id=seed.partner_id, plan_id=seed.plan_id, action="nuke"))
        with pytest.raises(IntegrityError, match="ck_deployments_action"):
            s.flush()
    with Session(migrated_engine) as s:
        s.add(
            SandboxAccount(
                partner_id=_partner(s).id,
                aws_account_id="123",
                role_arn="arn",
                external_id_ref="ref",
            )
        )
        with pytest.raises(IntegrityError, match="ck_sandbox_accounts_aws_account_id_format"):
            s.flush()


# --- 3.6 / 3.7 immutable and append-only triggers ---

PROTECTED = [
    "project_versions",
    "estimates",
    "architecture_graphs",
    "audit_events",
    "plan_approvals",
    "artifacts",
    "validation_runs",
]

# A harmless column to "update" on each table; the trigger must reject it anyway.
UPDATE_SQL = {
    "project_versions": "UPDATE project_versions SET number = number + 1 WHERE id = :id",
    "estimates": "UPDATE estimates SET monthly_total = 1 WHERE id = :id",
    "architecture_graphs": "UPDATE architecture_graphs SET sha256 = repeat('c', 64) WHERE id = :id",
    "audit_events": "UPDATE audit_events SET action = 'tampered' WHERE id = :id",
    "plan_approvals": "UPDATE plan_approvals SET approved_at = now() WHERE id = :id",
    "artifacts": "UPDATE artifacts SET kind = 'tampered' WHERE id = :id",
    "validation_runs": "UPDATE validation_runs SET exit_code = 9 WHERE id = :id",
}


@pytest.mark.parametrize("table", PROTECTED)
def test_protected_tables_reject_update_delete_truncate(
    migrated_engine: Engine, table: str
) -> None:
    seed = seed_partner_graph(migrated_engine)
    row_id = seed.rows[table]
    statements = [
        (UPDATE_SQL[table], {"id": row_id}),
        (f"DELETE FROM {table} WHERE id = :id", {"id": row_id}),  # noqa: S608
        (f"TRUNCATE {table} CASCADE", {}),
    ]
    for sql, params in statements:
        with (
            pytest.raises(IntegrityError, match="immutable or append-only"),
            migrated_engine.begin() as conn,
        ):
            conn.execute(text(sql), params)
    with migrated_engine.connect() as conn:  # row is still there, unchanged
        count = conn.execute(
            text(f"SELECT count(*) FROM {table} WHERE id = :id"),  # noqa: S608
            {"id": row_id},
        ).scalar_one()
    assert count == 1


def test_template_version_content_is_immutable_but_status_advances(
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as s:
        t = _template(s)
        s.commit()
        tid = t.id

    def run(sql: str) -> None:
        with migrated_engine.begin() as conn:
            conn.execute(text(sql), {"id": tid})

    with pytest.raises(IntegrityError, match="only status may change"):
        run("UPDATE template_versions SET schema_json = '{}' WHERE id = :id")
    with pytest.raises(IntegrityError, match="only status may change"):
        run("UPDATE template_versions SET version = '9.9.9' WHERE id = :id")
    with pytest.raises(IntegrityError, match="DELETE is not allowed"):
        run("DELETE FROM template_versions WHERE id = :id")
    with pytest.raises(IntegrityError, match="immutable"):
        run("TRUNCATE template_versions CASCADE")

    run("UPDATE template_versions SET status = 'published' WHERE id = :id")
    with pytest.raises(IntegrityError, match="invalid status move"):
        run("UPDATE template_versions SET status = 'draft' WHERE id = :id")
    run("UPDATE template_versions SET status = 'retired' WHERE id = :id")
    with pytest.raises(IntegrityError, match="invalid status move"):
        run("UPDATE template_versions SET status = 'published' WHERE id = :id")


def test_deployment_plan_identity_is_fixed_but_status_moves(migrated_engine: Engine) -> None:
    seed = seed_partner_graph(migrated_engine)
    pid = {"id": seed.plan_id}

    def run(sql: str) -> None:
        with migrated_engine.begin() as conn:
            conn.execute(text(sql), pid)

    for column_change in (
        "plan_hash = repeat('d', 64)",
        "state_serial = 99",
        "plan_output_s3_key = 'other'",
        "action = 'destroy'",
        "project_version_id = gen_random_uuid()",
    ):
        with pytest.raises(IntegrityError):
            run(f"UPDATE deployment_plans SET {column_change} WHERE id = :id")  # noqa: S608
    with pytest.raises(IntegrityError, match="DELETE is not allowed"):
        run("DELETE FROM deployment_plans WHERE id = :id")
    with pytest.raises(IntegrityError, match="immutable"):
        run("TRUNCATE deployment_plans CASCADE")

    run("UPDATE deployment_plans SET status = 'approved' WHERE id = :id")
    with migrated_engine.connect() as conn:
        row = conn.execute(
            text("SELECT status, plan_hash, state_serial FROM deployment_plans WHERE id = :id"),
            pid,
        ).one()
    assert tuple(row) == ("approved", SHA, 3)


# --- 3.8 no secret values; structural expectations ---

SECRET_WORDS = ("password", "secret", "token", "credential", "private_key", "api_key")


def test_no_column_holds_a_secret(migrated_engine: Engine) -> None:
    insp = inspect(migrated_engine)
    offenders = [
        f"{table}.{col['name']}"
        for table in insp.get_table_names()
        for col in insp.get_columns(table)
        if any(w in col["name"].lower() for w in SECRET_WORDS)
    ]
    assert offenders == []
    # The only external-id column is a reference, never the value.
    cols = {c["name"] for c in insp.get_columns("sandbox_accounts")}
    assert "external_id_ref" in cols
    assert "external_id" not in cols


def test_tenant_tables_have_partner_fk_and_uuid_pks(migrated_engine: Engine) -> None:
    insp = inspect(migrated_engine)
    for table in insp.get_table_names():
        if table == "alembic_version":
            continue
        cols = {c["name"]: c for c in insp.get_columns(table)}
        pk = insp.get_pk_constraint(table)["constrained_columns"]
        for name in pk:
            if name != "role":
                assert str(cols[name]["type"]) == "UUID", f"{table}.{name}"
        if table == "template_versions":  # platform-global
            assert "partner_id" not in cols
            continue
        if table == "partners":  # the tenant root itself
            continue
        assert "partner_id" in cols, table
        assert not cols["partner_id"]["nullable"], table
        referred = [
            fk["referred_table"]
            for fk in insp.get_foreign_keys(table)
            if fk["constrained_columns"] == ["partner_id"]
        ]
        assert referred == ["partners"], table
