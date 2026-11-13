"""Rewrite the golden files for a template version. TEST ONLY.

Run this when the template, a fixture, or the reference renderer changes on purpose, then
review the diff. The golden tests fail on any difference, so a rewrite is a visible, reviewed
change and never an accident.

    python tests/update_golden.py startup/1.0.0

For each fixture, `fixtures/golden/<name>/` holds the root files exactly as rendered, and
`manifest.json` with the SHA-256 of every rendered file (the module files too). Module files
are copied unchanged from `modules/`, so their hash pins them without storing five copies.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

# The renderer imports template_tools from the template root, one level above this directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fixtures import ROOT_FILES, load_fixtures, manifest, project_hash, render_fixture  # noqa: E402

SCHEMA = "lusiform.golden/1"


def golden_manifest(version_dir: Path, name: str, files: dict[str, bytes]) -> dict[str, object]:
    meta = json.loads((version_dir / "template.json").read_text())
    return {
        "schema": SCHEMA,
        "template": meta["template"],
        "template_version": meta["version"],
        "fixture": name,
        "project_sha256": project_hash(files),
        "files": manifest(files),
    }


def render_manifest(version_dir: Path, name: str, files: dict[str, bytes]) -> str:
    return json.dumps(golden_manifest(version_dir, name, files), indent=2) + "\n"


def write_golden(version_dir: Path) -> list[str]:
    written: list[str] = []
    golden_root = version_dir / "fixtures" / "golden"
    for name, fixture in load_fixtures(version_dir).items():
        files = render_fixture(version_dir, fixture)
        target = golden_root / name
        shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True)
        for root_file in ROOT_FILES:
            (target / root_file).write_bytes(files[root_file])
        (target / "manifest.json").write_text(render_manifest(version_dir, name, files))
        written.append(name)
    return written


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    names = write_golden(Path(argv[1]))
    print(f"wrote golden files for: {', '.join(names)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
