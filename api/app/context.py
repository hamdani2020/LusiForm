"""Per-request identity. The only place handlers and repositories read `partner_id` from."""

import uuid
from dataclasses import dataclass

from app.enums import Role


@dataclass(frozen=True, slots=True)
class RequestContext:
    user_id: uuid.UUID
    partner_id: uuid.UUID
    roles: frozenset[Role]
    request_id: str

    def has_role(self, *roles: Role) -> bool:
        return any(r in self.roles for r in roles)
