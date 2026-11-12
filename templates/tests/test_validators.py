"""The four validators on every fixture (startup-template task 10.2).

Each fixture is rendered and run through, in the validation spec's order:

1. `terraform fmt -check`
2. `terraform init -backend=false`, then `terraform validate`
3. `tflint` with the AWS ruleset (pinned in the worker image) and local modules
4. `checkov --skip-download`

All must pass with zero blocking findings. Checkov is judged by the validation spec's rule: a
failing check not accepted as LOW or MEDIUM is HIGH. The accepted list, and why each entry is
accepted, is `fixtures/checkov-accepted.json`; it stands in for the validation spec's
`checkov-severity.json` until that exists.

Nothing here contacts AWS or any Checkov platform.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import ResultFactory
from fixtures import VERSION_DIRS, load_fixtures, render_fixture
from reference_render import write_project
from tf_runner import output, terraform
from validators import blocking_checks

CASES = [(v, name) for v in VERSION_DIRS for name in sorted(load_fixtures(v))]
IDS = [f"{v.name}-{name}" for v, name in CASES]


def _accepted(version_dir: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(
        (version_dir / "fixtures" / "checkov-accepted.json").read_text()
    )
    return data


@pytest.fixture(params=CASES, ids=IDS)
def case(request: pytest.FixtureRequest) -> tuple[Path, str]:
    value: tuple[Path, str] = request.param
    return value


# --- 1 and 2: Terraform ------------------------------------------------------------------


def test_fmt(case: tuple[Path, str], tmp_path: Path) -> None:
    version_dir, name = case
    write_project(render_fixture(version_dir, load_fixtures(version_dir)[name]), tmp_path)
    result = terraform(["fmt", "-check", "-recursive", "-diff", "-no-color"], tmp_path)
    assert result.returncode == 0, f"terraform fmt -check failed:\n{output(result)}"


def test_validate(case: tuple[Path, str], project_factory: Any) -> None:
    version_dir, name = case
    result = terraform(["validate", "-no-color"], project_factory(version_dir, name))
    assert result.returncode == 0, f"terraform validate failed:\n{output(result)}"


# --- 3: tflint ---------------------------------------------------------------------------


def test_tflint_has_no_errors(case: tuple[Path, str], tflint_results: ResultFactory) -> None:
    version_dir, name = case
    result = tflint_results(version_dir, name)
    assert result.errors == [], f"tflint could not run: {result.errors}"
    assert result.blocking == [], [
        (i["rule"]["name"], i["range"]["filename"], i["message"]) for i in result.blocking
    ]


def test_tflint_has_no_warnings_either(
    case: tuple[Path, str], tflint_results: ResultFactory
) -> None:
    # Warnings do not block, but the template has none, so any new one is a decision to make.
    version_dir, name = case
    result = tflint_results(version_dir, name)
    assert result.issues == [], [
        (i["rule"]["severity"], i["rule"]["name"], i["range"]["filename"], i["message"])
        for i in result.issues
    ]


def test_tflint_ran_the_aws_ruleset(case: tuple[Path, str], tflint_results: ResultFactory) -> None:
    # A clean result is only meaningful if the AWS rules were loaded. tflint exits 1 with an
    # error when a configured plugin is missing, which test_tflint_has_no_errors would catch;
    # this pins the exit code too.
    version_dir, name = case
    assert tflint_results(version_dir, name).exit_code == 0


# --- 4: Checkov --------------------------------------------------------------------------


def test_checkov_scanned_the_whole_project(
    case: tuple[Path, str], checkov_results: ResultFactory
) -> None:
    version_dir, name = case
    result = checkov_results(version_dir, name)
    inventory = json.loads((version_dir / "inventory.json").read_text())
    assert result.summary["parsing_errors"] == 0
    assert result.summary["resource_count"] >= len(inventory["resources"])
    paths = {c["file_path"] for c in result.passed + result.failed}
    for module in ("network", "compute", "database", "monitoring", "iam"):
        assert any(f"/modules/{module}/" in p for p in paths), f"module {module} was not scanned"


def test_checkov_reports_no_severity(
    case: tuple[Path, str], checkov_results: ResultFactory
) -> None:
    # ASSUMPTION: open-source Checkov reports no severity, so Lusiform assigns it. If a future
    # version starts reporting one, the severity map needs revisiting, not silently ignoring.
    version_dir, name = case
    result = checkov_results(version_dir, name)
    assert {c.get("severity") for c in result.failed + result.passed} == {None}


def test_zero_high_severity_checkov_findings(
    case: tuple[Path, str], checkov_results: ResultFactory
) -> None:
    version_dir, name = case
    result = checkov_results(version_dir, name)
    high = blocking_checks(result, _accepted(version_dir)["accepted"])
    assert high == set(), f"failing checks that are not accepted as LOW or MEDIUM: {sorted(high)}"


def test_only_accepted_checks_fail(case: tuple[Path, str], checkov_results: ResultFactory) -> None:
    version_dir, name = case
    result = checkov_results(version_dir, name)
    assert result.failed_ids <= set(_accepted(version_dir)["accepted"])


def test_important_checks_ran_and_passed(
    case: tuple[Path, str], checkov_results: ResultFactory
) -> None:
    # Nothing failing is only reassuring if the checks that matter actually ran. A check that
    # stops applying (a renamed attribute, a Checkov upgrade) would otherwise vanish silently.
    version_dir, name = case
    result = checkov_results(version_dir, name)
    groups = _accepted(version_dir)["must_pass"]
    for group, ids in groups.items():
        for check_id in ids:
            assert check_id in result.passed_ids, f"{group}: {check_id} did not run"
            assert check_id not in result.failed_ids, f"{group}: {check_id} fails"


def test_the_gate_passes(
    case: tuple[Path, str],
    project_factory: Any,
    tflint_results: ResultFactory,
    checkov_results: ResultFactory,
) -> None:
    # The Terraform gate from the validation spec, as a pure function of the four results.
    version_dir, name = case
    project = project_factory(version_dir, name)
    fmt_ok = terraform(["fmt", "-check", "-recursive", "-no-color"], project).returncode == 0
    validate_ok = terraform(["validate", "-no-color"], project).returncode == 0
    tflint = tflint_results(version_dir, name)
    checkov = checkov_results(version_dir, name)
    gate = (
        fmt_ok
        and validate_ok
        and not tflint.errors
        and not tflint.blocking
        and not blocking_checks(checkov, _accepted(version_dir)["accepted"])
    )
    assert gate


# --- The accepted list is honest ---------------------------------------------------------


def test_accepted_checks_are_low_or_medium_with_a_reason(version_dir_param: Path) -> None:
    for check_id, entry in _accepted(version_dir_param)["accepted"].items():
        assert entry["severity"] in {"LOW", "MEDIUM"}, check_id
        assert entry["reason"], check_id
        assert isinstance(entry["deviates_from_rule"], bool), check_id


def test_every_accepted_check_still_fails_somewhere(
    version_dir_param: Path, checkov_results: ResultFactory
) -> None:
    failing: set[str] = set()
    for name in load_fixtures(version_dir_param):
        failing |= checkov_results(version_dir_param, name).failed_ids
    stale = set(_accepted(version_dir_param)["accepted"]) - failing
    assert stale == set(), f"accepted but no longer failing; remove them: {sorted(stale)}"


def test_accepted_and_must_pass_do_not_overlap(version_dir_param: Path) -> None:
    accepted = set(_accepted(version_dir_param)["accepted"])
    must_pass = {i for ids in _accepted(version_dir_param)["must_pass"].values() for i in ids}
    assert accepted.isdisjoint(must_pass)


def test_the_file_names_the_pinned_checkov(version_dir_param: Path) -> None:
    meta = json.loads((version_dir_param / "template.json").read_text())
    assert _accepted(version_dir_param)["checkov"] == meta["tools"]["checkov"]


def test_deviations_from_the_severity_rule_are_explained(version_dir_param: Path) -> None:
    deviating = {
        check_id
        for check_id, entry in _accepted(version_dir_param)["accepted"].items()
        if entry["deviates_from_rule"]
    }
    assumptions = " ".join(_accepted(version_dir_param)["assumptions"])
    assert deviating, "the deviations are the open decision for the reviewer"
    assert "deviates_from_rule" in assumptions or "would be HIGH" in assumptions


@pytest.fixture(params=VERSION_DIRS, ids=lambda p: p.name)
def version_dir_param(request: pytest.FixtureRequest) -> Path:
    path: Path = request.param
    return path
