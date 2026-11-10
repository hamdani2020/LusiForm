"""Audit helper.

`record` appends an `audit_events` row through the same unit of work (same session,
same transaction) as the write it describes, so the two commit or roll back together.
Call it inside the `with db.tenant(ctx) as repos:` block that performs the write.

Snapshots are sanitised (secrets and free text redacted, JSON-safe) before storage.
Actor and partner always come from the request context.
"""

import uuid
from typing import Any

from app.data.database import TenantRepositories
from app.data.models import AuditEvent


def record(
    repos: TenantRepositories,
    action: str,
    target_type: str,
    *,
    target_id: uuid.UUID | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AuditEvent:
    return repos.audit_events.add(
        action, target_type, target_id=target_id, before=before, after=after
    )
