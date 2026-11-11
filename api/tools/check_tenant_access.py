"""Tenant-access lint guard (foundation task 8, Requirement 4.5).

Fails the build when code outside the repository package (`app/data/`) touches the
database or the ORM models directly. All tenant data must go through a repository,
which applies `partner_id` (see `app/data/base.py`).

Flagged outside the allowlist:

  imports          the ORM models (`app.data.models`), `sqlalchemy` (except
                   `sqlalchemy.exc`, exception types only) and raw database drivers
  execution        calls to `.execute()`, `.executemany()`, `.exec_driver_sql()`,
                   `.scalars()` and `.query()`, which is how a session, connection
                   or driver runs SQL
  dynamic imports  `__import__("sqlalchemy")` / `importlib.import_module(...)` of the above

Allowlist: `app/data/` (the repository package) and `migrations/`. There is no
per-line escape hatch on purpose. To reach data, add a repository method.

Scope: this scans application code (default: `app/`). Tests are not scanned; they
need sessions and models to build fixtures and prove the layer.

Usage (from `api/`):  python -m tools.check_tenant_access [paths...]   (default: app)
"""

import ast
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

ALLOWED_PREFIXES: tuple[str, ...] = ("app/data/", "migrations/")

MODELS_MODULE = "app.data.models"

# Importing any of these outside the allowlist is a violation.
FORBIDDEN_IMPORT_ROOTS: tuple[str, ...] = (
    "sqlalchemy",
    "psycopg",
    "psycopg2",
    "psycopg_pool",
    "asyncpg",
    "pg8000",
    "sqlite3",
    "aiosqlite",
)
ALLOWED_IMPORTS: frozenset[str] = frozenset({"sqlalchemy.exc"})

EXECUTION_ATTRS: frozenset[str] = frozenset(
    {"execute", "executemany", "exec_driver_sql", "scalars", "query"}
)

HOW_TO_FIX = "go through a repository (Database.tenant(ctx) / Database.operator(ctx))"


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    rule: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: [{self.rule}] {self.message}"


def is_allowlisted(rel_path: str) -> bool:
    return rel_path.startswith(ALLOWED_PREFIXES)


def _module_name(rel_path: str) -> tuple[str, str]:
    """(dotted module name, package used to resolve relative imports)."""
    parts = Path(rel_path).with_suffix("").parts
    is_init = parts[-1] == "__init__"
    pkg_parts = parts[:-1] if is_init else parts[:-1]
    module_parts = parts[:-1] if is_init else parts
    return ".".join(module_parts), ".".join(pkg_parts)


def _resolve(module: str | None, level: int, package: str) -> str:
    if level == 0:
        return module or ""
    base = package.split(".") if package else []
    base = base[: len(base) - (level - 1)] if level > 1 else base
    return ".".join([*base, *([module] if module else [])])


def _is_under(name: str, root: str) -> bool:
    return name == root or name.startswith(root + ".")


def _forbidden_import(name: str) -> str | None:
    """Return the rule name if importing `name` is forbidden, else None."""
    if name in ALLOWED_IMPORTS or any(_is_under(name, ok) for ok in ALLOWED_IMPORTS):
        return None
    if _is_under(name, MODELS_MODULE):
        return "orm-models-import"
    if any(_is_under(name, root) for root in FORBIDDEN_IMPORT_ROOTS):
        return "database-import"
    return None


def _dotted(node: ast.AST) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


class _Visitor(ast.NodeVisitor):
    def __init__(self, rel_path: str, package: str) -> None:
        self.rel_path = rel_path
        self.package = package
        self.violations: list[Violation] = []

    def _add(self, node: ast.AST, rule: str, message: str) -> None:
        self.violations.append(
            Violation(self.rel_path, getattr(node, "lineno", 0), rule, f"{message}; {HOW_TO_FIX}")
        )

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            rule = _forbidden_import(alias.name)
            if rule:
                self._add(node, rule, f"import of {alias.name!r} outside the repository package")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = _resolve(node.module, node.level, self.package)
        rule = _forbidden_import(module)
        if rule:
            # `from sqlalchemy import exc` stays allowed; anything else from sqlalchemy is not.
            only_exc = module == "sqlalchemy" and all(a.name == "exc" for a in node.names)
            if not only_exc:
                self._add(node, rule, f"import from {module!r} outside the repository package")
        else:
            # `from app.data import models`: the module is fine, the imported name is not.
            for alias in node.names:
                full = f"{module}.{alias.name}" if module else alias.name
                sub = _forbidden_import(full)
                if sub:
                    self._add(node, sub, f"import of {full!r} outside the repository package")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        dotted = _dotted(node)
        if dotted and (_is_under(dotted, MODELS_MODULE) or dotted.endswith("data.models")):
            self._add(
                node, "orm-models-import", f"use of {dotted!r} outside the repository package"
            )
            return  # do not report the same chain at every prefix
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in EXECUTION_ATTRS:
            self._add(node, "sql-execution", f".{func.attr}() call outside the repository package")
        name = _dotted(func) if isinstance(func, ast.Attribute | ast.Name) else None
        if name and name.rpartition(".")[2] in {"__import__", "import_module"} and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                rule = _forbidden_import(first.value)
                if rule:
                    self._add(node, rule, f"dynamic import of {first.value!r}")
        self.generic_visit(node)


def check_source(source: str, rel_path: str) -> list[Violation]:
    """Check one file's source. `rel_path` is relative to the project root (posix)."""
    if is_allowlisted(rel_path):
        return []
    _module, package = _module_name(rel_path)
    visitor = _Visitor(rel_path, package)
    visitor.visit(ast.parse(source, filename=rel_path))
    return visitor.violations


def python_files(paths: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files.extend(sorted(f for f in p.rglob("*.py") if "__pycache__" not in f.parts))
        elif p.suffix == ".py":
            files.append(p)
    return files


def check_paths(paths: Sequence[Path], root: Path) -> tuple[list[Violation], int]:
    """Check files under `paths`. Returns (violations, number of files scanned)."""
    root = root.resolve()
    violations: list[Violation] = []
    scanned = 0
    for f in python_files(paths):
        rel = f.resolve().relative_to(root).as_posix()
        scanned += 1
        violations.extend(check_source(f.read_text(encoding="utf-8"), rel))
    return violations, scanned


def main(argv: Sequence[str] | None = None, root: Path | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    root = root or Path.cwd()
    targets = [root / a for a in (args or ["app"])]
    missing = [str(t) for t in targets if not t.exists()]
    if missing:
        print(f"tenant-access guard: path not found: {', '.join(missing)}", file=sys.stderr)
        return 2
    violations, scanned = check_paths(targets, root)
    if scanned == 0:
        print("tenant-access guard: no Python files scanned (wrong path?)", file=sys.stderr)
        return 2
    for v in violations:
        print(v)
    if violations:
        print(
            f"\ntenant-access guard FAILED: {len(violations)} violation(s) in {scanned} files. "
            "Tenant data may only be reached through the repository package (app/data/).",
            file=sys.stderr,
        )
        return 1
    print(f"tenant-access guard OK: {scanned} files scanned, no violations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
