"""Tenant-access lint guard: it flags violations, allows the repository, and the code is clean."""

import re
from pathlib import Path

import pytest

from tools.check_tenant_access import (
    ALLOWED_PREFIXES,
    check_paths,
    check_source,
    main,
)

API_DIR = Path(__file__).resolve().parents[1]
FIXTURE = API_DIR / "tests" / "fixtures" / "tenant_guard" / "leaky_handler.py.txt"
OUTSIDE = "app/routers/leaky.py"  # a path outside the repository package


def rules(source: str, path: str = OUTSIDE) -> list[str]:
    return [v.rule for v in check_source(source, path)]


# --- the deliberate-violation fixture ---


def test_fixture_violations_are_all_flagged_on_the_marked_lines() -> None:
    source = FIXTURE.read_text()
    expected = {
        (i, m.group(1))
        for i, line in enumerate(source.splitlines(), start=1)
        if (m := re.search(r"# VIOLATION (\S+)", line))
    }
    assert len(expected) == 4  # guard against the fixture being edited into nothing
    found = {(v.line, v.rule) for v in check_source(source, OUTSIDE)}
    assert found == expected


def test_same_fixture_is_allowed_inside_the_repository_package_and_migrations() -> None:
    source = FIXTURE.read_text()
    assert check_source(source, "app/data/anything.py") == []
    assert check_source(source, "app/data/models/project.py") == []
    assert check_source(source, "migrations/versions/0002_x.py") == []
    assert ALLOWED_PREFIXES == ("app/data/", "migrations/")


# --- rule matrix: each form of bypass is caught ---


@pytest.mark.parametrize(
    ("source", "rule"),
    [
        ("import sqlalchemy", "database-import"),
        ("import sqlalchemy.orm", "database-import"),
        ("from sqlalchemy import select", "database-import"),
        ("from sqlalchemy.orm import Session, sessionmaker", "database-import"),
        ("from sqlalchemy import create_engine, exc", "database-import"),
        ("from sqlalchemy.ext.asyncio import AsyncSession", "database-import"),
        ("import psycopg", "database-import"),
        ("import psycopg2", "database-import"),
        ("from psycopg import connect", "database-import"),
        ("import asyncpg", "database-import"),
        ("import sqlite3", "database-import"),
        ("from app.data.models import Project", "orm-models-import"),
        ("from app.data.models.tenant import User", "orm-models-import"),
        ("import app.data.models", "orm-models-import"),
        ("import app.data.models.versions as v", "orm-models-import"),
        ("from app.data import models", "orm-models-import"),
        ("from app.data import models as m", "orm-models-import"),
        ("from ..data.models import Project", "orm-models-import"),
        ("from ..data import models", "orm-models-import"),
        ("import app.data\nx = app.data.models.Project", "orm-models-import"),
        ("from app import data\nx = data.models.Project", "orm-models-import"),
        ("session.execute(stmt)", "sql-execution"),
        ("conn.executemany(stmt, rows)", "sql-execution"),
        ("conn.exec_driver_sql('select 1')", "sql-execution"),
        ("db.scalars(stmt)", "sql-execution"),
        ("session.query(Project)", "sql-execution"),
        ("repo._session.execute(stmt)", "sql-execution"),
        ("__import__('sqlalchemy')", "database-import"),
        ("import importlib\nimportlib.import_module('sqlalchemy.orm')", "database-import"),
        ("import importlib\nimportlib.import_module('app.data.models')", "orm-models-import"),
    ],
)
def test_bypass_forms_are_flagged(source: str, rule: str) -> None:
    assert rule in rules(source), source


@pytest.mark.parametrize(
    "source",
    [
        "from app.data.database import Database",
        "from app.data.database import TenantRepositories",
        "from app.context import RequestContext",
        "from app.enums import Role",
        "from app.errors import NotFound",
        "from sqlalchemy.exc import IntegrityError",
        "from sqlalchemy import exc",
        "import sqlalchemy.exc",
        "from fastapi import Depends",
        "with db.tenant(ctx) as repos:\n    repos.projects.get(project_id)",
        "import importlib\nimportlib.import_module('json')",
        "__import__('os')",
        "x = models.Project",  # a bare local name is not the ORM models package
    ],
)
def test_legitimate_code_is_not_flagged(source: str) -> None:
    assert rules(source) == [], source


def test_relative_import_inside_a_package_resolves_correctly() -> None:
    assert rules("from .data.models import Project", "app/service.py") == ["orm-models-import"]
    assert rules("from . import models", "app/data/__init__.py") == []  # allowlisted
    assert rules("from .models import Project", "app/routers/x.py") == []  # app.routers.models


def test_violation_message_points_to_the_fix() -> None:
    (v,) = check_source("session.execute(stmt)", OUTSIDE)
    assert v.path == OUTSIDE
    assert v.line == 1
    assert "repository" in v.message
    assert str(v).startswith(f"{OUTSIDE}:1:")


# --- the real codebase ---


def test_real_codebase_is_clean() -> None:
    violations, scanned = check_paths([API_DIR / "app", API_DIR / "migrations"], API_DIR)
    assert [str(v) for v in violations] == []
    assert scanned > 20  # not vacuous: it really looked at the application code


def test_scan_covers_the_files_that_matter() -> None:
    _, scanned = check_paths([API_DIR / "app"], API_DIR)
    names = {p.relative_to(API_DIR).as_posix() for p in (API_DIR / "app").rglob("*.py")}
    assert {"app/deps.py", "app/routers/me.py", "app/routers/admin.py", "app/audit.py"} <= names
    assert scanned == len(names)


def test_audit_helper_is_reachable_without_importing_models() -> None:
    # app/audit.py is a thin re-export; the implementation lives in the data package.
    assert check_source((API_DIR / "app" / "audit.py").read_text(), "app/audit.py") == []


# --- CLI behaviour ---


def _project(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)
    return tmp_path


def test_cli_fails_on_a_violation_and_names_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _project(
        tmp_path,
        {
            "app/routers/bad.py": FIXTURE.read_text(),
            "app/data/ok.py": "from sqlalchemy import select\n",
        },
    )
    assert main(["app"], root=root) == 1
    out = capsys.readouterr()
    assert "app/routers/bad.py" in out.out
    assert "app/data/ok.py" not in out.out
    assert "FAILED" in out.err


def test_cli_passes_on_clean_code(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _project(tmp_path, {"app/routers/fine.py": "from app.data.database import Database\n"})
    assert main(["app"], root=root) == 0
    assert "OK" in capsys.readouterr().out


def test_cli_does_not_pass_vacuously(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()
    assert main(["app"], root=tmp_path) == 2  # nothing scanned
    assert main(["nope"], root=tmp_path) == 2  # path missing
