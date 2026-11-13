"""Versioning and publication guards for a template version (startup-template task 11).

A template version is a directory, `startup/<semver>/`. Once it is published its files never
change (requirement 5.2). Three rules, all checked here and by `tests/test_publication.py`:

- Review gate (6.1, 6.3). `status` may be `published` (or `retired`, which follows published)
  only when `review.reviewed_by` and `review.reviewed_at` are set. A draft may have either.
- Hash manifest (5.1, 5.2). A published or retired version has `manifest.json`, the SHA-256 of
  every file in the version directory except the manifest itself. The set of files and every
  hash must match, so an edited, added, or removed file fails. `template.json` is hashed
  without its `status` field, because `status` mirrors the `template_versions` row and moves
  from `published` to `retired` without the template changing.
- Publish helper (5.3). `row` validates a version and prints the values for a
  `template_versions` row. It never touches a database; the operator route in the admin spec
  writes the row.

A manifest cannot stop someone from editing a published file and regenerating the manifest in
the same commit. Reviewers (and CODEOWNERS) must treat any diff to a published version's
directory as a failure; the manifest makes such a diff visible and the test makes an
accidental one fail.

Commands (run in the worker container, from `templates/`):

    python -m template_tools.publication check startup/1.0.0
    python -m template_tools.publication manifest startup/1.0.0           # write manifest.json
    python -m template_tools.publication manifest startup/1.0.0 --check
    python -m template_tools.publication row startup/1.0.0
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

Json = dict[str, Any]

MANIFEST_NAME = "manifest.json"
MANIFEST_SCHEMA = "lusiform.template-manifest/1"
STATUSES = ("draft", "published", "retired")
# States that need the review record and the manifest.
FROZEN_STATUSES = ("published", "retired")
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
# Directories that tools create inside a version directory and that are not template files.
IGNORED_DIRS = frozenset(
    {".terraform", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
)
IGNORED_FILES = frozenset({".DS_Store"})
# Fields of template.json that may change without changing the template.
MUTABLE_TEMPLATE_FIELDS = ("status",)
TEMPLATE_JSON = "template.json"


class PublicationError(Exception):
    """A version failed a publication rule; the message says which and why."""


def load_template_json(version_dir: Path) -> Json:
    path = version_dir / TEMPLATE_JSON
    if not path.is_file():
        raise PublicationError(f"{path} does not exist")
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise PublicationError(f"{path} must hold a JSON object")
    return data


# --- Review gate -------------------------------------------------------------------------


def _is_set(value: object) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _is_iso_date(value: str) -> bool:
    text = value.strip()
    try:
        if "T" in text or " " in text:
            datetime.fromisoformat(text.replace("Z", "+00:00"))
        else:
            date.fromisoformat(text)
    except ValueError:
        return False
    return True


def review_problems(meta: Json) -> list[str]:
    """Why `meta` may not be published, or an empty list when the review gate passes."""
    status = meta.get("status")
    if status not in STATUSES:
        return [f"status must be one of {', '.join(STATUSES)}, not {status!r}"]
    if status == "draft":
        return []
    review = meta.get("review")
    if not isinstance(review, dict):
        return [f"status {status!r} needs a review record; template.json has no review object"]
    problems = []
    if not _is_set(review.get("reviewed_by")):
        problems.append(f"status {status!r} needs review.reviewed_by (the reviewer)")
    reviewed_at = review.get("reviewed_at")
    if not _is_set(reviewed_at):
        problems.append(f"status {status!r} needs review.reviewed_at (an ISO 8601 date)")
    elif not _is_iso_date(str(reviewed_at)):
        problems.append(f"review.reviewed_at {reviewed_at!r} is not an ISO 8601 date")
    return problems


# --- Hash manifest -----------------------------------------------------------------------


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _template_json_bytes(content: bytes) -> bytes:
    """`template.json` without the fields that may change after publication, canonical form."""
    data = json.loads(content)
    for name in MUTABLE_TEMPLATE_FIELDS:
        data.pop(name, None)
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()


def version_files(version_dir: Path) -> list[Path]:
    """Every template file in the version directory, as sorted paths relative to it."""
    found = []
    for path in version_dir.rglob("*"):
        relative = path.relative_to(version_dir)
        if not path.is_file() or path.is_symlink():
            continue
        if any(part in IGNORED_DIRS for part in relative.parts[:-1]):
            continue
        if relative.name in IGNORED_FILES or relative.as_posix() == MANIFEST_NAME:
            continue
        found.append(relative)
    return sorted(found, key=lambda p: p.as_posix())


def file_hashes(version_dir: Path) -> dict[str, str]:
    hashes = {}
    for relative in version_files(version_dir):
        content = (version_dir / relative).read_bytes()
        if relative.as_posix() == TEMPLATE_JSON:
            content = _template_json_bytes(content)
        hashes[relative.as_posix()] = _sha256(content)
    return hashes


def manifest_digest(files: dict[str, str]) -> str:
    """One hash over the whole file list, for the `template_versions` record."""
    canonical = "".join(f"{path}\0{files[path]}\n" for path in sorted(files))
    return _sha256(canonical.encode())


def build_manifest(version_dir: Path) -> Json:
    meta = load_template_json(version_dir)
    files = file_hashes(version_dir)
    return {
        "schema": MANIFEST_SCHEMA,
        "template": meta.get("template"),
        "template_version": meta.get("version"),
        "template_json_ignores": list(MUTABLE_TEMPLATE_FIELDS),
        "files": files,
        "manifest_sha256": manifest_digest(files),
    }


def render_manifest(manifest: Json) -> str:
    return json.dumps(manifest, indent=2, sort_keys=False) + "\n"


def manifest_problems(version_dir: Path) -> list[str]:
    """Differences between the committed manifest and the files on disk."""
    path = version_dir / MANIFEST_NAME
    if not path.is_file():
        return [f"{path} is missing; run `python -m template_tools.publication manifest`"]
    try:
        recorded = json.loads(path.read_text())
    except json.JSONDecodeError as error:
        return [f"{path} is not valid JSON: {error}"]
    if recorded.get("schema") != MANIFEST_SCHEMA:
        return [f"{path}: schema must be {MANIFEST_SCHEMA!r}"]

    meta = load_template_json(version_dir)
    problems = []
    for key, expected in (
        ("template", meta.get("template")),
        ("template_version", meta.get("version")),
    ):
        if recorded.get(key) != expected:
            problems.append(
                f"manifest {key} is {recorded.get(key)!r}, template.json says {expected!r}"
            )

    expected_files = recorded.get("files")
    if not isinstance(expected_files, dict):
        return [*problems, "manifest has no files map"]
    actual = file_hashes(version_dir)
    for name in sorted(set(expected_files) - set(actual)):
        problems.append(f"{name}: removed from a frozen version")
    for name in sorted(set(actual) - set(expected_files)):
        problems.append(f"{name}: added to a frozen version")
    for name in sorted(set(actual) & set(expected_files)):
        if actual[name] != expected_files[name]:
            problems.append(f"{name}: changed in a frozen version")
    if recorded.get("manifest_sha256") != manifest_digest(
        {k: str(v) for k, v in expected_files.items()}
    ):
        problems.append("manifest_sha256 does not match the file list in the manifest")
    return problems


# --- Whole-version check ------------------------------------------------------------------


def check_version(version_dir: Path) -> list[str]:
    """Every publication problem for a version directory; empty means it may be used."""
    try:
        meta = load_template_json(version_dir)
    except (PublicationError, json.JSONDecodeError) as error:
        return [str(error)]
    problems = []
    version = meta.get("version")
    if not isinstance(version, str) or not SEMVER.match(version):
        problems.append(f"version {version!r} is not semver (for example 1.0.4)")
    elif version != version_dir.name:
        problems.append(
            f"template.json version {version} does not match the directory {version_dir.name}"
        )
    problems.extend(review_problems(meta))
    if meta.get("status") in FROZEN_STATUSES:
        problems.extend(manifest_problems(version_dir))
    elif meta.get("status") == "draft" and (version_dir / MANIFEST_NAME).exists():
        problems.append(
            f"{MANIFEST_NAME} exists but the version is a draft; drafts have no manifest"
        )
    return problems


def write_manifest(version_dir: Path) -> Json:
    """Write `manifest.json`. Refuses unless the version passes the review gate and is frozen."""
    meta = load_template_json(version_dir)
    if meta.get("status") not in FROZEN_STATUSES:
        raise PublicationError(
            f"status is {meta.get('status')!r}; set it to 'published' before writing the manifest"
        )
    problems = review_problems(meta)
    if problems:
        raise PublicationError("; ".join(problems))
    manifest = build_manifest(version_dir)
    (version_dir / MANIFEST_NAME).write_text(render_manifest(manifest))
    return manifest


# --- Publish helper -----------------------------------------------------------------------


def template_version_row(version_dir: Path) -> Json:
    """Values for a `template_versions` row, after validating the version.

    Raises `PublicationError` listing every problem. Does not write anywhere. The table's
    `id` and `created_at` are set by the database.
    """
    # Imported here so the manifest and review checks work without the policy inputs.
    from template_tools import sandbox_policy

    problems = check_version(version_dir)
    if not problems:
        try:
            result = sandbox_policy.generate(version_dir)
        except Exception as error:  # noqa: BLE001 - report any generator failure as a problem
            problems.append(f"sandbox policy cannot be generated: {error}")
        else:
            committed = version_dir / "sandbox-policy.json"
            if not committed.is_file() or committed.read_text() != sandbox_policy.render(
                result.document
            ):
                problems.append(
                    "sandbox-policy.json is out of date; run template_tools.sandbox_policy"
                )
    if problems:
        raise PublicationError("\n".join(problems))

    meta = load_template_json(version_dir)
    schema = json.loads((version_dir / "schema.json").read_text())
    row: Json = {
        "template_id": meta["template"],
        "version": meta["version"],
        "schema_json": schema,
        "status": meta["status"],
    }
    if meta["status"] in FROZEN_STATUSES:
        row["manifest_sha256"] = json.loads((version_dir / MANIFEST_NAME).read_text())[
            "manifest_sha256"
        ]
    return row


# --- Command line -------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Template version publication guards")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, text in (
        ("check", "run the review gate and manifest checks"),
        ("manifest", "write manifest.json (published versions only)"),
        ("row", "validate and print the template_versions row as JSON"),
    ):
        p = sub.add_parser(name, help=text)
        p.add_argument("version_dir", type=Path)
        if name == "manifest":
            p.add_argument("--check", action="store_true", help="fail if the file is out of date")
    args = parser.parse_args(argv)
    version_dir: Path = args.version_dir

    try:
        if args.command == "check":
            problems = check_version(version_dir)
            for problem in problems:
                print(f"{version_dir}: {problem}", file=sys.stderr)
            if not problems:
                print(f"{version_dir} passes the publication checks")
            return 1 if problems else 0
        if args.command == "manifest":
            if args.check:
                problems = manifest_problems(version_dir)
                for problem in problems:
                    print(f"{version_dir}: {problem}", file=sys.stderr)
                return 1 if problems else 0
            manifest = write_manifest(version_dir)
            print(f"wrote {version_dir / MANIFEST_NAME} ({len(manifest['files'])} files)")
            return 0
        print(json.dumps(template_version_row(version_dir), indent=2))
        return 0
    except PublicationError as error:
        print(f"{version_dir}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
