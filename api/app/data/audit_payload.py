"""Sanitising of audit before/after snapshots.

Audit rows are permanent (append-only), so what goes in must be safe forever: values
under sensitive or free-text keys are replaced with a placeholder (same rules as
logging), and everything is converted to plain JSON types.
"""

from typing import Any

from lusiform_common import redact
from pydantic_core import to_jsonable_python


def sanitize(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    cleaned = redact(to_jsonable_python(payload))
    assert isinstance(cleaned, dict)  # noqa: S101 - redact preserves mappings
    return cleaned
