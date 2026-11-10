"""The worker has no access path to the API's data package or any database (security.md)."""

import ast
import importlib.util
import tomllib
from pathlib import Path

WORKER_DIR = Path(__file__).resolve().parents[1]

FORBIDDEN_MODULES = (
    "sqlalchemy",
    "psycopg",
    "psycopg2",
    "asyncpg",
    "alembic",
    "app.data",  # the API's repository/data package
    "app.deps",
    "app.context",
)


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
    return names


def _under(name: str, root: str) -> bool:
    return name == root or name.startswith(root + ".")


def test_worker_code_imports_nothing_from_the_api_data_layer_or_a_database() -> None:
    files = sorted((WORKER_DIR / "app").rglob("*.py"))
    assert files, "no worker sources found"
    offenders = sorted(
        f"{f.relative_to(WORKER_DIR)}: {name}"
        for f in files
        for name in _imports(f)
        if any(_under(name, root) for root in FORBIDDEN_MODULES)
    )
    assert offenders == []


def test_worker_package_has_no_data_package() -> None:
    assert not (WORKER_DIR / "app" / "data").exists()


def test_worker_dependencies_exclude_database_libraries() -> None:
    project = tomllib.loads((WORKER_DIR / "pyproject.toml").read_text())
    deps = [d.lower() for d in project["project"]["dependencies"]]
    banned = ("sqlalchemy", "psycopg", "asyncpg", "alembic", "lusiform-api")
    assert not [d for d in deps if d.startswith(banned)]
    # And the API package is not a path dependency either.
    sources = project.get("tool", {}).get("uv", {}).get("sources", {})
    assert set(sources) <= {"lusiform-common"}


def test_database_libraries_are_not_installed_in_the_worker_environment() -> None:
    for module in ("sqlalchemy", "psycopg", "alembic"):
        assert importlib.util.find_spec(module) is None, module
