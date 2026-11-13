"""Versioning and publication guards (startup-template tasks 11.1 to 11.3).

Covers the review gate (6.1, 6.3), the file-hash manifest that freezes a published version
(5.1, 5.2), and the publish helper that produces `template_versions` row values (5.3).
Mutation tests work on a copy of the real version directory in a temporary location.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from template_tools import publication
from template_tools.publication import (
    MANIFEST_NAME,
    PublicationError,
    check_version,
    review_problems,
    template_version_row,
    write_manifest,
)

TEMPLATES_ROOT = Path(__file__).resolve().parent.parent
VERSION_DIRS = sorted(p for p in (TEMPLATES_ROOT / "startup").iterdir() if p.is_dir())
NO_REVIEW = {"reviewed_by": None, "reviewed_at": None, "notes_ref": None}
REVIEW = {"reviewed_by": "A. Reviewer", "reviewed_at": "2026-11-20", "notes_ref": None}


@pytest.fixture(params=VERSION_DIRS, ids=lambda p: p.name)
def version_dir(request: pytest.FixtureRequest) -> Path:
    path: Path = request.param
    return path


@pytest.fixture
def copy(version_dir: Path, tmp_path: Path) -> Path:
    """A scratch copy, reset to an unreviewed draft, that tests may change.

    The committed version may already be published, so the copy drops its manifest, review
    record, and status; each test then publishes the copy itself when it needs to.
    """
    target = tmp_path / version_dir.name
    shutil.copytree(version_dir, target, ignore=shutil.ignore_patterns(".terraform", "__pycache__"))
    (target / MANIFEST_NAME).unlink(missing_ok=True)
    _set_template(target, status="draft", review=NO_REVIEW)
    return target


def _set_template(path: Path, **changes: object) -> None:
    file = path / "template.json"
    data = json.loads(file.read_text())
    data.update(changes)
    file.write_text(json.dumps(data, indent=2) + "\n")


def _publish(path: Path) -> None:
    _set_template(path, status="published", review=REVIEW)
    write_manifest(path)


# --- The committed versions --------------------------------------------------------------


def test_every_committed_version_passes_the_checks(version_dir: Path) -> None:
    assert check_version(version_dir) == []


def test_a_published_version_has_a_review_record_and_a_manifest(version_dir: Path) -> None:
    meta = json.loads((version_dir / "template.json").read_text())
    if meta["status"] == "draft":
        assert not (version_dir / MANIFEST_NAME).exists()
    else:
        assert not review_problems(meta)
        assert (version_dir / MANIFEST_NAME).is_file()


def test_the_publish_helper_accepts_every_committed_version(version_dir: Path) -> None:
    row = template_version_row(version_dir)
    meta = json.loads((version_dir / "template.json").read_text())
    assert row["template_id"] == meta["template"]
    assert row["version"] == meta["version"]
    assert row["status"] == meta["status"]


# --- Review gate -------------------------------------------------------------------------


def test_a_draft_needs_no_review() -> None:
    assert review_problems({"status": "draft", "review": {"reviewed_by": None}}) == []


@pytest.mark.parametrize("status", ["published", "retired"])
@pytest.mark.parametrize(
    "review",
    [
        None,
        {},
        {"reviewed_by": None, "reviewed_at": None},
        {"reviewed_by": "A. Reviewer", "reviewed_at": None},
        {"reviewed_by": None, "reviewed_at": "2026-11-20"},
        {"reviewed_by": "  ", "reviewed_at": "2026-11-20"},
        {"reviewed_by": "A. Reviewer", "reviewed_at": ""},
        {"reviewed_by": "A. Reviewer", "reviewed_at": "last week"},
        {"reviewed_by": 7, "reviewed_at": "2026-11-20"},
    ],
)
def test_the_review_gate_blocks_an_incomplete_review(status: str, review: object) -> None:
    assert review_problems({"status": status, "review": review})


@pytest.mark.parametrize(
    "stamp", ["2026-11-20", "2026-11-20T09:30:00Z", "2026-11-20T09:30:00+01:00"]
)
def test_the_review_gate_passes_a_complete_review(stamp: str) -> None:
    review = {"reviewed_by": "A. Reviewer", "reviewed_at": stamp}
    assert review_problems({"status": "published", "review": review}) == []


def test_an_unknown_status_is_rejected() -> None:
    assert review_problems({"status": "released"})
    assert review_problems({})


def test_publishing_without_a_review_fails_the_version_check(copy: Path) -> None:
    _set_template(copy, status="published", review=NO_REVIEW)
    problems = check_version(copy)
    assert any("reviewed_by" in p for p in problems)
    assert any("reviewed_at" in p for p in problems)


def test_the_manifest_cannot_be_written_without_a_review(copy: Path) -> None:
    _set_template(copy, status="published", review=NO_REVIEW)
    with pytest.raises(PublicationError, match="reviewed_by"):
        write_manifest(copy)
    assert not (copy / MANIFEST_NAME).exists()


def test_the_manifest_cannot_be_written_for_a_draft(copy: Path) -> None:
    _set_template(copy, status="draft")
    with pytest.raises(PublicationError, match="published"):
        write_manifest(copy)


# --- Manifest and immutability -----------------------------------------------------------


def test_a_published_version_without_a_manifest_fails(copy: Path) -> None:
    _publish(copy)
    (copy / MANIFEST_NAME).unlink()
    assert any("manifest.json is missing" in p for p in check_version(copy))


def test_a_draft_must_not_carry_a_manifest(copy: Path) -> None:
    _publish(copy)
    _set_template(copy, status="draft")
    assert any("drafts have no manifest" in p for p in check_version(copy))


def test_a_freshly_published_version_passes(copy: Path) -> None:
    _publish(copy)
    assert check_version(copy) == []
    manifest = json.loads((copy / MANIFEST_NAME).read_text())
    assert MANIFEST_NAME not in manifest["files"]
    assert "modules/network/main.tf" in manifest["files"]
    assert "schema.json" in manifest["files"]


def test_the_manifest_is_deterministic(copy: Path) -> None:
    _publish(copy)
    first = (copy / MANIFEST_NAME).read_text()
    write_manifest(copy)
    assert (copy / MANIFEST_NAME).read_text() == first
    assert list(json.loads(first)["files"]) == sorted(json.loads(first)["files"])


@pytest.mark.parametrize(
    "path", ["schema.json", "modules/network/main.tf", "root/main.tf.tmpl", "sandbox-policy.json"]
)
def test_editing_a_published_file_fails(copy: Path, path: str) -> None:
    _publish(copy)
    target = copy / path
    target.write_text(target.read_text() + "\n# edit\n")
    assert any(p.startswith(f"{path}: changed") for p in check_version(copy))


def test_adding_a_file_to_a_published_version_fails(copy: Path) -> None:
    _publish(copy)
    (copy / "modules" / "network" / "extra.tf").write_text("# new\n")
    assert any("extra.tf: added" in p for p in check_version(copy))


def test_removing_a_file_from_a_published_version_fails(copy: Path) -> None:
    _publish(copy)
    (copy / "inventory.json").unlink()
    assert any("inventory.json: removed" in p for p in check_version(copy))


def test_tampering_with_the_file_list_in_the_manifest_fails(copy: Path) -> None:
    _publish(copy)
    path = copy / MANIFEST_NAME
    data = json.loads(path.read_text())
    del data["files"]["schema.json"]
    path.write_text(json.dumps(data))
    problems = check_version(copy)
    assert any("schema.json: added" in p for p in problems)
    assert any("manifest_sha256" in p for p in problems)


def test_changing_the_review_after_publication_fails(copy: Path) -> None:
    _publish(copy)
    _set_template(copy, review={**REVIEW, "reviewed_by": "Someone Else"})
    assert any(p.startswith("template.json: changed") for p in check_version(copy))


def test_retiring_a_published_version_is_allowed(copy: Path) -> None:
    _publish(copy)
    _set_template(copy, status="retired")
    assert check_version(copy) == []


def test_a_retired_version_still_needs_its_review(copy: Path) -> None:
    _publish(copy)
    _set_template(copy, status="retired", review={"reviewed_by": None, "reviewed_at": None})
    assert check_version(copy)


def test_tool_output_directories_are_not_part_of_a_version(copy: Path) -> None:
    _publish(copy)
    (copy / "tests" / "network" / ".terraform").mkdir(parents=True)
    (copy / "tests" / "network" / ".terraform" / "state").write_text("x")
    (copy / "__pycache__").mkdir()
    (copy / "__pycache__" / "x.pyc").write_bytes(b"\0")
    assert check_version(copy) == []


def test_the_version_must_match_its_directory(copy: Path) -> None:
    _set_template(copy, version="9.9.9")
    assert any("does not match the directory" in p for p in check_version(copy))


def test_the_version_must_be_semver(copy: Path) -> None:
    _set_template(copy, version="v1")
    assert any("not semver" in p for p in check_version(copy))


# --- Publish helper ----------------------------------------------------------------------


def test_the_row_holds_the_table_columns(copy: Path) -> None:
    row = template_version_row(copy)
    assert set(row) == {"template_id", "version", "schema_json", "status"}
    assert row["template_id"] == "startup"
    assert row["schema_json"] == json.loads((copy / "schema.json").read_text())
    assert row["status"] == "draft"


def test_the_row_of_a_published_version_carries_the_manifest_hash(copy: Path) -> None:
    _publish(copy)
    row = template_version_row(copy)
    assert row["status"] == "published"
    assert (
        row["manifest_sha256"] == json.loads((copy / MANIFEST_NAME).read_text())["manifest_sha256"]
    )


def test_the_helper_refuses_an_unreviewed_publication(copy: Path) -> None:
    _set_template(copy, status="published", review=NO_REVIEW)
    with pytest.raises(PublicationError, match="reviewed_by"):
        template_version_row(copy)


def test_the_helper_refuses_a_stale_sandbox_policy(copy: Path) -> None:
    policy = copy / "sandbox-policy.json"
    policy.write_text(policy.read_text() + " ")
    with pytest.raises(PublicationError, match="sandbox-policy.json is out of date"):
        template_version_row(copy)


def test_the_helper_writes_nothing(copy: Path) -> None:
    before = publication.file_hashes(copy)
    template_version_row(copy)
    assert publication.file_hashes(copy) == before
    assert not (copy / MANIFEST_NAME).exists()


# --- Command line ------------------------------------------------------------------------


def test_the_cli_check_and_row(copy: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert publication.main(["check", str(copy)]) == 0
    assert publication.main(["row", str(copy)]) == 0
    assert json.loads(capsys.readouterr().out.split("\n", 1)[1])["version"] == copy.name


def test_the_cli_fails_on_a_bad_version(copy: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _set_template(copy, status="published", review=NO_REVIEW)
    assert publication.main(["check", str(copy)]) == 1
    assert publication.main(["manifest", str(copy)]) == 1
    assert publication.main(["row", str(copy)]) == 1
    assert "reviewed_by" in capsys.readouterr().err


def test_the_cli_manifest_check(copy: Path) -> None:
    _publish(copy)
    assert publication.main(["manifest", str(copy), "--check"]) == 0
    (copy / "schema.json").write_text("{}")
    assert publication.main(["manifest", str(copy), "--check"]) == 1
