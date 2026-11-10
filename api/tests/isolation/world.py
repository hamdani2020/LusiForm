"""Two-partner fixtures and helpers for the isolation suite (task 7.1)."""

import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.config import ApiSettings
from app.context import RequestContext
from app.data.database import Database
from app.data.models import Base, User, UserRole
from app.deps import get_database, get_verifier
from app.enums import Role
from app.jwt_verifier import JwtVerifier
from app.main import create_app
from tests.isolation.endpoints import Endpoint
from tests.test_auth import CLIENT_ID, ISSUER, StaticKeys, make_token
from tests.test_schema_constraints import seed_partner_graph


@dataclass
class Account:
    sub: str
    ctx: RequestContext
    email: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {make_token(self.sub)}"}


@dataclass
class Party:
    """One partner: a user in every role plus rows across the tenant tables."""

    name: str
    partner_id: uuid.UUID
    accounts: dict[Role, Account]
    ids: dict[str, str] = field(default_factory=dict)  # seeded resource ids, as strings

    def __getitem__(self, role: Role) -> Account:
        return self.accounts[role]


@dataclass
class World:
    engine: Engine
    db: Database
    a: Party
    b: Party
    app: FastAPI

    def client(self, app: FastAPI | None = None) -> TestClient:
        return TestClient(app or self.app, raise_server_exceptions=False)


def make_app(db: Database) -> FastAPI:
    app = create_app(ApiSettings())
    app.dependency_overrides[get_verifier] = lambda: JwtVerifier(
        issuer=ISSUER, client_id=CLIENT_ID, keys=StaticKeys()
    )
    app.dependency_overrides[get_database] = lambda: db
    return app


def _build_party(engine: Engine, db: Database, name: str) -> Party:
    # Rows across every tenant table (versions, estimates, plans, approvals, ...).
    seed = seed_partner_graph(engine)
    accounts: dict[Role, Account] = {}
    with Session(engine) as s:
        for role in Role:
            sub = f"{name}-{role.value}-{uuid.uuid4().hex}"
            email = f"{name.lower()}.{role.value}.{uuid.uuid4().hex[:8]}@example.com"
            user = User(
                partner_id=seed.partner_id,
                email=email,
                cognito_sub=sub,
                status="active",
                display_name=f"{name} {role.value}",
            )
            s.add(user)
            s.flush()
            s.add(UserRole(user_id=user.id, role=role.value, partner_id=seed.partner_id))
            ctx = RequestContext(user.id, seed.partner_id, frozenset({role}), uuid.uuid4().hex)
            accounts[role] = Account(sub, ctx, email)
        s.commit()

    consultant = accounts[Role.CONSULTANT]
    with db.tenant(consultant.ctx) as repos:
        project = repos.projects.add(f"{name}-project")
        repos.intake_drafts.save(project.id, {"answers": f"{name} secret plans"})
        event = repos.audit_events.add(f"{name}.seed", "project", target_id=project.id)

    ids = {
        "partner_id": str(seed.partner_id),
        "user_id": str(consultant.ctx.user_id),
        "project_id": str(project.id),
        "seed_project_id": str(seed.project_id),
        "version_id": str(seed.version_id),
        "plan_id": str(seed.plan_id),
        "sandbox_id": str(seed.sandbox_id),
        "audit_id": str(event.id),
    }
    return Party(name, seed.partner_id, accounts, ids)


def build_world(engine: Engine) -> World:
    db = Database(engine)
    a = _build_party(engine, db, "A")
    b = _build_party(engine, db, "B")
    return World(engine, db, a, b, make_app(db))


def snapshot(engine: Engine, partner_id: uuid.UUID) -> dict[str, list[str]]:
    """Every row of every tenant table for one partner, as text, for before/after diffs."""
    out: dict[str, list[str]] = {}
    with engine.connect() as conn:
        for table in Base.metadata.sorted_tables:
            if "partner_id" not in table.c:
                continue
            rows = conn.execute(
                text(f'SELECT t::text FROM "{table.name}" t WHERE t.partner_id = :p ORDER BY 1'),  # noqa: S608
                {"p": partner_id},
            ).scalars()
            out[table.name] = list(rows)
    return out


def snapshot_all_tenants(engine: Engine, *parties: Party) -> dict[str, dict[str, list[str]]]:
    return {p.name: snapshot(engine, p.partner_id) for p in parties}


def assert_cross_partner_refused(
    client: TestClient, endpoint: Endpoint, a_ids: dict[str, str], b_headers: dict[str, str]
) -> None:
    """B asks for A's resource. The answer must be a 404 identical to asking for a missing id."""
    real = endpoint.path.format(**{param: a_ids[key] for param, key in endpoint.ids.items()})
    missing = endpoint.path.format(**{param: str(uuid.uuid4()) for param in endpoint.ids})
    cross = client.request(endpoint.method, real, headers=b_headers, json=endpoint.body)
    gone = client.request(endpoint.method, missing, headers=b_headers, json=endpoint.body)
    assert cross.status_code == 404, f"{endpoint}: cross-partner got {cross.status_code}"
    assert gone.status_code == 404, f"{endpoint}: missing id got {gone.status_code}"
    assert cross.json() == gone.json(), f"{endpoint}: 404 bodies differ, existence is disclosed"


def contains_any(payload: Any, needles: set[str]) -> bool:
    """True if any needle string appears anywhere in a JSON-like payload."""
    return any(n in str(payload) for n in needles)
