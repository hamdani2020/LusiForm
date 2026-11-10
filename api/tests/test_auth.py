"""Authentication: JWT verification, request context, role gating."""

import base64
import hashlib
import hmac
import json
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from jwt import PyJWKClient
from jwt.algorithms import RSAAlgorithm
from jwt.exceptions import PyJWKClientConnectionError
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.config import ApiSettings
from app.context import RequestContext
from app.data.database import Database
from app.data.models import Partner, User, UserRole
from app.deps import get_database, get_request_context, get_verifier
from app.enums import Role
from app.jwt_verifier import AuthUnavailable, JwtVerifier, TokenError, issuer_for
from app.main import create_app
from app.routers.admin import make_admin_router, make_operator_router

ISSUER = issuer_for("us-east-1", "us-east-1_TESTPOOL")
CLIENT_ID = "test-client-id"


def _keypair() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


SIGNING_KEY = _keypair()
OTHER_KEY = _keypair()


class _Key:
    def __init__(self, key: Any) -> None:
        self.key = key


class StaticKeys:
    """KeyProvider that always returns the test public key."""

    def get_signing_key_from_jwt(self, token: str) -> _Key:
        return _Key(SIGNING_KEY.public_key())


class BrokenKeys:
    def get_signing_key_from_jwt(self, token: str) -> _Key:
        raise PyJWKClientConnectionError("jwks down")


def make_token(
    sub: str = "sub-1",
    *,
    key: Any = None,
    algorithm: str = "RS256",
    drop: tuple[str, ...] = (),
    **overrides: Any,
) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "sub": sub,
        "iss": ISSUER,
        "client_id": CLIENT_ID,
        "token_use": "access",
        "iat": now,
        "exp": now + 300,
    }
    claims.update(overrides)
    for name in drop:
        claims.pop(name)
    return jwt.encode(claims, key or SIGNING_KEY, algorithm=algorithm, headers={"kid": "k1"})


@pytest.fixture
def verifier() -> JwtVerifier:
    return JwtVerifier(issuer=ISSUER, client_id=CLIENT_ID, keys=StaticKeys())


# --- 5.1 JWT verification ---


def test_valid_token_is_accepted(verifier: JwtVerifier) -> None:
    claims = verifier.verify(make_token("abc"))
    assert claims.sub == "abc"
    assert claims.client_id == CLIENT_ID


@pytest.mark.parametrize(
    "token",
    [
        pytest.param(make_token(exp=int(time.time()) - 10), id="expired"),
        pytest.param(make_token(key=OTHER_KEY), id="bad-signature"),
        pytest.param(make_token(iss="https://evil.example.com/pool"), id="wrong-issuer"),
        pytest.param(make_token(client_id="someone-else"), id="wrong-client-id"),
        pytest.param(make_token(token_use="id"), id="id-token-not-access"),
        pytest.param(make_token(drop=("exp",)), id="missing-exp"),
        pytest.param(make_token(drop=("client_id",)), id="missing-client-id"),
        pytest.param(make_token(drop=("sub",)), id="missing-sub"),
        pytest.param(make_token(sub=""), id="empty-sub"),
        pytest.param("not-a-jwt", id="garbage"),
        pytest.param("", id="empty"),
    ],
)
def test_bad_tokens_are_rejected(verifier: JwtVerifier, token: str) -> None:
    with pytest.raises(TokenError):
        verifier.verify(token)


def test_unsigned_and_hmac_confusion_tokens_are_rejected(verifier: JwtVerifier) -> None:
    now = int(time.time())
    claims = {
        "sub": "x",
        "iss": ISSUER,
        "client_id": CLIENT_ID,
        "token_use": "access",
        "exp": now + 300,
    }
    unsigned = jwt.encode(claims, key="", algorithm="none", headers={"kid": "k1"})
    with pytest.raises(TokenError):
        verifier.verify(unsigned)
    # Classic alg-confusion: sign with HS256 using the public key bytes as the secret.
    pub_pem = SIGNING_KEY.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )

    def b64(data: bytes) -> bytes:
        return base64.urlsafe_b64encode(data).rstrip(b"=")

    head = b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": "k1"}).encode())
    body = b64(json.dumps(claims).encode())
    sig = b64(hmac.new(pub_pem, head + b"." + body, hashlib.sha256).digest())
    with pytest.raises(TokenError):
        verifier.verify((head + b"." + body + b"." + sig).decode())


def test_jwks_outage_is_not_reported_as_an_invalid_token() -> None:
    v = JwtVerifier(issuer=ISSUER, client_id=CLIENT_ID, keys=BrokenKeys())
    with pytest.raises(AuthUnavailable):
        v.verify(make_token())


def test_jwks_is_cached_and_refreshed_on_key_rotation(monkeypatch: pytest.MonkeyPatch) -> None:
    def jwk(key: rsa.RSAPrivateKey, kid: str) -> dict[str, Any]:
        d: dict[str, Any] = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
        d.update(kid=kid, use="sig", alg="RS256")
        return d

    published: dict[str, Any] = {"keys": [jwk(SIGNING_KEY, "k1")]}
    fetches = 0

    client = PyJWKClient("https://example.invalid/jwks.json", cooldown_duration=0)

    def fake_fetch() -> dict[str, Any]:
        nonlocal fetches
        fetches += 1
        client.jwk_set_cache.put(published)  # type: ignore[union-attr]
        return published

    monkeypatch.setattr(client, "fetch_data", fake_fetch)
    v = JwtVerifier(issuer=ISSUER, client_id=CLIENT_ID, keys=client)

    assert v.verify(make_token()).sub == "sub-1"
    assert v.verify(make_token()).sub == "sub-1"
    assert fetches == 1  # second verification served from cache

    # Cognito rotates: a new kid appears. The unknown kid forces a refresh.
    rotated = jwt.encode(
        {
            "sub": "rotated",
            "iss": ISSUER,
            "client_id": CLIENT_ID,
            "token_use": "access",
            "exp": int(time.time()) + 300,
        },
        OTHER_KEY,
        algorithm="RS256",
        headers={"kid": "k2"},
    )
    with pytest.raises(TokenError):  # still unknown: not published yet
        v.verify(rotated)
    published["keys"].append(jwk(OTHER_KEY, "k2"))
    assert v.verify(rotated).sub == "rotated"


# --- 5.2 / 5.3 request context and roles (through the real app + Postgres) ---


@dataclass
class Account:
    sub: str
    user_id: uuid.UUID
    partner_id: uuid.UUID


def _account(
    s: Session,
    roles: list[Role],
    *,
    user_status: str = "active",
    partner_status: str = "active",
    sub: str | None = None,
) -> Account:
    p = Partner(name=f"p-{uuid.uuid4().hex}", status=partner_status)
    s.add(p)
    s.flush()
    sub = sub or f"sub-{uuid.uuid4().hex}"
    u = User(
        partner_id=p.id,
        email=f"{uuid.uuid4().hex}@example.com",
        cognito_sub=sub,
        status=user_status,
        display_name="Test User",
    )
    s.add(u)
    s.flush()
    for r in roles:
        s.add(UserRole(user_id=u.id, role=r.value, partner_id=p.id))
    s.flush()
    return Account(sub, u.id, p.id)


@pytest.fixture
def client(migrated_engine: Engine) -> Iterator[TestClient]:
    app: FastAPI = create_app(ApiSettings())
    app.dependency_overrides[get_verifier] = lambda: JwtVerifier(
        issuer=ISSUER, client_id=CLIENT_ID, keys=StaticKeys()
    )
    app.dependency_overrides[get_database] = lambda: Database(migrated_engine)

    admin = make_admin_router()
    operator = make_operator_router()

    @admin.get("/probe-admin")
    def probe_admin() -> dict[str, str]:
        return {"ok": "admin"}

    @operator.get("/probe-operator")
    def probe_operator() -> dict[str, str]:
        return {"ok": "operator"}

    @app.get("/api/probe-ctx")
    def probe_ctx(ctx: RequestContext = Depends(get_request_context)) -> dict[str, Any]:  # noqa: B008
        return {"roles": sorted(ctx.roles), "partner_id": str(ctx.partner_id)}

    app.include_router(admin)
    app.include_router(operator)
    yield TestClient(app)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_missing_or_malformed_credentials_get_401(client: TestClient) -> None:
    for headers in ({}, {"Authorization": "Basic abc"}, _bearer("garbage"), _bearer("")):
        r = client.get("/api/me", headers=headers)
        assert r.status_code == 401, headers
        assert r.headers["WWW-Authenticate"] == "Bearer"


def test_expired_and_forged_tokens_get_401(client: TestClient) -> None:
    for token in (make_token(exp=int(time.time()) - 5), make_token(key=OTHER_KEY)):
        assert client.get("/api/me", headers=_bearer(token)).status_code == 401


def test_me_returns_identity_from_the_database(client: TestClient, migrated_engine: Engine) -> None:
    with Session(migrated_engine) as s:
        acct = _account(s, [Role.CONSULTANT, Role.PARTNER_ADMIN])
        s.commit()
    r = client.get("/api/me", headers=_bearer(make_token(acct.sub)))
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == str(acct.user_id)
    assert body["partner_id"] == str(acct.partner_id)
    assert body["roles"] == ["consultant", "partner_admin"]
    assert body["display_name"] == "Test User"
    assert r.headers["X-Request-ID"]


@pytest.mark.parametrize(
    ("user_status", "partner_status"),
    [("deactivated", "active"), ("invited", "active"), ("active", "suspended")],
)
def test_inactive_user_or_suspended_partner_gets_403(
    client: TestClient, migrated_engine: Engine, user_status: str, partner_status: str
) -> None:
    with Session(migrated_engine) as s:
        acct = _account(
            s, [Role.CONSULTANT], user_status=user_status, partner_status=partner_status
        )
        s.commit()
    r = client.get("/api/me", headers=_bearer(make_token(acct.sub)))
    assert r.status_code == 403
    assert r.json() == {"detail": "Forbidden"}


def test_valid_token_without_a_user_record_gets_403(client: TestClient) -> None:
    r = client.get("/api/me", headers=_bearer(make_token("nobody-knows-me")))
    assert r.status_code == 403
    assert r.json() == {"detail": "Forbidden"}


def test_client_supplied_roles_have_no_effect(client: TestClient, migrated_engine: Engine) -> None:
    with Session(migrated_engine) as s:
        acct = _account(s, [Role.CONSULTANT])
        s.commit()
    forged: dict[str, Any] = {
        "custom:role": "platform_operator",
        "cognito:groups": ["platform_operator", "partner_admin"],
        "roles": ["platform_operator"],
    }
    token = make_token(acct.sub, **forged)
    headers = {
        **_bearer(token),
        "X-Role": "platform_operator",
        "X-Roles": "platform_operator",
        "X-Partner-Id": str(uuid.uuid4()),
    }
    ctx = client.get("/api/probe-ctx", headers=headers, params={"role": "platform_operator"}).json()
    assert ctx["roles"] == ["consultant"]
    assert ctx["partner_id"] == str(acct.partner_id)
    assert client.get("/api/admin/probe-admin", headers=headers).status_code == 403
    assert client.get("/api/admin/probe-operator", headers=headers).status_code == 403


def test_role_gating_matrix(client: TestClient, migrated_engine: Engine) -> None:
    with Session(migrated_engine) as s:
        consultant = _account(s, [Role.CONSULTANT])
        admin = _account(s, [Role.PARTNER_ADMIN])
        operator = _account(s, [Role.PLATFORM_OPERATOR])
        s.commit()

    def status(acct: Account, path: str) -> int:
        return client.get(path, headers=_bearer(make_token(acct.sub))).status_code

    assert status(consultant, "/api/admin/probe-admin") == 403
    assert status(consultant, "/api/admin/probe-operator") == 403
    assert status(admin, "/api/admin/probe-admin") == 200
    assert status(admin, "/api/admin/probe-operator") == 403
    assert status(operator, "/api/admin/probe-admin") == 200
    assert status(operator, "/api/admin/probe-operator") == 200
    # Gated routes still need authentication first.
    assert client.get("/api/admin/probe-admin").status_code == 401
    assert client.get("/api/admin/probe-operator").status_code == 401


def test_health_stays_public_and_everything_else_requires_context() -> None:
    app = create_app(ApiSettings())
    public = {"/api/health"}
    unprotected = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or route.path in public:
            continue
        if not _uses(route.dependant, get_request_context):
            unprotected.append(route.path)
    assert unprotected == []
    assert any(isinstance(r, APIRoute) and r.path == "/api/me" for r in app.routes)


def _uses(dependant: Any, call: Any) -> bool:
    return any(d.call is call or _uses(d, call) for d in dependant.dependencies)


def test_unconfigured_auth_fails_closed_with_503() -> None:
    get_verifier.cache_clear()
    app = create_app(ApiSettings())
    r = TestClient(app).get("/api/me", headers=_bearer(make_token()))
    assert r.status_code == 503
