import pytest

from app.config import ApiSettings


def test_settings_load_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:pw@db/x")
    s = ApiSettings()
    assert s.environment == "staging"
    assert s.database_url is not None
    assert s.database_url.get_secret_value().endswith("@db/x")


def test_database_url_not_exposed_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:hunter2@db/x")
    assert "hunter2" not in repr(ApiSettings())


def test_no_secret_default() -> None:
    assert ApiSettings.model_fields["database_url"].default is None
