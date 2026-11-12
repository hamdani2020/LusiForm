"""Run the validators on a rendered project and read their output. TEST ONLY.

These mirror what the validation spec's worker will run, with the same flags where they are
known: `terraform fmt -check`, `terraform init -backend=false` then `validate`, `tflint` with
the AWS ruleset, and `checkov --skip-download`. Nothing contacts AWS.

tflint runs with `--recursive`. Run from the project root with only `--call-module-type=local`,
tflint does NOT inspect the resources inside the modules: an invalid instance class written
into a module passed cleanly. `--recursive` analyses the root and every module directory.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tf_runner import env as terraform_env

TFLINT_TIMEOUT = 120
CHECKOV_TIMEOUT = 300


@dataclass(frozen=True)
class TflintResult:
    exit_code: int
    issues: list[dict[str, Any]]
    errors: list[dict[str, Any]]

    @property
    def blocking(self) -> list[dict[str, Any]]:
        """Findings at error level. Warnings and notices are reported but do not block."""
        return [i for i in self.issues if i["rule"]["severity"] == "error"]


@dataclass(frozen=True)
class CheckovResult:
    exit_code: int
    summary: dict[str, Any]
    passed: list[dict[str, Any]]
    failed: list[dict[str, Any]]

    @property
    def passed_ids(self) -> set[str]:
        return {c["check_id"] for c in self.passed}

    @property
    def failed_ids(self) -> set[str]:
        return {c["check_id"] for c in self.failed}


def run_tflint(config: Path, project: Path) -> TflintResult:
    result = subprocess.run(  # noqa: S603
        [  # noqa: S607
            "tflint",
            "--config",
            str(config),
            "--chdir",
            str(project),
            "--recursive",
            "--call-module-type=local",
            "--format",
            "json",
        ],
        env=terraform_env(),
        capture_output=True,
        text=True,
        timeout=TFLINT_TIMEOUT,
        check=False,
    )
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise AssertionError(
            f"tflint printed no JSON (exit {result.returncode}):\n{result.stdout}\n{result.stderr}"
        ) from error
    return TflintResult(result.returncode, data["issues"], data["errors"])


def run_checkov(project: Path) -> CheckovResult:
    environment = dict(os.environ)
    # Checkov must never reach a platform: no API key, no downloads.
    for name in ("BC_API_KEY", "PRISMA_API_URL", "CKV_API_KEY"):
        environment.pop(name, None)
    result = subprocess.run(  # noqa: S603
        [  # noqa: S607
            "checkov",
            "-d",
            str(project),
            "--framework",
            "terraform",
            "--skip-download",
            "--compact",
            "-o",
            "json",
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=CHECKOV_TIMEOUT,
        check=False,
    )
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise AssertionError(
            f"checkov printed no JSON (exit {result.returncode}):\n"
            f"{result.stdout[:500]}\n{result.stderr[-1500:]}"
        ) from error
    report = data[0] if isinstance(data, list) else data
    return CheckovResult(
        result.returncode,
        report["summary"],
        report["results"]["passed_checks"],
        report["results"]["failed_checks"],
    )


def blocking_checks(result: CheckovResult, accepted: dict[str, dict[str, Any]]) -> set[str]:
    """Failing Checkov checks that block: anything not accepted as LOW or MEDIUM.

    This is the validation spec's fail-closed rule: a failing check missing from the severity
    map is HIGH.
    """
    return {
        check_id
        for check_id in result.failed_ids
        if accepted.get(check_id, {}).get("severity") not in {"LOW", "MEDIUM"}
    }
