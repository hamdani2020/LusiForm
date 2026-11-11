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

import os
import shutil
import subprocess
from pathlib import Path

import pytest

TEMPLATES_ROOT = Path(__file__).resolve().parent.parent
VERSION_DIRS = sorted(p for p in (TEMPLATES_ROOT / "startup").iterdir() if p.is_dir())
MODULES = ["network", "monitoring", "iam", "database", "compute"]

# Providers are downloaded once and reused across modules and runs. Kept inside templates/
# (git-ignored) so it persists through the bind mount in local runs.
PLUGIN_CACHE = TEMPLATES_ROOT / ".tf-plugin-cache"

# Generous: the first init may download the AWS provider (several hundred MB).
INIT_TIMEOUT = 900
RUN_TIMEOUT = 300


def _env() -> dict[str, str]:
    PLUGIN_CACHE.mkdir(exist_ok=True)
    env = dict(os.environ)
    env["TF_PLUGIN_CACHE_DIR"] = str(PLUGIN_CACHE)
    env["TF_IN_AUTOMATION"] = "1"
    env["TF_INPUT"] = "0"
    # Mocked tests never need credentials. Make sure none can leak in and be used.
    for name in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_PROFILE",
    ):
        env.pop(name, None)
    return env


def _terraform(
    args: list[str], cwd: Path, timeout: int = RUN_TIMEOUT
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["terraform", *args],  # noqa: S607
        cwd=cwd,
        env=_env(),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _output(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stdout + result.stderr)[-6000:]


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
        lock = version_dir / "tests" / ".terraform.lock.hcl"
        if lock.is_file():
            shutil.copy(lock, work / ".terraform.lock.hcl")
        init = _terraform(
            ["init", "-backend=false", "-input=false", "-no-color"], work, INIT_TIMEOUT
        )
        assert init.returncode == 0, f"terraform init failed for {module}:\n{_output(init)}"
        cache[key] = work
    return cache[key]


@pytest.mark.parametrize("module", MODULES)
def test_fmt(version_dir: Path, module: str) -> None:
    result = _terraform(
        ["fmt", "-check", "-recursive", "-diff", "-no-color"], version_dir / "modules" / module
    )
    assert result.returncode == 0, f"terraform fmt -check failed for {module}:\n{_output(result)}"


@pytest.mark.parametrize("module", MODULES)
def test_fmt_tests(version_dir: Path, module: str) -> None:
    result = _terraform(
        ["fmt", "-check", "-recursive", "-diff", "-no-color"], version_dir / "tests" / module
    )
    assert result.returncode == 0, (
        f"terraform fmt -check failed for {module} tests:\n{_output(result)}"
    )


@pytest.mark.parametrize("module", MODULES)
def test_validate(
    version_dir: Path,
    module: str,
    workdirs: dict[tuple[str, str], Path],
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    work = _prepared(workdirs, tmp_path_factory, version_dir, module)
    result = _terraform(["validate", "-no-color"], work)
    assert result.returncode == 0, f"terraform validate failed for {module}:\n{_output(result)}"


@pytest.mark.parametrize("module", MODULES)
def test_module_tests(
    version_dir: Path,
    module: str,
    workdirs: dict[tuple[str, str], Path],
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    work = _prepared(workdirs, tmp_path_factory, version_dir, module)
    result = _terraform(["test", "-no-color"], work)
    output = _output(result)
    assert result.returncode == 0, f"terraform test failed for {module}:\n{output}"
    # A green run with nothing executed would look like success.
    assert " 0 passed" not in output, f"no tests ran for {module}:\n{output}"
    assert "Success!" in output, f"unexpected terraform test output for {module}:\n{output}"
