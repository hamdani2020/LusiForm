"""Worker entrypoint: long-poll the SQS job queue and dispatch jobs.

No job handlers exist yet (foundation spec). Unknown job types are logged and left on the
queue for the specs that add them. Shutdown: SIGTERM/SIGINT set a stop flag; the loop
finishes the current poll (at most `poll_wait_seconds`, 20 s by default, inside ECS's 30 s
stop timeout) and exits.
"""

import signal
import threading
from collections.abc import Mapping
from types import FrameType
from typing import Any, Protocol, cast

from botocore.exceptions import BotoCoreError, ClientError
from lusiform_common import bind_log_context, clear_log_context, configure_logging, get_logger

from app.config import WorkerSettings
from app.jobs import HANDLERS, Handler, MalformedJob, Outcome, dispatch, parse

log = get_logger("worker")


class QueueClient(Protocol):
    """The subset of the boto3 SQS client the worker uses (so tests can stub it)."""

    def receive_message(self, **kwargs: Any) -> Mapping[str, Any]: ...
    def delete_message(self, **kwargs: Any) -> Any: ...
    def get_queue_url(self, **kwargs: Any) -> Mapping[str, Any]: ...


def sqs_client(settings: WorkerSettings) -> QueueClient:
    import boto3

    # Endpoint (LocalStack locally) and credentials come from the standard AWS
    # environment (AWS_ENDPOINT_URL, task role), not from Lusiform settings.
    return cast(QueueClient, boto3.client("sqs", region_name=settings.aws_region))


def resolve_queue_url(settings: WorkerSettings, client: QueueClient) -> str:
    if settings.job_queue_url:
        return settings.job_queue_url
    response = client.get_queue_url(QueueName=settings.job_queue_name)
    return str(response["QueueUrl"])


class Worker:
    def __init__(
        self,
        settings: WorkerSettings,
        client: QueueClient,
        handlers: Mapping[str, Handler] = HANDLERS,
    ) -> None:
        self._settings = settings
        self._client = client
        self._handlers = handlers
        self._queue_url: str | None = None

    def run(self, stop: threading.Event) -> None:
        log.info("worker started", environment=self._settings.environment)
        while not stop.is_set():
            try:
                self.poll_once()
            except (BotoCoreError, ClientError) as exc:
                # Queue unreachable or refused: back off, keep running, never crash-loop.
                log.error("job queue error", error=type(exc).__name__)
                stop.wait(self._settings.error_backoff_seconds)
        log.info("worker stopped")

    def poll_once(self) -> int:
        """One long poll. Returns the number of messages received."""
        if self._queue_url is None:
            self._queue_url = resolve_queue_url(self._settings, self._client)
        response = self._client.receive_message(
            QueueUrl=self._queue_url,
            MaxNumberOfMessages=self._settings.max_messages,
            WaitTimeSeconds=self._settings.poll_wait_seconds,
        )
        messages = response.get("Messages", [])
        for message in messages:
            self._handle(message)
        return len(messages)

    def _handle(self, message: Mapping[str, Any]) -> None:
        message_id = str(message.get("MessageId", ""))
        bind_log_context(request_id=message_id or None)
        try:
            try:
                job = parse(str(message.get("Body", "")))
            except MalformedJob as exc:
                log.warning(
                    "malformed job message left on queue", message_id=message_id, reason=str(exc)
                )
                return
            outcome = dispatch(job, self._handlers)
            if outcome is Outcome.UNKNOWN_TYPE:
                log.warning(
                    "no handler for job type; left on queue",
                    job_type=job.type,
                    job_id=str(job.job_id),
                    message_id=message_id,
                )
                return
            self._client.delete_message(
                QueueUrl=self._queue_url, ReceiptHandle=message["ReceiptHandle"]
            )
            log.info("job done", job_type=job.type, job_id=str(job.job_id))
        finally:
            clear_log_context()


def install_signal_handlers(stop: threading.Event) -> None:
    def _handle(signum: int, _frame: FrameType | None) -> None:
        log.info("shutdown requested", signal=signal.Signals(signum).name)
        stop.set()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)


def main() -> None:
    settings = WorkerSettings()
    configure_logging(settings.service_name, settings.log_level)
    stop = threading.Event()
    install_signal_handlers(stop)
    Worker(settings, sqs_client(settings)).run(stop)


if __name__ == "__main__":
    main()
