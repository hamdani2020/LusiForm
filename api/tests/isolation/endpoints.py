"""The endpoint table for the tenant isolation suite.

EVERY route the app registers must appear here with a classification. The coverage
test fails when a route is missing, so a new endpoint cannot ship without deciding
how isolation is proven for it:

- PUBLIC: no auth, no tenant data (health).
- SELF: returns only the caller's own identity; no id taken from the client.
- OPERATOR: cross-partner by design; platform_operator only, audited.
- TENANT: acts on a tenant-owned resource named by id in the path. The suite sends
  partner B's token with partner A's resource id and requires 404 identical to a
  missing id, and requires A's rows to be unchanged afterwards.

For TENANT entries, `ids` maps each path parameter to a key of partner A's seeded
ids (see `Party.ids` in conftest.py).
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute


class Kind(StrEnum):
    PUBLIC = "public"
    SELF = "self"
    OPERATOR = "operator"
    TENANT = "tenant"


@dataclass(frozen=True)
class Endpoint:
    method: str
    path: str  # route template, exactly as registered, e.g. /api/projects/{project_id}
    kind: Kind
    ids: dict[str, str] = field(default_factory=dict)
    body: dict[str, Any] | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.method, self.path)

    def __repr__(self) -> str:
        return f"{self.method} {self.path} [{self.kind.value}]"


# Add every new route here. Tenant-resource routes are added by the specs that create them.
ENDPOINTS: list[Endpoint] = [
    Endpoint("GET", "/api/health", Kind.PUBLIC),
    Endpoint("GET", "/api/me", Kind.SELF),
    Endpoint("GET", "/api/admin/partners", Kind.OPERATOR),
]


def registered_routes(app: FastAPI) -> set[tuple[str, str]]:
    """(method, path template) for every API route on the app."""
    out: set[tuple[str, str]] = set()
    for route in app.routes:
        if isinstance(route, APIRoute):
            for method in route.methods:
                out.add((method, route.path))
    return out
