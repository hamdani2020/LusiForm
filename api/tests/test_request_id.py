import json
import re

import pytest
from fastapi.testclient import TestClient

from app.main import app

_HEX32 = re.compile(r"^[0-9a-f]{32}$")


def test_response_carries_generated_request_id() -> None:
    response = TestClient(app).get("/api/health")
    assert _HEX32.match(response.headers["X-Request-ID"])


def test_request_ids_are_unique_per_request() -> None:
    client = TestClient(app)
    ids = {client.get("/api/health").headers["X-Request-ID"] for _ in range(5)}
    assert len(ids) == 5


def test_client_supplied_request_id_is_ignored() -> None:
    response = TestClient(app).get("/api/health", headers={"X-Request-ID": "evil\nline"})
    assert response.headers["X-Request-ID"] != "evil\nline"
    assert _HEX32.match(response.headers["X-Request-ID"])


def test_access_log_is_json_with_request_id(capsys: pytest.CaptureFixture[str]) -> None:
    response = TestClient(app).get("/api/health")
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")]
    entry = next(x for x in lines if x["message"] == "request")
    assert entry["request_id"] == response.headers["X-Request-ID"]
    assert entry["path"] == "/api/health"
    assert entry["status"] == 200
    assert entry["service"] == "lusiform-api"
