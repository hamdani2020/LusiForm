"""Job envelope parsing and dispatch.

A job message body is JSON: `{"type": "<job type>", "job_id": "<uuid>", ...}`. Handlers
for each type arrive with the specs that need them (generation, validation, sandbox).
Until a type has a handler, its messages are logged and left on the queue: they are not
deleted, so they become visible again after the visibility timeout and, with a redrive
policy, end up in the dead-letter queue instead of being lost.

Only the type, job id and SQS message id are ever logged. The body can carry intake data,
which must not reach logs.
"""

import json
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


@dataclass(frozen=True)
class Job:
    type: str
    job_id: uuid.UUID
    payload: Mapping[str, Any]


class Outcome(StrEnum):
    DONE = "done"  # handled: delete the message
    UNKNOWN_TYPE = "unknown_type"  # no handler yet: leave it
    MALFORMED = "malformed"  # not a valid envelope: leave it (goes to the DLQ)


Handler = Callable[[Job], None]

# job type -> handler. Empty in the foundation spec.
HANDLERS: dict[str, Handler] = {}


class MalformedJob(ValueError):  # noqa: N818 - domain name
    """The message body is not a valid job envelope."""


def parse(body: str) -> Job:
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError) as exc:
        raise MalformedJob("body is not JSON") from exc
    if not isinstance(data, dict):
        raise MalformedJob("body is not a JSON object")
    job_type = data.get("type")
    if not isinstance(job_type, str) or not job_type:
        raise MalformedJob("missing job type")
    try:
        job_id = uuid.UUID(str(data.get("job_id")))
    except ValueError as exc:
        raise MalformedJob("missing or invalid job_id") from exc
    return Job(type=job_type, job_id=job_id, payload=data)


def dispatch(job: Job, handlers: Mapping[str, Handler] = HANDLERS) -> Outcome:
    handler = handlers.get(job.type)
    if handler is None:
        return Outcome.UNKNOWN_TYPE
    handler(job)
    return Outcome.DONE
