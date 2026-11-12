"""Shared fixtures: each template fixture is rendered and initialised once per test session."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fixtures import Fixture, load_fixtures, render_fixture
from reference_render import write_project
from tf_runner import INIT_TIMEOUT, lock_file, output, terraform
from validators import CheckovResult, TflintResult, run_checkov, run_tflint

ProjectFactory = Callable[[Path, str], Path]
ResultFactory = Callable[[Path, str], Any]


@pytest.fixture(scope="session")
def rendered_factory(tmp_path_factory: pytest.TempPathFactory) -> ProjectFactory:
    """Return `(version_dir, fixture_name) -> directory` holding a freshly rendered project.

    Unlike `project_factory` this does not run `terraform init`, so the directory contains
    only rendered files. Treat it as read-only.
    """
    cache: dict[tuple[str, str], Path] = {}

    def get(version_dir: Path, name: str) -> Path:
        key = (version_dir.name, name)
        if key not in cache:
            fixture = load_fixtures(version_dir)[name]
            work = tmp_path_factory.mktemp(f"render-{version_dir.name}-{name}")
            write_project(render_fixture(version_dir, fixture), work)
            cache[key] = work
        return cache[key]

    return get


@pytest.fixture(scope="session")
def checkov_results(rendered_factory: ProjectFactory) -> ResultFactory:
    """Return `(version_dir, fixture_name) -> CheckovResult`, running Checkov once per fixture."""
    cache: dict[tuple[str, str], CheckovResult] = {}

    def get(version_dir: Path, name: str) -> CheckovResult:
        key = (version_dir.name, name)
        if key not in cache:
            cache[key] = run_checkov(rendered_factory(version_dir, name))
        return cache[key]

    return get


@pytest.fixture(scope="session")
def tflint_results(project_factory: ProjectFactory) -> ResultFactory:
    """Return `(version_dir, fixture_name) -> TflintResult`, running tflint once per fixture."""
    cache: dict[tuple[str, str], TflintResult] = {}

    def get(version_dir: Path, name: str) -> TflintResult:
        key = (version_dir.name, name)
        if key not in cache:
            cache[key] = run_tflint(version_dir / "tflint.hcl", project_factory(version_dir, name))
        return cache[key]

    return get


@pytest.fixture(scope="session")
def project_factory(tmp_path_factory: pytest.TempPathFactory) -> ProjectFactory:
    """Return a function `(version_dir, fixture_name) -> initialised project directory`.

    The project is rendered from the fixture, the committed provider lock file is copied in,
    and `terraform init -backend=false` is run, so validators can use it straight away. The
    directory is shared across tests, which must treat it as read-only.
    """
    cache: dict[tuple[str, str], Path] = {}

    def get(version_dir: Path, name: str) -> Path:
        key = (version_dir.name, name)
        if key not in cache:
            fixture: Fixture = load_fixtures(version_dir)[name]
            work = tmp_path_factory.mktemp(f"{version_dir.name}-{name}")
            write_project(render_fixture(version_dir, fixture), work)
            lock = lock_file(version_dir)
            if lock.is_file():
                shutil.copy(lock, work / ".terraform.lock.hcl")
            init = terraform(
                ["init", "-backend=false", "-input=false", "-no-color"], work, INIT_TIMEOUT
            )
            assert init.returncode == 0, f"terraform init failed for {name}:\n{output(init)}"
            cache[key] = work
        return cache[key]

    return get
