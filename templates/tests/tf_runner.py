"""Shared helpers for running Terraform in the template tests.

Nothing here plans or applies against AWS. Tests use `mock_provider` or `-backend=false`
plus `validate`, so no credentials are needed, and any that are present are removed from
the environment so they cannot be used by accident.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

TEMPLATES_ROOT = Path(__file__).resolve().parent.parent

# Providers are downloaded once and reused across tests and runs. Kept inside templates/
# (git-ignored) so it persists through the bind mount in local runs.
PLUGIN_CACHE = TEMPLATES_ROOT / ".tf-plugin-cache"

# Generous: the first init may download the AWS provider (several hundred MB).
INIT_TIMEOUT = 900
RUN_TIMEOUT = 300


def lock_file(version_dir: Path) -> Path:
    """The committed provider lock file used when tests run `terraform init`."""
    return version_dir / "tests" / ".terraform.lock.hcl"


def env() -> dict[str, str]:
    PLUGIN_CACHE.mkdir(exist_ok=True)
    environment = dict(os.environ)
    environment["TF_PLUGIN_CACHE_DIR"] = str(PLUGIN_CACHE)
    environment["TF_IN_AUTOMATION"] = "1"
    environment["TF_INPUT"] = "0"
    for name in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_PROFILE",
    ):
        environment.pop(name, None)
    return environment


def terraform(
    args: list[str], cwd: Path, timeout: int = RUN_TIMEOUT
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["terraform", *args],  # noqa: S607
        cwd=cwd,
        env=env(),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def output(result: subprocess.CompletedProcess[str]) -> str:
    """The tail of a command's output, for assertion messages."""
    return (result.stdout + result.stderr)[-6000:]
