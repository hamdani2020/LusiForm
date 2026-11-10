"""Worker loop: config, polling a stubbed queue, unknown jobs, errors, clean shutdown."""

import json
import os
import signal
import threading
import time
import uuid
from collections.abc import Mapping
from typing import Any

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from lusiform_common import configure_logging
from pydantic import ValidationError

from app import main as worker_main
from app.config import WorkerSettings
from app.jobs import Job, MalformedJob, parse
from app.main import Worker, install_signal_handlers

QUEUE_URL = "http://localstack:4566/queue/lusiform-jobs-local"


class FakeQueue:
    """Stub SQS client. Serves queued batches, then empty polls; records every call."""

    def __init__(self, batches: list[list[dict[str, Any]]] | None = None) -> None:
        self.batches = list(batches or [])
        self.receives: list[dict[str, Any]] = []
        self.deletes: list[dict[str, Any]] = []
        self.url_lookups: list[dict[str, Any]] = []
        self.errors: list[Exception] = []
        self.on_receive: Any = None

    def receive_message(self, **kwargs: Any) -> Mapping[str, Any]:
        self.receives.append(kwargs)
        if self.on_receive:
            self.on_receive()
        if self.errors:
            raise self.errors.pop(0)
        return {"Messages": self.batches.pop(0)} if self.batches else {}

    def delete_message(self, **kwargs: Any) -> None:
        self.deletes.append(kwargs)

    def get_queue_url(self, **kwargs: Any) -> Mapping[str, Any]:
        self.url_lookups.append(kwargs)
        return {"QueueUrl": QUEUE_URL}


def message(body: str, n: int = 1) -> dict[str, Any]:
    return {"MessageId": f"m-{n}", "ReceiptHandle": f"rh-{n}", "Body": body}


def job_body(job_type: str = "generate", **extra: Any) -> str:
    return json.dumps({"type": job_type, "job_id": str(uuid.uuid4()), **extra})


def settings(**overrides: Any) -> WorkerSettings:
    values: dict[str, Any] = {
        "job_queue_url": QUEUE_URL,
        "poll_wait_seconds": 0,
        "error_backoff_seconds": 0.01,
    }
    values.update(overrides)
    return WorkerSettings(**values)


def log_lines(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.splitlines() if line.startswith("{")]


@pytest.fixture(autouse=True)
def _json_logs() -> None:
    configure_logging("lusiform-worker", "INFO")


# --- config ---


def test_reads_config_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOB_QUEUE_NAME", "lusiform-jobs-local")
    monkeypatch.setenv("ARTIFACT_BUCKET", "lusiform-artifacts-local")
    monkeypatch.setenv("POLL_WAIT_SECONDS", "10")
    monkeypatch.setenv("ENVIRONMENT", "staging")
    s = WorkerSettings()
    assert s.service_name == "lusiform-worker"
    assert s.job_queue_name == "lusiform-jobs-local"
    assert s.artifact_bucket == "lusiform-artifacts-local"
    assert s.poll_wait_seconds == 10
    assert s.environment == "staging"


def test_queue_must_be_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JOB_QUEUE_URL", raising=False)
    monkeypatch.delenv("JOB_QUEUE_NAME", raising=False)
    with pytest.raises(ValidationError, match="JOB_QUEUE_URL or JOB_QUEUE_NAME"):
        WorkerSettings()


@pytest.mark.parametrize("wait", [-1, 21])
def test_long_poll_wait_is_bounded_by_sqs_limits(wait: int) -> None:
    with pytest.raises(ValidationError):
        settings(poll_wait_seconds=wait)


def test_worker_has_no_database_setting() -> None:
    fields = set(WorkerSettings.model_fields)
    assert not {f for f in fields if "database" in f or "db_" in f or f.startswith("db")}


# --- polling ---


def test_polls_the_queue_with_long_polling() -> None:
    queue = FakeQueue()
    Worker(settings(poll_wait_seconds=20, max_messages=5), queue).poll_once()
    assert queue.receives == [
        {"QueueUrl": QUEUE_URL, "MaxNumberOfMessages": 5, "WaitTimeSeconds": 20}
    ]


def test_resolves_the_queue_url_from_its_name_once() -> None:
    queue = FakeQueue()
    worker = Worker(settings(job_queue_url=None, job_queue_name="lusiform-jobs-local"), queue)
    worker.poll_once()
    worker.poll_once()
    assert queue.url_lookups == [{"QueueName": "lusiform-jobs-local"}]
    assert [r["QueueUrl"] for r in queue.receives] == [QUEUE_URL, QUEUE_URL]


def test_unknown_job_type_is_logged_and_left_on_the_queue(
    capsys: pytest.CaptureFixture[str],
) -> None:
    body = job_body("generate", intake={"notes": "customer secret plans"})
    queue = FakeQueue([[message(body)]])
    assert Worker(settings(), queue).poll_once() == 1

    assert queue.deletes == []  # left for a later spec's handler (or the DLQ)
    entry = next(x for x in log_lines(capsys) if x["message"].startswith("no handler"))
    assert entry["job_type"] == "generate"
    assert entry["job_id"] == json.loads(body)["job_id"]
    assert entry["message_id"] == "m-1"
    assert entry["request_id"] == "m-1"
    assert entry["level"] == "warning"


@pytest.mark.parametrize(
    "body",
    [
        "not json",
        "[1, 2]",
        json.dumps({"job_id": str(uuid.uuid4())}),
        json.dumps({"type": "generate", "job_id": "nope"}),
        "",
    ],
)
def test_malformed_messages_are_logged_and_left(
    body: str, capsys: pytest.CaptureFixture[str]
) -> None:
    queue = FakeQueue([[message(body)]])
    Worker(settings(), queue).poll_once()
    assert queue.deletes == []
    assert any(x["message"].startswith("malformed job") for x in log_lines(capsys))


def test_message_bodies_never_reach_the_logs(capsys: pytest.CaptureFixture[str]) -> None:
    secret = "customer free text about their secret launch"
    queue = FakeQueue([[message(job_body("generate", notes=secret)), message(f"{secret} {{", 2)]])
    Worker(settings(), queue).poll_once()
    assert secret not in capsys.readouterr().out


def test_handled_job_is_deleted() -> None:
    seen: list[Job] = []
    queue = FakeQueue([[message(job_body("echo"))]])
    Worker(settings(), queue, handlers={"echo": seen.append}).poll_once()
    assert [j.type for j in seen] == ["echo"]
    assert queue.deletes == [{"QueueUrl": QUEUE_URL, "ReceiptHandle": "rh-1"}]


def test_log_context_is_cleared_between_messages(capsys: pytest.CaptureFixture[str]) -> None:
    queue = FakeQueue([[message(job_body(), 1), message(job_body(), 2)]])
    worker = Worker(settings(), queue)
    worker.poll_once()
    worker_main.log.info("after")
    lines = log_lines(capsys)
    assert [x["request_id"] for x in lines if x["message"].startswith("no handler")] == [
        "m-1",
        "m-2",
    ]
    assert "request_id" not in next(x for x in lines if x["message"] == "after")


def test_parse_reads_the_envelope() -> None:
    job_id = uuid.uuid4()
    job = parse(json.dumps({"type": "validate", "job_id": str(job_id), "x": 1}))
    assert (job.type, job.job_id, job.payload["x"]) == ("validate", job_id, 1)
    with pytest.raises(MalformedJob):
        parse(json.dumps({"type": "", "job_id": str(job_id)}))


# --- errors and shutdown ---


def test_queue_errors_back_off_and_do_not_stop_the_worker(
    capsys: pytest.CaptureFixture[str],
) -> None:
    queue = FakeQueue()
    queue.errors = [
        EndpointConnectionError(endpoint_url=QUEUE_URL),
        ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "ReceiveMessage"),
    ]
    stop = threading.Event()

    def stop_after_three() -> None:
        if len(queue.receives) >= 3:
            stop.set()

    queue.on_receive = stop_after_three
    Worker(settings(), queue).run(stop)

    assert len(queue.receives) == 3  # kept polling after both errors
    errors = [x for x in log_lines(capsys) if x["message"] == "job queue error"]
    assert [x["error"] for x in errors] == ["EndpointConnectionError", "ClientError"]


def test_starts_and_stops_cleanly(capsys: pytest.CaptureFixture[str]) -> None:
    queue = FakeQueue()
    stop = threading.Event()
    thread = threading.Thread(target=Worker(settings(), queue).run, args=(stop,))
    thread.start()
    time.sleep(0.05)
    stop.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
    messages = [x["message"] for x in log_lines(capsys)]
    assert messages[0] == "worker started"
    assert messages[-1] == "worker stopped"
    assert queue.receives  # it really polled


def test_sigterm_requests_a_clean_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    installed: dict[int, Any] = {}
    monkeypatch.setattr(signal, "signal", lambda sig, fn: installed.__setitem__(sig, fn))
    stop = threading.Event()
    install_signal_handlers(stop)
    assert set(installed) == {signal.SIGTERM, signal.SIGINT}
    installed[signal.SIGTERM](signal.SIGTERM, None)
    assert stop.is_set()


def test_main_wires_settings_client_and_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOB_QUEUE_URL", QUEUE_URL)
    queue = FakeQueue()
    monkeypatch.setattr(worker_main, "sqs_client", lambda _s: queue)
    monkeypatch.setattr(worker_main, "install_signal_handlers", lambda stop: stop.set())
    worker_main.main()  # returns because the stop flag is already set
    assert os.environ["JOB_QUEUE_URL"] == QUEUE_URL
