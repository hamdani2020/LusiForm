"""Repository layer: partner scoping, uniform NotFound, no mutation on append-only repos."""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.config import ApiSettings
from app.context import RequestContext
from app.data import base as repo_base
from app.data import repositories as repos
from app.data.database import Database
from app.data.models import Partner, User, UserRole
from app.enums import PartnerStatus, Role, TemplateStatus, UserStatus
from app.errors import NotAuthorized, NotFound
from app.main import create_app


@dataclass
class Tenant:
    ctx: RequestContext
    partner_id: uuid.UUID
    user_id: uuid.UUID


@dataclass
class Env:
    db: Database
    a: Tenant
    b: Tenant
    operator: RequestContext


def _tenant(s: Session, name: str, role: Role) -> Tenant:
    p = Partner(name=f"{name}-{uuid.uuid4().hex}")
    s.add(p)
    s.flush()
    u = User(partner_id=p.id, email=f"{uuid.uuid4().hex}@example.com", status="active")
    s.add(u)
    s.flush()
    s.add(UserRole(user_id=u.id, role=role.value, partner_id=p.id))
    s.flush()
    ctx = RequestContext(u.id, p.id, frozenset({role}), uuid.uuid4().hex)
    return Tenant(ctx, p.id, u.id)


@pytest.fixture
def env(migrated_engine: Engine) -> Iterator[Env]:
    with Session(migrated_engine) as s:
        a = _tenant(s, "A", Role.CONSULTANT)
        b = _tenant(s, "B", Role.PARTNER_ADMIN)
        op = _tenant(s, "OP", Role.PLATFORM_OPERATOR)
        s.commit()
    db = Database(migrated_engine)
    yield Env(db, a, b, op.ctx)


# --- scoping on reads ---


def test_list_and_get_are_scoped_to_the_callers_partner(env: Env) -> None:
    with env.db.tenant(env.a.ctx) as r:
        project = r.projects.add("alpha")
    with env.db.tenant(env.b.ctx) as r:
        assert r.projects.list_all() == []
        with pytest.raises(NotFound):
            r.projects.get(project.id)
    with env.db.tenant(env.a.ctx) as r:
        assert [p.id for p in r.projects.list_all()] == [project.id]
        assert r.projects.get(project.id).name == "alpha"


def test_cross_partner_and_missing_are_indistinguishable(env: Env) -> None:
    with env.db.tenant(env.a.ctx) as r:
        project = r.projects.add("alpha")
    errors = []
    with env.db.tenant(env.b.ctx) as r:
        for target in (project.id, uuid.uuid4()):
            with pytest.raises(NotFound) as exc:
                r.projects.get(target)
            errors.append((type(exc.value), exc.value.args, str(exc.value)))
    assert errors[0] == errors[1]
    assert str(project.id) not in errors[0][2]


# --- scoping on writes ---


def test_cross_partner_update_and_delete_touch_nothing(env: Env) -> None:
    with env.db.tenant(env.a.ctx) as r:
        project = r.projects.add("alpha")
    with env.db.tenant(env.b.ctx) as r:
        with pytest.raises(NotFound):
            r.projects.rename(project.id, "hijacked")
        with pytest.raises(NotFound):
            r.projects._delete(project.id)
    with env.db.tenant(env.a.ctx) as r:
        assert r.projects.get(project.id).name == "alpha"


def test_add_stamps_partner_from_context_and_refuses_override(env: Env) -> None:
    with env.db.tenant(env.a.ctx) as r:
        project = r.projects.add("alpha")
        assert project.partner_id == env.a.partner_id
        assert project.created_by == env.a.user_id
        with pytest.raises(TypeError, match="request context"):
            r.projects._add(partner_id=env.b.partner_id, name="x", created_by=env.a.user_id)


def test_update_cannot_change_id_or_partner(env: Env) -> None:
    with env.db.tenant(env.a.ctx) as r:
        project = r.projects.add("alpha")
        with pytest.raises(TypeError):
            r.projects._update(project.id, partner_id=env.b.partner_id)
        with pytest.raises(TypeError):
            r.projects._update(project.id, **{"id": uuid.uuid4()})


def test_failed_unit_of_work_rolls_back(env: Env) -> None:
    with pytest.raises(RuntimeError), env.db.tenant(env.a.ctx) as r:
        r.projects.add("doomed")
        raise RuntimeError
    with env.db.tenant(env.a.ctx) as r:
        assert r.projects.list_all() == []


# --- users and roles ---


def test_users_scoped_and_email_normalised(env: Env) -> None:
    with env.db.tenant(env.a.ctx) as r:
        created = r.users.add("  Dup@Example.COM ")
        assert created.email == "dup@example.com"
        assert r.users.get_by_email("DUP@example.com").id == created.id
    with env.db.tenant(env.b.ctx) as r:
        r.users.add("dup@example.com")  # same email in another partner is fine
        assert r.users.get_by_email("dup@example.com").id != created.id
        with pytest.raises(NotFound):
            r.users.get(created.id)
        with pytest.raises(NotFound):
            r.users.set_status(created.id, UserStatus.DEACTIVATED)
    with env.db.tenant(env.a.ctx) as r:
        assert r.users.get(created.id).status == "invited"


def test_roles_grant_revoke_and_isolation(env: Env) -> None:
    with env.db.tenant(env.a.ctx) as r:
        r.user_roles.grant(env.a.user_id, Role.PARTNER_ADMIN)
        assert r.user_roles.roles_for(env.a.user_id) == {Role.CONSULTANT, Role.PARTNER_ADMIN}
    with env.db.tenant(env.b.ctx) as r:
        assert r.user_roles.roles_for(env.a.user_id) == frozenset()  # invisible to B
        with pytest.raises(NotFound):
            r.user_roles.grant(env.a.user_id, Role.PLATFORM_OPERATOR)
        with pytest.raises(NotFound):
            r.user_roles.revoke(env.a.user_id, Role.CONSULTANT)
    with env.db.tenant(env.a.ctx) as r:
        r.user_roles.revoke(env.a.user_id, Role.PARTNER_ADMIN)
        assert r.user_roles.roles_for(env.a.user_id) == {Role.CONSULTANT}


# --- intake drafts ---


def test_intake_draft_save_is_upsert_and_scoped(env: Env) -> None:
    with env.db.tenant(env.a.ctx) as r:
        project = r.projects.add("alpha")
        first = r.intake_drafts.save(project.id, {"q": 1})
        second = r.intake_drafts.save(project.id, {"q": 2})
        assert first.id == second.id
        assert r.intake_drafts.get_for_project(project.id).intake_json == {"q": 2}
    with env.db.tenant(env.b.ctx) as r:
        with pytest.raises(NotFound):
            r.intake_drafts.save(project.id, {"q": "hijack"})
        with pytest.raises(NotFound):
            r.intake_drafts.get_for_project(project.id)
        assert r.intake_drafts.list_all() == []
    with env.db.tenant(env.a.ctx) as r:
        assert r.intake_drafts.get_for_project(project.id).intake_json == {"q": 2}


# --- audit events: insert only ---


def test_audit_events_insert_and_scoped_read(env: Env) -> None:
    with env.db.tenant(env.a.ctx) as r:
        event = r.audit_events.add("project.create", "project", after={"name": "alpha"})
        assert event.partner_id == env.a.partner_id
        assert event.actor_user_id == env.a.user_id
    with env.db.tenant(env.b.ctx) as r:
        assert r.audit_events.list_all() == []
        with pytest.raises(NotFound):
            r.audit_events.get(event.id)


MUTATION_NAMES = ("update", "delete", "remove", "set_", "rename", "save", "revoke")


def _public_methods(cls: type) -> list[str]:
    return [n for n in dir(cls) if not n.startswith("__")]


def test_append_only_repository_has_no_mutation_path() -> None:
    cls = repos.AuditEventRepository
    assert not issubclass(cls, repo_base.MutableRepository)
    offenders = [n for n in _public_methods(cls) if n.lstrip("_").startswith(MUTATION_NAMES)]
    assert offenders == []
    assert {"add", "get", "list_all"} <= set(_public_methods(cls))


def test_only_mutable_tables_have_mutating_repositories() -> None:
    mutable = {
        c.__name__
        for c in _all_subclasses(repo_base.TenantRepository)
        if issubclass(c, repo_base.MutableRepository) and c is not repo_base.MutableRepository
    }
    assert mutable == {"UserRepository", "ProjectRepository", "IntakeDraftRepository"}


def _all_subclasses(cls: type) -> set[type]:
    out: set[type] = set()
    for sub in cls.__subclasses__():
        out.add(sub)
        out |= _all_subclasses(sub)
    return out


def test_every_tenant_repository_query_is_filtered_by_partner(env: Env) -> None:
    with env.db.tenant(env.a.ctx) as r:
        bundle: list[repo_base.TenantRepository[Any]] = [
            r.users,
            r.user_roles,
            r.projects,
            r.intake_drafts,
            r.audit_events,
        ]
        for repo in bundle:
            sql = str(repo._scoped().compile())
            assert "partner_id = " in sql, type(repo).__name__


# --- operator (non-tenant) repositories ---


def test_operator_repositories_require_platform_operator(env: Env) -> None:
    for ctx in (env.a.ctx, env.b.ctx):
        with pytest.raises(NotAuthorized), env.db.operator(ctx):
            pass


def test_operator_sees_all_partners_and_manages_templates(env: Env) -> None:
    with env.db.operator(env.operator) as r:
        ids = {p.id for p in r.partners.list_all()}
        assert {env.a.partner_id, env.b.partner_id} <= ids
        suspended = r.partners.set_status(env.b.partner_id, PartnerStatus.SUSPENDED)
        assert suspended.status == "suspended"
        with pytest.raises(NotFound):
            r.partners.get(uuid.uuid4())

        t = r.template_versions.add("startup", "1.0.0", {"type": "object"})
        assert t.status == "draft"
        assert r.template_versions.set_status(t.id, TemplateStatus.PUBLISHED).status == "published"
        assert [x.id for x in r.template_versions.list_all()] == [t.id]
        assert not hasattr(r.template_versions, "update")


# --- 404 mapping ---


def test_not_found_maps_to_identical_404(env: Env) -> None:
    with env.db.tenant(env.a.ctx) as r:
        project = r.projects.add("alpha")

    app: FastAPI = create_app(ApiSettings())

    @app.get("/api/_probe/{pid}")
    def probe(pid: uuid.UUID) -> dict[str, str]:
        with env.db.tenant(env.b.ctx) as r:
            r.projects.get(pid)
        return {}

    client = TestClient(app)
    other = client.get(f"/api/_probe/{project.id}")
    missing = client.get(f"/api/_probe/{uuid.uuid4()}")
    assert other.status_code == missing.status_code == 404
    assert other.json() == missing.json() == {"detail": "Not found"}
