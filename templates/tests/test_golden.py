"""Determinism and golden output (startup-template task 10.5).

The same fixture and template version must render byte for byte the same project, anywhere.
The golden files store that output; any difference fails, so a change to the output is always
a visible, reviewed diff. The generation-pipeline renderer's golden tests replace the
reference renderer used here and must match these files.

If a test fails after an intended change, regenerate and review the diff:

    docker compose run --rm --no-deps -w /app/templates worker \\
      python tests/update_golden.py startup/1.0.0
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from fixtures import (
    ROOT_FILES,
    VERSION_DIRS,
    load_fixtures,
    manifest,
    project_hash,
    render_fixture,
    sha256,
)
from reference_render import render_project
from update_golden import render_manifest

TESTS_DIR = Path(__file__).resolve().parent
TEMPLATES_ROOT = TESTS_DIR.parent
HOW_TO_UPDATE = "if this change is intended, run tests/update_golden.py and review the diff"

CASES = [(v, name) for v in VERSION_DIRS for name in sorted(load_fixtures(v))]


@pytest.fixture(params=CASES, ids=[f"{v.name}-{name}" for v, name in CASES])
def case(request: pytest.FixtureRequest) -> tuple[Path, str]:
    value: tuple[Path, str] = request.param
    return value


@pytest.fixture(params=VERSION_DIRS, ids=lambda p: p.name)
def version_dir(request: pytest.FixtureRequest) -> Path:
    path: Path = request.param
    return path


def _files(case: tuple[Path, str]) -> dict[str, bytes]:
    version_dir, name = case
    return render_fixture(version_dir, load_fixtures(version_dir)[name])


# --- Determinism -------------------------------------------------------------------------


def test_rendering_twice_gives_identical_bytes(case: tuple[Path, str]) -> None:
    first, second = _files(case), _files(case)
    assert first == second
    assert project_hash(first) == project_hash(second)


def test_per_file_hashes_are_identical_across_renders(case: tuple[Path, str]) -> None:
    assert manifest(_files(case)) == manifest(_files(case))


def test_the_output_does_not_depend_on_the_environment(
    case: tuple[Path, str], tmp_path: Path
) -> None:
    # A fresh interpreter, another working directory, another time zone, locale, and hash seed.
    version_dir, name = case
    code = (
        "import sys; from fixtures import load_fixtures, render_fixture, project_hash; "
        f"from pathlib import Path; v = Path({str(version_dir)!r}); "
        f"print(project_hash(render_fixture(v, load_fixtures(v)[{name!r}])))"
    )
    results = set()
    for tz, lang, seed in (
        ("UTC", "C", "0"),
        ("Asia/Tokyo", "C.UTF-8", "1"),
        ("America/Los_Angeles", "C", "random"),
    ):
        environment = dict(os.environ)
        environment.update(
            {
                "TZ": tz,
                "LANG": lang,
                "LC_ALL": lang,
                "PYTHONHASHSEED": seed,
                "PYTHONPATH": f"{TESTS_DIR}{os.pathsep}{TEMPLATES_ROOT}",
            }
        )
        done = subprocess.run(  # noqa: S603
            [sys.executable, "-c", code],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert done.returncode == 0, done.stderr
        results.add(done.stdout.strip())
    assert results == {project_hash(_files(case))}


def test_no_timestamps_or_run_specific_values(case: tuple[Path, str]) -> None:
    for path, content in _files(case).items():
        if path.startswith("modules/"):
            continue
        text = content.decode("utf-8")
        assert not re.search(r"\b\d{4}-\d{2}-\d{2}\b", text), f"{path}: a date"
        assert not re.search(r"\b\d{2}:\d{2}:\d{2}\b", text), f"{path}: a time"
        assert not re.search(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", text
        ), path
        assert "generated at" not in text.lower(), path


def test_fixtures_with_different_inputs_render_differently() -> None:
    hashes = {}
    for version_dir in VERSION_DIRS:
        for name in load_fixtures(version_dir):
            hashes[name] = project_hash(
                render_fixture(version_dir, load_fixtures(version_dir)[name])
            )
    assert len(set(hashes.values())) == len(hashes), hashes


# --- Golden files ------------------------------------------------------------------------


def test_golden_has_exactly_the_expected_files(case: tuple[Path, str]) -> None:
    version_dir, name = case
    golden = version_dir / "fixtures" / "golden" / name
    assert sorted(p.name for p in golden.iterdir()) == sorted([*ROOT_FILES, "manifest.json"])


def test_root_files_match_the_golden_files_byte_for_byte(case: tuple[Path, str]) -> None:
    version_dir, name = case
    files = _files(case)
    for root_file in ROOT_FILES:
        golden = (version_dir / "fixtures" / "golden" / name / root_file).read_bytes()
        assert files[root_file] == golden, f"{name}/{root_file} differs; {HOW_TO_UPDATE}"


def test_every_file_matches_the_golden_manifest(case: tuple[Path, str]) -> None:
    version_dir, name = case
    expected = json.loads(
        (version_dir / "fixtures" / "golden" / name / "manifest.json").read_text()
    )
    actual = manifest(_files(case))
    assert set(actual) == set(expected["files"]), (
        f"files added or removed: {sorted(set(actual) ^ set(expected['files']))}; {HOW_TO_UPDATE}"
    )
    changed = sorted(p for p in actual if actual[p] != expected["files"][p])
    assert changed == [], f"changed files: {changed}; {HOW_TO_UPDATE}"


def test_the_whole_project_hash_matches(case: tuple[Path, str]) -> None:
    version_dir, name = case
    expected = json.loads(
        (version_dir / "fixtures" / "golden" / name / "manifest.json").read_text()
    )
    assert project_hash(_files(case)) == expected["project_sha256"], HOW_TO_UPDATE


def test_the_committed_manifest_is_what_the_script_writes(case: tuple[Path, str]) -> None:
    version_dir, name = case
    committed = (version_dir / "fixtures" / "golden" / name / "manifest.json").read_text()
    assert committed == render_manifest(version_dir, name, _files(case)), HOW_TO_UPDATE


def test_the_manifest_names_the_template_and_fixture(case: tuple[Path, str]) -> None:
    version_dir, name = case
    meta = json.loads((version_dir / "template.json").read_text())
    data = json.loads((version_dir / "fixtures" / "golden" / name / "manifest.json").read_text())
    assert data["schema"] == "lusiform.golden/1"
    assert (data["template"], data["template_version"], data["fixture"]) == (
        meta["template"],
        meta["version"],
        name,
    )
    assert list(data["files"]) == sorted(data["files"]), "files are sorted by path"


def test_there_is_no_golden_directory_without_a_fixture(version_dir: Path) -> None:
    golden = sorted(p.name for p in (version_dir / "fixtures" / "golden").iterdir() if p.is_dir())
    assert golden == sorted(load_fixtures(version_dir))


def test_module_files_in_the_manifest_are_the_template_modules(case: tuple[Path, str]) -> None:
    version_dir, name = case
    expected = json.loads(
        (version_dir / "fixtures" / "golden" / name / "manifest.json").read_text()
    )
    for path, digest in expected["files"].items():
        if path.startswith("modules/"):
            assert sha256((version_dir / path).read_bytes()) == digest, path


def test_a_changed_input_changes_the_golden_comparison(case: tuple[Path, str]) -> None:
    # The comparison has teeth: render with one parameter changed and it must not match.
    version_dir, name = case
    fixture = load_fixtures(version_dir)[name]
    params = json.loads(json.dumps(fixture.parameters))
    params.setdefault("monitoring", {})["log_retention_days"] = 14  # no fixture uses 14
    changed = render_project(
        version_dir,
        params,
        region=fixture.region,
        name_prefix=fixture.name_prefix,
        project_name=fixture.project_name,
        customer_name=fixture.customer_name,
    )
    expected = json.loads(
        (version_dir / "fixtures" / "golden" / name / "manifest.json").read_text()
    )
    assert project_hash(changed) != expected["project_sha256"]
