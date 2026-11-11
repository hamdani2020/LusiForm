"""Audit helper and operator cross-partner access recording."""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import record
from app.config import ApiSettings
from app.context import RequestContext
from app.data.database import Database
from app.data.models import AuditEvent, Partner, Project, User, UserRole
from app.data.repositories import OperatorAuditRepository
from app.deps import get_database, get_verifier
from app.enums import Role
from app.jwt_verifier import JwtVerifier
from app.main import create_app
from tests.test_auth import CLIENT_ID, ISSUER, StaticKeys, make_token


@dataclass
class Account:
    sub: str
    ctx: RequestContext


def _account(s: Session, role: Role) -> Account:
    p = Partner(name=f"p-{uuid.uuid4().hex}")
    s.add(p)
    s.flush()
    sub = f"sub-{uuid.uuid4().hex}"
    u = User(
        partner_id=p.id, email=f"{uuid.uuid4().hex}@example.com", cognito_sub=sub, status="active"
    )
    s.add(u)
    s.flush()
    s.add(UserRole(user_id=u.id, role=role.value, partner_id=p.id))
    s.flush()
    return Account(sub, RequestContext(u.id, p.id, frozenset({role}), uuid.uuid4().hex))


@pytest.fixture
def env(migrated_engine: Engine) -> Iterator[tuple[Engine, Database, Account, Account, Account]]:
    with Session(migrated_engine) as s:
        consultant = _account(s, Role.CONSULTANT)
        admin = _account(s, Role.PARTNER_ADMIN)
        operator = _account(s, Role.PLATFORM_OPERATOR)
        s.commit()
    yield migrated_engine, Database(migrated_engine), consultant, admin, operator


def _count(engine: Engine, model: Any, **where: Any) -> int:
    with Session(engine) as s:
        stmt = select(func.count()).select_from(model)
        for k, v in where.items():
            stmt = stmt.where(getattr(model, k) == v)
        return s.execute(stmt).scalar_one()


# --- 6.1 helper: same transaction as the write ---


def test_record_commits_with_the_write_and_captures_actor_and_partner(env: Any) -> None:
    engine, db, _, admin, _ = env
    with db.tenant(admin.ctx) as repos:
        project = repos.projects.add("alpha")
        event = record(
            repos,
            "project.create",
            "project",
            target_id=project.id,
            before=None,
            after={"name": "alpha"},
        )
    with Session(engine) as s:
        row = s.get(AuditEvent, event.id)
        assert row is not None
        assert row.actor_user_id == admin.ctx.user_id
        assert row.partner_id == admin.ctx.partner_id
        assert (row.action, row.target_type, row.target_id) == (
            "project.create",
            "project",
            project.id,
        )
        assert row.before_json is None
        assert row.after_json == {"name": "alpha"}
    assert _count(engine, Project, id=project.id) == 1


def test_write_and_audit_roll_back_together_on_error(env: Any) -> None:
    engine, db, _, admin, _ = env
    with pytest.raises(RuntimeError), db.tenant(admin.ctx) as repos:
        project = repos.projects.add("doomed")
        record(repos, "project.create", "project", target_id=project.id)
        raise RuntimeError
    assert _count(engine, Project, partner_id=admin.ctx.partner_id) == 0
    assert _count(engine, AuditEvent, partner_id=admin.ctx.partner_id) == 0


def test_failed_audit_insert_rolls_back_the_write(env: Any) -> None:
    engine, db, _, admin, _ = env
    with pytest.raises(IntegrityError), db.tenant(admin.ctx) as repos:
        repos.projects.add("needs-audit")
        record(repos, "", "project")  # empty action violates the CHECK constraint
    assert _count(engine, Project, partner_id=admin.ctx.partner_id) == 0


def test_role_grant_and_audit_are_atomic(env: Any) -> None:
    engine, db, consultant, admin, _ = env
    with db.tenant(admin.ctx) as repos:
        # an admin write: grant a role inside the same unit of work as its audit row
        repos.user_roles.grant(admin.ctx.user_id, Role.CONSULTANT)
        record(
            repos,
            "user.role.grant",
            "user",
            target_id=admin.ctx.user_id,
            after={"role": "consultant"},
        )
    assert _count(engine, UserRole, user_id=admin.ctx.user_id) == 2
    assert _count(engine, AuditEvent, action="user.role.grant") == 1


def test_snapshots_are_sanitised_and_json_safe(env: Any) -> None:
    engine, db, _, admin, _ = env
    with db.tenant(admin.ctx) as repos:
        event = record(
            repos,
            "assumptions.update",
            "assumption_set",
            before={"notes": "customer free text", "api_token": "abc", "n": 1},
            after={
                "when": datetime(2026, 1, 1, tzinfo=UTC),
                "id": uuid.UUID(int=7),
                "nested": {"password": "hunter2", "ok": True},
            },
        )
    with Session(engine) as s:
        row = s.get(AuditEvent, event.id)
        assert row is not None
        assert row.before_json == {"notes": "[REDACTED]", "api_token": "[REDACTED]", "n": 1}
        assert row.after_json == {
            "when": "2026-01-01T00:00:00Z",
            "id": str(uuid.UUID(int=7)),
            "nested": {"password": "[REDACTED]", "ok": True},
        }


# --- 6.3 audit rows cannot be changed ---


def test_audit_rows_cannot_be_updated_or_deleted(env: Any) -> None:
    engine, db, _, admin, _ = env
    with db.tenant(admin.ctx) as repos:
        event = record(repos, "project.create", "project")
    for sql in (
        "UPDATE audit_events SET action = 'tampered' WHERE id = :id",
        "DELETE FROM audit_events WHERE id = :id",
    ):
        with pytest.raises(IntegrityError, match="append-only"), engine.begin() as conn:
            conn.execute(text(sql), {"id": event.id})
    assert _count(engine, AuditEvent, id=event.id, action="project.create") == 1


# --- 6.2 operator cross-partner route ---


@pytest.fixture
def client(env: Any) -> TestClient:
    engine, db, *_ = env
    app: FastAPI = create_app(ApiSettings())
    app.dependency_overrides[get_verifier] = lambda: JwtVerifier(
        issuer=ISSUER, client_id=CLIENT_ID, keys=StaticKeys()
    )
    app.dependency_overrides[get_database] = lambda: db
    return TestClient(app, raise_server_exceptions=False)


def _auth(acct: Account) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(acct.sub)}"}


def test_operator_lists_all_partners_and_the_access_is_audited(
    env: Any, client: TestClient
) -> None:
    engine, _, consultant, admin, operator = env
    r = client.get("/api/admin/partners", headers=_auth(operator), params={"limit": 100})
    assert r.status_code == 200
    ids = {p["id"] for p in r.json()}
    assert {str(consultant.ctx.partner_id), str(admin.ctx.partner_id)} <= ids

    with Session(engine) as s:
        events = (
            s.execute(select(AuditEvent).where(AuditEvent.action == "operator.partners.list"))
            .scalars()
            .all()
        )
    assert len(events) == 1
    ev = events[0]
    assert ev.actor_user_id == operator.ctx.user_id
    assert ev.partner_id == operator.ctx.partner_id
    assert ev.target_type == "partner"
    assert ev.after_json is not None
    assert ev.after_json["returned"] == len(r.json())


def test_every_operator_access_adds_its_own_audit_row(env: Any, client: TestClient) -> None:
    engine, _, _, _, operator = env
    for _ in range(3):
        assert client.get("/api/admin/partners", headers=_auth(operator)).status_code == 200
    assert _count(engine, AuditEvent, action="operator.partners.list") == 3


def test_non_operators_and_anonymous_are_refused_and_nothing_is_audited(
    env: Any, client: TestClient
) -> None:
    engine, _, consultant, admin, _ = env
    assert client.get("/api/admin/partners", headers=_auth(consultant)).status_code == 403
    assert client.get("/api/admin/partners", headers=_auth(admin)).status_code == 403
    assert client.get("/api/admin/partners").status_code == 401
    assert _count(engine, AuditEvent, action="operator.partners.list") == 0


def test_unaudited_access_is_impossible(
    env: Any, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, _, _, _, operator = env

    def boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("audit store unavailable")

    monkeypatch.setattr(OperatorAuditRepository, "add", boom)
    r = client.get("/api/admin/partners", headers=_auth(operator))
    assert r.status_code == 500  # no partner data returned without an audit row
    assert "name" not in r.text
    assert _count(engine, AuditEvent, action="operator.partners.list") == 0
