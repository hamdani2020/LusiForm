"""The deliberately insecure fixture (startup-template task 10.3).

`fixtures/insecure/` breaks three rules on purpose. A gate that has never failed proves
nothing, so this shows Checkov fails it, on the checks that matter, and that the same
fail-closed rule that passes the template blocks this project.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fixtures import VERSION_DIRS, load_fixtures, render_fixture
from tf_runner import output, terraform
from validators import CheckovResult, blocking_checks, run_checkov

# The checks each deliberate violation must trip.
UNENCRYPTED_DATABASE = {"CKV_AWS_16"}
PUBLIC_DATABASE = {"CKV_AWS_17"}
WILDCARD_IAM = {"CKV_AWS_62", "CKV_AWS_63", "CKV_AWS_355", "CKV2_AWS_40"}
OPEN_SSH = {"CKV_AWS_24"}


@pytest.fixture(params=VERSION_DIRS, ids=lambda p: p.name)
def version_dir(request: pytest.FixtureRequest) -> Path:
    path: Path = request.param
    return path


@pytest.fixture(scope="module")
def results() -> dict[str, CheckovResult]:
    return {}


def _result(version_dir: Path, cache: dict[str, CheckovResult]) -> CheckovResult:
    if version_dir.name not in cache:
        cache[version_dir.name] = run_checkov(version_dir / "fixtures" / "insecure")
    return cache[version_dir.name]


def _accepted(version_dir: Path) -> dict[str, Any]:
    accepted: dict[str, Any] = json.loads(
        (version_dir / "fixtures" / "checkov-accepted.json").read_text()
    )["accepted"]
    return accepted


def test_checkov_fails_the_insecure_project(
    version_dir: Path, results: dict[str, CheckovResult]
) -> None:
    result = _result(version_dir, results)
    assert result.exit_code != 0
    assert result.summary["failed"] > 0
    assert result.summary["parsing_errors"] == 0


def test_the_unencrypted_database_is_caught(
    version_dir: Path, results: dict[str, CheckovResult]
) -> None:
    assert _result(version_dir, results).failed_ids >= UNENCRYPTED_DATABASE


def test_the_public_database_is_caught(
    version_dir: Path, results: dict[str, CheckovResult]
) -> None:
    assert _result(version_dir, results).failed_ids >= PUBLIC_DATABASE


def test_the_wildcard_iam_policy_is_caught(
    version_dir: Path, results: dict[str, CheckovResult]
) -> None:
    assert _result(version_dir, results).failed_ids >= WILDCARD_IAM


def test_the_open_ssh_rule_is_caught(version_dir: Path, results: dict[str, CheckovResult]) -> None:
    assert _result(version_dir, results).failed_ids >= OPEN_SSH


def test_the_gate_blocks_the_insecure_project(
    version_dir: Path, results: dict[str, CheckovResult]
) -> None:
    # The same rule that passes the template: a failing check not accepted as LOW or MEDIUM.
    blocked = blocking_checks(_result(version_dir, results), _accepted(version_dir))
    assert blocked >= UNENCRYPTED_DATABASE | PUBLIC_DATABASE | WILDCARD_IAM | OPEN_SSH


def test_none_of_the_deliberate_failures_is_an_accepted_check(version_dir: Path) -> None:
    deliberate = UNENCRYPTED_DATABASE | PUBLIC_DATABASE | WILDCARD_IAM | OPEN_SSH
    assert deliberate.isdisjoint(_accepted(version_dir))


def test_the_insecure_project_is_otherwise_valid_terraform(version_dir: Path) -> None:
    # It must fail because it is insecure, not because it is broken.
    result = terraform(
        ["fmt", "-check", "-recursive", "-no-color"], version_dir / "fixtures" / "insecure"
    )
    assert result.returncode == 0, output(result)


def test_it_is_labelled_and_holds_no_credentials(version_dir: Path) -> None:
    text = (version_dir / "fixtures" / "insecure" / "main.tf").read_text()
    assert text.startswith("# DELIBERATELY INSECURE")
    assert "password            = var.db_password" in text
    for forbidden in ("AKIA", "ASIA", "BEGIN RSA", "BEGIN PRIVATE"):
        assert forbidden not in text


def test_it_is_never_part_of_a_rendered_project(version_dir: Path) -> None:
    for fixture in load_fixtures(version_dir).values():
        for path in render_fixture(version_dir, fixture):
            assert "insecure" not in path
