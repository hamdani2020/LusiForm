import json

import pytest

from lusiform_common import (
    BaseAppSettings,
    bind_log_context,
    clear_log_context,
    configure_logging,
    get_logger,
    redact,
)


def test_settings_read_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    s = BaseAppSettings()
    assert s.environment == "dev"
    assert s.log_level == "DEBUG"


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


def test_bind_rejects_unknown_key() -> None:
    with pytest.raises(ValueError):
        bind_log_context(intake="x")
