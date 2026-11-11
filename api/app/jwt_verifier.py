"""Cognito access-token verification.

Checks, in order: signature (RS256 only, key from the pool's JWKS), `iss`, `exp`,
`token_use == "access"`, and `client_id`. Cognito access tokens carry `client_id`
rather than `aud`, so audience is checked through `client_id`.

The JWKS is cached by `PyJWKClient` (5 minute TTL). An unknown `kid` forces one
refresh, rate-limited by the client's cooldown, which is how key rotation is picked
up without letting an attacker trigger a fetch per request.
"""

from dataclasses import dataclass
from typing import Any, Protocol

import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError, PyJWTError

from app.config import ApiSettings

ALGORITHMS = ["RS256"]  # never derived from the token header
REQUIRED_CLAIMS = ["exp", "iss", "sub", "token_use", "client_id"]


class TokenError(Exception):
    """The token is missing, expired, or invalid. Mapped to 401; never says why."""

    def __init__(self) -> None:
        super().__init__("invalid token")


class AuthUnavailable(Exception):  # noqa: N818 - mapped to 503
    """Keys could not be fetched; the token was neither accepted nor rejected."""


@dataclass(frozen=True)
class TokenClaims:
    sub: str
    client_id: str


class _SigningKey(Protocol):
    @property
    def key(self) -> Any: ...


class KeyProvider(Protocol):
    def get_signing_key_from_jwt(self, token: str) -> _SigningKey: ...


def issuer_for(region: str, user_pool_id: str) -> str:
    return f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"


class JwtVerifier:
    def __init__(self, *, issuer: str, client_id: str, keys: KeyProvider) -> None:
        self._issuer = issuer
        self._client_id = client_id
        self._keys = keys

    @classmethod
    def from_settings(cls, settings: ApiSettings) -> "JwtVerifier":
        if not (
            settings.cognito_region
            and settings.cognito_user_pool_id
            and settings.cognito_app_client_id
        ):
            raise RuntimeError(
                "COGNITO_REGION, COGNITO_USER_POOL_ID, COGNITO_APP_CLIENT_ID not set"
            )
        issuer = issuer_for(settings.cognito_region, settings.cognito_user_pool_id)
        keys = PyJWKClient(f"{issuer}/.well-known/jwks.json", cache_jwk_set=True, lifespan=300)
        return cls(issuer=issuer, client_id=settings.cognito_app_client_id, keys=keys)

    def verify(self, token: str) -> TokenClaims:
        try:
            signing_key = self._keys.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=ALGORITHMS,
                issuer=self._issuer,
                options={"require": REQUIRED_CLAIMS, "verify_aud": False},
            )
        except PyJWKClientConnectionError as exc:
            raise AuthUnavailable from exc
        except PyJWTError as exc:
            raise TokenError from exc
        if claims["token_use"] != "access" or claims["client_id"] != self._client_id:  # noqa: S105
            raise TokenError
        if not isinstance(claims["sub"], str) or not claims["sub"]:
            raise TokenError
        return TokenClaims(sub=claims["sub"], client_id=claims["client_id"])
