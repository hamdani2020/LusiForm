"""Worker settings, from the environment only (shared base in lusiform_common).

The worker's boundary (security.md): it may read and write the artifact bucket and the job
queue, nothing else. It has no database setting on purpose; job data arrives in the
message payload. AWS credentials come from the ECS task role (or LocalStack's dummy
credentials in local dev), never from these settings.
"""

from lusiform_common import BaseAppSettings
from pydantic import Field, model_validator


class WorkerSettings(BaseAppSettings):
    service_name: str = Field(default="lusiform-worker", min_length=1)

    # The job queue: give the URL, or the name and let the worker resolve it.
    job_queue_url: str | None = None
    job_queue_name: str | None = None

    # Artifact bucket the job handlers (later specs) write to. Not used by the loop itself.
    artifact_bucket: str | None = None

    # Long polling: SQS holds the request open up to this many seconds (max 20).
    poll_wait_seconds: int = Field(default=20, ge=0, le=20)
    max_messages: int = Field(default=1, ge=1, le=10)
    # Delay before polling again after a queue error.
    error_backoff_seconds: float = Field(default=5.0, gt=0, le=300)

    @model_validator(mode="after")
    def _queue_is_set(self) -> "WorkerSettings":
        if not (self.job_queue_url or self.job_queue_name):
            raise ValueError("set JOB_QUEUE_URL or JOB_QUEUE_NAME")
        return self
