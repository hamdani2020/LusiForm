"""Tenant isolation suite (Requirements 4.3, 4.6; NFR 3).

Two partners, A and B, each with a user in every role and rows across the tenant
tables. B must never read or change A's data, through the API or the repositories,
and the suite fails if a route or tenant table is added without being covered.
"""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi import Depends, FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.context import RequestContext
from app.data.base import TenantRepository
from app.data.database import TenantRepositories
from app.data.models import AuditEvent, Base, Project
from app.deps import get_request_context
from app.enums import Role, UserStatus
from app.errors import NotFound
from tests.isolation.endpoints import ENDPOINTS, Endpoint, Kind, registered_routes
from tests.isolation.world import (
    World,
    assert_cross_partner_refused,
    contains_any,
    make_app,
    snapshot_all_tenants,
)

# --- coverage: nothing can silently fall outside the suite ---


def test_every_registered_route_is_in_the_endpoint_table(world: World) -> None:
    table = {e.key for e in ENDPOINTS}
    registered = registered_routes(world.app)
    missing = sorted(registered - table)
    stale = sorted(table - registered)
    assert not missing, (
        f"routes registered but not in tests/isolation/endpoints.py: {missing}. "
        "Classify each (public/self/operator/tenant) so isolation is proven for it."
    )
    assert not stale, f"endpoint table lists routes that no longer exist: {stale}"
    assert len(table) == len(ENDPOINTS), "duplicate entries in the endpoint table"


def test_tenant_endpoints_declare_how_to_reach_a_resource() -> None:
    for e in ENDPOINTS:
        params = {p.strip("{}") for p in e.path.split("/") if p.startswith("{")}
        if e.kind is Kind.TENANT:
            assert params, f"{e}: tenant endpoints act on a resource id"
            assert params == set(e.ids), f"{e}: ids must map every path parameter"
        else:
            assert not params, f"{e}: id-taking routes must be classified tenant"


# Tables that carry partner_id, and how each is proven isolated. A new table must be
# added to one of the two sets, forcing a decision.
REPOSITORY_COVERED = {"users", "user_roles", "projects", "intake_drafts", "audit_events"}
NO_REPOSITORY_YET = {
    "project_versions",
    "assumption_sets",
    "estimates",
    "generation_jobs",
    "artifacts",
    "validation_runs",
    "sandbox_accounts",
    "architecture_graphs",
    "diagram_artifacts",
    "deployment_plans",
    "plan_approvals",
    "deployments",
}


def _all_subclasses(cls: type) -> set[type]:
    out: set[type] = set()
    for sub in cls.__subclasses__():
        out.add(sub)
        out |= _all_subclasses(sub)
    return out


def test_every_tenant_table_is_classified() -> None:
    tenant_tables = {t.name for t in Base.metadata.tables.values() if "partner_id" in t.c}
    assert tenant_tables == REPOSITORY_COVERED | NO_REPOSITORY_YET
    assert not REPOSITORY_COVERED & NO_REPOSITORY_YET


def test_every_tenant_repository_is_covered_by_this_suite() -> None:
    with_repo = {
        c.model.__tablename__  # type: ignore[attr-defined]
        for c in _all_subclasses(TenantRepository)
        if c.__dict__.get("model") is not None
    }
    assert with_repo == REPOSITORY_COVERED, (
        "a repository was added or removed: update REPOSITORY_COVERED and add cases below"
    )


# --- API level: one test per endpoint kind ---


def test_public_endpoints_need_no_auth_and_leak_nothing(world: World) -> None:
    client = world.client()
    for e in (e for e in ENDPOINTS if e.kind is Kind.PUBLIC):
        r = client.request(e.method, e.path)
        assert r.status_code == 200, e
        assert not contains_any(r.json(), set(world.a.ids.values()) | set(world.b.ids.values()))


@pytest.mark.parametrize("role", list(Role))
def test_self_endpoints_return_only_the_callers_own_identity(world: World, role: Role) -> None:
    client = world.client()
    a_values = set(world.a.ids.values()) | {a.email for a in world.a.accounts.values()}
    b_acct = world.b[role]
    for e in (e for e in ENDPOINTS if e.kind is Kind.SELF):
        # Client-controlled hints that must not redirect the lookup to partner A.
        hints = {"X-Partner-Id": world.a.ids["partner_id"], "X-User-Id": world.a.ids["user_id"]}
        r = client.request(
            e.method,
            e.path,
            headers={**b_acct.headers, **hints},
            params={"partner_id": world.a.ids["partner_id"]},
        )
        assert r.status_code == 200, e
        body = r.json()
        assert body["partner_id"] == str(world.b.partner_id)
        assert body["user_id"] == str(b_acct.ctx.user_id)
        assert not contains_any(body, a_values), f"{e} leaked partner A data"


@pytest.mark.parametrize("party", ["a", "b"])
def test_operator_endpoints_refuse_every_non_operator_in_both_partners(
    world: World, party: str
) -> None:
    client = world.client()
    p = world.a if party == "a" else world.b
    for e in (e for e in ENDPOINTS if e.kind is Kind.OPERATOR):
        for role in (Role.CONSULTANT, Role.PARTNER_ADMIN):
            r = client.request(e.method, e.path, headers=p[role].headers)
            assert r.status_code == 403, f"{e} as {role} of {p.name}"
        assert client.request(e.method, e.path).status_code == 401
        assert (
            client.request(e.method, e.path, headers=p[Role.PLATFORM_OPERATOR].headers).status_code
            == 200
        )


@pytest.mark.parametrize("role", list(Role))
def test_tenant_endpoints_refuse_cross_partner_access(world: World, role: Role) -> None:
    """B (any role) asks for A's resources: 404, identical to a missing id, A untouched."""
    client = world.client()
    before = snapshot_all_tenants(world.engine, world.a)
    for e in (e for e in ENDPOINTS if e.kind is Kind.TENANT):
        assert_cross_partner_refused(client, e, world.a.ids, world.b[role].headers)
    assert snapshot_all_tenants(world.engine, world.a) == before


# --- the harness itself: prove it catches a leak and passes a scoped route ---


def _probe_app(world: World) -> FastAPI:
    app = make_app(world.db)

    @app.get("/api/_probe/scoped/{project_id}")
    def scoped(
        project_id: uuid.UUID,
        ctx: RequestContext = Depends(get_request_context),  # noqa: B008
    ) -> dict[str, str]:
        with world.db.tenant(ctx) as repos:
            return {"name": repos.projects.get(project_id).name}

    @app.get("/api/_probe/leaky/{project_id}")
    def leaky(
        project_id: uuid.UUID,
        ctx: RequestContext = Depends(get_request_context),  # noqa: B008
    ) -> dict[str, str]:
        with Session(world.engine) as s:  # bypasses the repository layer on purpose
            row = s.execute(select(Project).where(Project.id == project_id)).scalar_one_or_none()
            if row is None:
                raise NotFound
            return {"name": row.name}

    return app


def test_harness_passes_a_scoped_route_and_catches_a_leaky_one(world: World) -> None:
    client = world.client(_probe_app(world))
    scoped = Endpoint(
        "GET", "/api/_probe/scoped/{project_id}", Kind.TENANT, {"project_id": "project_id"}
    )
    leaky = Endpoint(
        "GET", "/api/_probe/leaky/{project_id}", Kind.TENANT, {"project_id": "project_id"}
    )
    b_headers = world.b[Role.CONSULTANT].headers

    assert_cross_partner_refused(client, scoped, world.a.ids, b_headers)
    with pytest.raises(AssertionError, match="cross-partner got 200"):
        assert_cross_partner_refused(client, leaky, world.a.ids, b_headers)
    # The owner can still use the scoped route, so the 404 above is isolation, not breakage.
    own = client.get(
        f"/api/_probe/scoped/{world.a.ids['project_id']}", headers=world.a[Role.CONSULTANT].headers
    )
    assert own.status_code == 200


# --- repository level: every operation, B against A's rows ---


def _id(ids: dict[str, str], key: str) -> uuid.UUID:
    return uuid.UUID(ids[key])


# Each case tries to reach partner A's data as partner B and must raise NotFound.
REFUSED: dict[str, Callable[[TenantRepositories, dict[str, str]], Any]] = {
    "projects.get": lambda r, i: r.projects.get(_id(i, "project_id")),
    "projects.get(seed)": lambda r, i: r.projects.get(_id(i, "seed_project_id")),
    "projects.rename": lambda r, i: r.projects.rename(_id(i, "project_id"), "hijacked"),
    "users.get": lambda r, i: r.users.get(_id(i, "user_id")),
    "users.get_by_email": lambda r, i: r.users.get_by_email(i["a_email"]),
    "users.set_status": lambda r, i: r.users.set_status(_id(i, "user_id"), UserStatus.DEACTIVATED),
    "users.set_display_name": lambda r, i: r.users.set_display_name(_id(i, "user_id"), "pwned"),
    "user_roles.grant": lambda r, i: r.user_roles.grant(_id(i, "user_id"), Role.PLATFORM_OPERATOR),
    "user_roles.revoke": lambda r, i: r.user_roles.revoke(_id(i, "user_id"), Role.CONSULTANT),
    "intake_drafts.get_for_project": lambda r, i: r.intake_drafts.get_for_project(
        _id(i, "project_id")
    ),
    "intake_drafts.save": lambda r, i: r.intake_drafts.save(_id(i, "project_id"), {"x": 1}),
    "audit_events.get": lambda r, i: r.audit_events.get(_id(i, "audit_id")),
}

LISTS: dict[str, Callable[[TenantRepositories], list[Any]]] = {
    "users.list_all": lambda r: r.users.list_all(limit=1000),
    "user_roles.list_all": lambda r: r.user_roles.list_all(limit=1000),
    "projects.list_all": lambda r: r.projects.list_all(limit=1000),
    "intake_drafts.list_all": lambda r: r.intake_drafts.list_all(limit=1000),
    "audit_events.list_all": lambda r: r.audit_events.list_all(limit=1000),
}


@pytest.mark.parametrize("role", list(Role))
@pytest.mark.parametrize("case", list(REFUSED))
def test_repository_operations_on_another_partners_rows_raise_not_found(
    world: World, case: str, role: Role
) -> None:
    ids = {**world.a.ids, "a_email": world.a[Role.CONSULTANT].email}
    before = snapshot_all_tenants(world.engine, world.a)
    with pytest.raises(NotFound), world.db.tenant(world.b[role].ctx) as repos:
        REFUSED[case](repos, ids)
    assert snapshot_all_tenants(world.engine, world.a) == before


@pytest.mark.parametrize("role", list(Role))
@pytest.mark.parametrize("case", list(LISTS))
def test_lists_contain_only_the_callers_partner(world: World, case: str, role: Role) -> None:
    with world.db.tenant(world.b[role].ctx) as repos:
        rows = LISTS[case](repos)
    assert rows, f"{case}: partner B has seeded rows, an empty list would hide a bug"
    assert {r.partner_id for r in rows} == {world.b.partner_id}


@pytest.mark.parametrize("role", list(Role))
def test_roles_of_another_partners_user_are_invisible(world: World, role: Role) -> None:
    with world.db.tenant(world.b[role].ctx) as repos:
        assert repos.user_roles.roles_for(_id(world.a.ids, "user_id")) == frozenset()


def test_a_full_attack_by_b_leaves_every_a_row_unchanged(world: World) -> None:
    """All refused operations in one go, as all three of B's roles, then compare A."""
    ids = {**world.a.ids, "a_email": world.a[Role.CONSULTANT].email}
    before = snapshot_all_tenants(world.engine, world.a)
    attempted = 0
    for role in Role:
        for fn in REFUSED.values():
            with pytest.raises(NotFound), world.db.tenant(world.b[role].ctx) as repos:
                fn(repos, ids)
            attempted += 1
    assert attempted == len(REFUSED) * len(Role)
    assert snapshot_all_tenants(world.engine, world.a) == before


def test_b_writes_are_stamped_with_bs_partner_even_when_a_ids_are_in_play(world: World) -> None:
    ctx: RequestContext = world.b[Role.PARTNER_ADMIN].ctx
    with world.db.tenant(ctx) as repos:
        mine = repos.projects.add("b-new")
        event = repos.audit_events.add(
            "b.write", "project", target_id=_id(world.a.ids, "project_id")
        )
    assert mine.partner_id == world.b.partner_id
    with Session(world.engine) as s:
        row = s.get(AuditEvent, event.id)
        assert row is not None
        assert row.partner_id == world.b.partner_id  # not A, despite pointing at A's project id


def test_ids_are_unique_between_the_two_partners(world: World) -> None:
    assert not set(world.a.ids.values()) & set(world.b.ids.values())
    assert world.a.partner_id != world.b.partner_id
