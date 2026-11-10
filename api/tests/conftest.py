"""Shared fixtures. DB tests use a throwaway database on the compose `db` Postgres."""

import os
import uuid
from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from tests.dbutil import alembic_config


@pytest.fixture
def scratch_db_url(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Create an empty disposable database, point DATABASE_URL at it, drop it afterwards."""
    base = os.environ.get("DATABASE_URL")
    if not base:
        pytest.fail("DATABASE_URL is not set; run DB tests via docker compose (db must be up)")
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    name = f"lusiform_test_{uuid.uuid4().hex}"  # generated, never user input
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    except OperationalError as exc:
        admin.dispose()
        pytest.fail(f"cannot reach Postgres (is the compose db up?): {exc}")
    url = make_url(base).set(database=name).render_as_string(hide_password=False)
    monkeypatch.setenv("DATABASE_URL", url)
    try:
        yield url
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def migrated_engine(scratch_db_url: str) -> Iterator[Engine]:
    """A scratch database migrated to head."""
    command.upgrade(alembic_config(), "head")
    engine = create_engine(scratch_db_url)
    try:
        yield engine
    finally:
        engine.dispose()
