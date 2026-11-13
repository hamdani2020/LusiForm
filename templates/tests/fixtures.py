"""Template fixtures: named parameter sets, and helpers to render them. TEST ONLY.

A fixture is a JSON file in `startup/<version>/fixtures/params/`. It fixes everything a render
depends on (parameters, region, name prefix, display names), so the rendered output is the same
every time and can be compared to the golden files.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reference_render import render_project

TEMPLATES_ROOT = Path(__file__).resolve().parent.parent
VERSION_DIRS = sorted(p for p in (TEMPLATES_ROOT / "startup").iterdir() if p.is_dir())

# The files the renderer fills from root/*.tmpl. Module files are copied verbatim.
ROOT_FILES = ("main.tf", "variables.tf", "outputs.tf", "terraform.tfvars.example", "README.md")


@dataclass(frozen=True)
class Fixture:
    name: str
    description: str
    region: str
    name_prefix: str
    project_name: str
    customer_name: str
    parameters: dict[str, Any]


def load_fixtures(version_dir: Path) -> dict[str, Fixture]:
    fixtures: dict[str, Fixture] = {}
    for path in sorted((version_dir / "fixtures" / "params").glob("*.json")):
        data = json.loads(path.read_text())
        fixture = Fixture(**data)
        assert fixture.name == path.stem, f"{path.name}: name must match the file name"
        fixtures[fixture.name] = fixture
    return fixtures


def render_fixture(version_dir: Path, fixture: Fixture) -> dict[str, bytes]:
    """The rendered project for a fixture, as `{path: bytes}`."""
    return render_project(
        version_dir,
        fixture.parameters,
        region=fixture.region,
        name_prefix=fixture.name_prefix,
        project_name=fixture.project_name,
        customer_name=fixture.customer_name,
    )


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def manifest(files: dict[str, bytes]) -> dict[str, str]:
    """SHA-256 of every file, sorted by path."""
    return {path: sha256(content) for path, content in sorted(files.items())}


def project_hash(files: dict[str, bytes]) -> str:
    """One hash for a whole project: the manifest, canonically serialised."""
    canonical = json.dumps(manifest(files), sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8"))
