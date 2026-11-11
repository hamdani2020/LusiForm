"""Run Terraform against each template module (startup-template tasks 3 to 7).

For every module: `terraform fmt -check`, `terraform init -backend=false`, `terraform
validate`, then `terraform test` with the mocked-provider tests in
`startup/<version>/tests/<module>/`. Nothing here plans or applies against AWS; the tests
use `mock_provider`, so no credentials are needed.

Each module is copied to a temp directory first, so `.terraform/` and lock files never
land in the template tree. The committed provider lock file pins the exact AWS provider
build and its hashes.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from tf_runner import INIT_TIMEOUT, lock_file, output, terraform

TEMPLATES_ROOT = Path(__file__).resolve().parent.parent
VERSION_DIRS = sorted(p for p in (TEMPLATES_ROOT / "startup").iterdir() if p.is_dir())
MODULES = ["network", "monitoring", "iam", "database", "compute"]


@pytest.fixture(params=VERSION_DIRS, ids=lambda p: p.name)
def version_dir(request: pytest.FixtureRequest) -> Path:
    path: Path = request.param
    return path


@pytest.fixture(scope="module")
def workdirs(tmp_path_factory: pytest.TempPathFactory) -> dict[tuple[str, str], Path]:
    """Initialised copies of each module, shared by the tests below."""
    return {}


def _prepared(
    cache: dict[tuple[str, str], Path],
    tmp_path_factory: pytest.TempPathFactory,
    version_dir: Path,
    module: str,
) -> Path:
    key = (version_dir.name, module)
    if key not in cache:
        work = tmp_path_factory.mktemp(f"{version_dir.name}-{module}") / module
        shutil.copytree(version_dir / "modules" / module, work)
        shutil.copytree(version_dir / "tests" / module, work / "tests")
        lock = lock_file(version_dir)
        if lock.is_file():
            shutil.copy(lock, work / ".terraform.lock.hcl")
        init = terraform(
            ["init", "-backend=false", "-input=false", "-no-color"], work, INIT_TIMEOUT
        )
        assert init.returncode == 0, f"terraform init failed for {module}:\n{output(init)}"
        cache[key] = work
    return cache[key]


@pytest.mark.parametrize("module", MODULES)
def test_fmt(version_dir: Path, module: str) -> None:
    result = terraform(
        ["fmt", "-check", "-recursive", "-diff", "-no-color"], version_dir / "modules" / module
    )
    assert result.returncode == 0, f"terraform fmt -check failed for {module}:\n{output(result)}"


@pytest.mark.parametrize("module", MODULES)
def test_fmt_tests(version_dir: Path, module: str) -> None:
    result = terraform(
        ["fmt", "-check", "-recursive", "-diff", "-no-color"], version_dir / "tests" / module
    )
    assert result.returncode == 0, (
        f"terraform fmt -check failed for {module} tests:\n{output(result)}"
    )


@pytest.mark.parametrize("module", MODULES)
def test_validate(
    version_dir: Path,
    module: str,
    workdirs: dict[tuple[str, str], Path],
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    work = _prepared(workdirs, tmp_path_factory, version_dir, module)
    result = terraform(["validate", "-no-color"], work)
    assert result.returncode == 0, f"terraform validate failed for {module}:\n{output(result)}"


@pytest.mark.parametrize("module", MODULES)
def test_module_tests(
    version_dir: Path,
    module: str,
    workdirs: dict[tuple[str, str], Path],
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    work = _prepared(workdirs, tmp_path_factory, version_dir, module)
    result = terraform(["test", "-no-color"], work)
    text = output(result)
    assert result.returncode == 0, f"terraform test failed for {module}:\n{text}"
    # A green run with nothing executed would look like success.
    assert " 0 passed" not in text, f"no tests ran for {module}:\n{text}"
    assert "Success!" in text, f"unexpected terraform test output for {module}:\n{text}"
