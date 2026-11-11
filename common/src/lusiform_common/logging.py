"""Structured JSON logging shared by api and worker.

Log lines carry request_id, partner_id, user_id and project_id from a context.
Sensitive keys and intake free text are redacted; they must never reach logs.
"""

import logging
from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog
from structlog.contextvars import (
    bind_contextvars,
    clear_contextvars,
    merge_contextvars,
    unbind_contextvars,
)

CONTEXT_KEYS = ("request_id", "partner_id", "user_id", "project_id")

REDACTED = "[REDACTED]"

# Keys whose values are dropped (case-insensitive, matched on substring for the
# credential-like ones, exact for free-text fields).
_SENSITIVE_SUBSTRINGS = (
    "password",
    "secret",
    "token",
    "credential",
    "authorization",
    "api_key",
    "apikey",
    "external_id",
    "cookie",
    "private_key",
    "session",
)
_FREE_TEXT_KEYS = frozenset(
    {"notes", "note", "free_text", "intake", "intake_text", "answers", "prompt", "message_body"}
)


def _is_sensitive(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    return lowered in _FREE_TEXT_KEYS or any(s in lowered for s in _SENSITIVE_SUBSTRINGS)


def redact(value: Any) -> Any:
    """Recursively replace values under sensitive keys with a placeholder."""
    if isinstance(value, Mapping):
        return {
            k: REDACTED if isinstance(k, str) and _is_sensitive(k) else redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact(v) for v in value]
    return value


def _redaction_processor(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    for key in list(event_dict):
        if key == "event":
            continue
        if _is_sensitive(key):
            event_dict[key] = REDACTED
        else:
            event_dict[key] = redact(event_dict[key])
    return event_dict


def configure_logging(service_name: str, level: str = "INFO") -> None:
    """Configure structlog and stdlib logging to emit JSON lines on stdout."""
    processors: list[Any] = [
        merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.format_exc_info,
        _redaction_processor,
        structlog.processors.EventRenamer("message"),
        structlog.processors.JSONRenderer(),
    ]
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        # No explicit file: PrintLogger resolves sys.stdout when each logger is created,
        # so output follows stream redirection (tests, container runtimes) instead of a
        # stream captured at configure time.
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )
    clear_contextvars()
    bind_contextvars(service=service_name)


def get_logger(name: str | None = None) -> Any:
    return structlog.get_logger(name)


def bind_log_context(**values: str | None) -> None:
    """Bind request_id / partner_id / user_id / project_id for the current context."""
    unknown = set(values) - set(CONTEXT_KEYS)
    if unknown:
        raise ValueError(f"unsupported log context keys: {sorted(unknown)}")
    bind_contextvars(**{k: v for k, v in values.items() if v is not None})


def clear_log_context() -> None:
    """Clear request-scoped context (keeps the service name)."""
    unbind_contextvars(*CONTEXT_KEYS)
