import json

import pytest
from pydantic import ValidationError

from lusiform_common import (
    BaseAppSettings,
    bind_log_context,
    clear_log_context,
    configure_logging,
    get_logger,
    redact,
)


def test_settings_read_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    s = BaseAppSettings()
    assert s.environment == "staging"
    assert s.log_level == "DEBUG"


@pytest.mark.parametrize("name", ["dev", "pilot", "production", ""])
def test_unknown_environment_names_are_rejected(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    # Only local (Docker Compose), staging, and prod exist.
    monkeypatch.setenv("ENVIRONMENT", name)
    with pytest.raises(ValidationError):
        BaseAppSettings()


def test_log_line_has_context_and_redacts(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("api", "INFO")
    bind_log_context(request_id="r1", partner_id="p1", user_id="u1", project_id="pr1")
    get_logger().info("hello", password="hunter2", notes="customer free text", ok=1)
    line = json.loads(capsys.readouterr().out.strip())
    assert line["request_id"] == "r1"
    assert line["partner_id"] == "p1"
    assert line["service"] == "api"
    assert line["message"] == "hello"
    assert line["ok"] == 1
    assert line["password"] == "[REDACTED]"
    assert line["notes"] == "[REDACTED]"
    clear_log_context()


def test_redact_nested() -> None:
    out = redact({"a": {"token": "x", "b": [{"external_id": "y", "c": 1}]}})
    assert out == {"a": {"token": "[REDACTED]", "b": [{"external_id": "[REDACTED]", "c": 1}]}}


@pytest.mark.parametrize(
    "key",
    [
        "Authorization",
        "access_token",
        "client_secret",
        "db_password",
        "aws_credentials",
        "X-Api-Key",
        "session_id",
        "Cookie",
        "external_id",
        "private_key",
        "notes",
        "intake",
        "answers",
        "prompt",
    ],
)
def test_redacts_sensitive_and_free_text_keys(key: str) -> None:
    assert redact({key: "value"}) == {key: "[REDACTED]"}


def test_redact_keeps_safe_keys_and_tuples() -> None:
    out = redact({"path": "/api/health", "items": ({"token": "t", "n": 1},)})
    assert out == {"path": "/api/health", "items": [{"token": "[REDACTED]", "n": 1}]}


def test_exception_text_is_not_a_bypass_for_top_level_keys(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("api", "INFO")
    get_logger().info("evt", authorization="Bearer abc", intake_text="free text", status=200)
    line = json.loads(capsys.readouterr().out.strip())
    assert line["authorization"] == "[REDACTED]"
    assert line["intake_text"] == "[REDACTED]"
    assert line["status"] == 200
    assert "abc" not in json.dumps(line)
    assert "free text" not in json.dumps(line)


def test_bind_rejects_unknown_key() -> None:
    with pytest.raises(ValueError):
        bind_log_context(intake="x")
