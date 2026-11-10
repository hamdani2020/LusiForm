"""First-operator bootstrap: creates exactly one operator, refuses afterwards, audits it."""

import json
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.bootstrap_operator import main
from app.config import ApiSettings
from app.data.bootstrap import BootstrapError, bootstrap_platform_operator
from app.data.database import Database
from app.data.models import AuditEvent, Partner, User, UserRole
from app.deps import get_database, get_verifier
from app.jwt_verifier import JwtVerifier
from app.main import create_app
from tests.test_auth import CLIENT_ID, ISSUER, StaticKeys, make_token

ARGS = {
    "partner_name": "Lusiform",
    "email": "  Ops@Example.COM ",
    "cognito_sub": "sub-operator-1",
    "display_name": "First Operator",
}


def _count(engine: Engine, model: type) -> int:
    with Session(engine) as s:
        return s.execute(select(func.count()).select_from(model)).scalar_one()


def test_creates_partner_active_user_operator_role_and_audit(migrated_engine: Engine) -> None:
    result = bootstrap_platform_operator(migrated_engine, **ARGS)

    with Session(migrated_engine) as s:
        partner = s.get(Partner, result.partner_id)
        user = s.get(User, result.user_id)
        assert partner is not None and partner.name == "Lusiform"
        assert user is not None
        assert (user.email, user.cognito_sub, user.status) == (
            "ops@example.com",
            "sub-operator-1",
            "active",
        )
        roles = s.execute(select(UserRole.role).where(UserRole.user_id == user.id)).scalars()
        assert list(roles) == ["platform_operator"]
        event = s.execute(select(AuditEvent)).scalar_one()
        assert event.action == "bootstrap.platform_operator.create"
        assert event.actor_user_id is None
        assert event.partner_id == partner.id
        assert event.target_id == user.id


def test_refuses_once_an_operator_exists_and_writes_nothing(migrated_engine: Engine) -> None:
    bootstrap_platform_operator(migrated_engine, **ARGS)
    before = {m: _count(migrated_engine, m) for m in (Partner, User, UserRole, AuditEvent)}

    second = {**ARGS, "partner_name": "Other", "email": "x@example.com", "cognito_sub": "sub-2"}
    with pytest.raises(BootstrapError, match="already exists"):
        bootstrap_platform_operator(migrated_engine, **second)

    assert {m: _count(migrated_engine, m) for m in before} == before


def test_concurrent_runs_create_only_one_operator(migrated_engine: Engine) -> None:
    outcomes: list[str] = []

    def run(n: int) -> None:
        try:
            bootstrap_platform_operator(
                migrated_engine,
                partner_name=f"Lusiform {n}",
                email=f"ops{n}@example.com",
                cognito_sub=f"sub-{n}",
            )
            outcomes.append("ok")
        except BootstrapError:
            outcomes.append("refused")

    threads = [threading.Thread(target=run, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(outcomes) == ["ok", "refused", "refused", "refused"]
    with Session(migrated_engine) as s:
        operators = s.execute(
            select(func.count()).where(UserRole.role == "platform_operator")
        ).scalar_one()
    assert operators == 1


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("email", "not-an-email", "email"),
        ("partner_name", "   ", "partner name"),
        ("cognito_sub", "", "cognito sub"),
    ],
)
def test_rejects_invalid_input(
    migrated_engine: Engine, field: str, value: str, message: str
) -> None:
    with pytest.raises(BootstrapError, match=message):
        bootstrap_platform_operator(migrated_engine, **{**ARGS, field: value})
    assert _count(migrated_engine, Partner) == 0


def test_bootstrapped_operator_can_use_operator_routes(migrated_engine: Engine) -> None:
    bootstrap_platform_operator(migrated_engine, **ARGS)
    app = create_app(ApiSettings())
    app.dependency_overrides[get_verifier] = lambda: JwtVerifier(
        issuer=ISSUER, client_id=CLIENT_ID, keys=StaticKeys()
    )
    app.dependency_overrides[get_database] = lambda: Database(migrated_engine)
    headers = {"Authorization": f"Bearer {make_token('sub-operator-1')}"}

    client = TestClient(app)
    me = client.get("/api/me", headers=headers).json()
    assert me["roles"] == ["platform_operator"]
    assert me["partner_name"] == "Lusiform"
    assert client.get("/api/admin/partners", headers=headers).status_code == 200


def test_cli_exit_codes_and_logs_without_email(
    migrated_engine: Engine, scratch_db_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = [
        "--partner-name",
        "Lusiform",
        "--email",
        "ops@example.com",
        "--cognito-sub",
        "sub-cli",
    ]
    assert main(argv, ApiSettings()) == 0
    assert main(argv, ApiSettings()) == 1  # second run refused

    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")]
    assert [x["message"] for x in lines] == ["platform operator created", "bootstrap refused"]
    assert "ops@example.com" not in json.dumps(lines)
    assert lines[0]["user_id"] and lines[0]["partner_id"]


def test_cli_requires_its_arguments() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--email", "a@example.com"], ApiSettings())
    assert exc.value.code == 2
