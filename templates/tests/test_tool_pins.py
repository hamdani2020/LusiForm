"""Tool pins and template metadata (startup-template tasks 1.1 and 1.2).

The tool versions recorded in template.json must equal the pins in the worker image
Dockerfile and the binaries actually installed in it (requirement NFR 3). A drift
fails here rather than as a confusing validator difference later.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

TEMPLATES_ROOT = Path(__file__).resolve().parent.parent
WORKER_DOCKERFILE = TEMPLATES_ROOT.parent / "worker" / "Dockerfile"
VERSION_DIRS = sorted(p for p in (TEMPLATES_ROOT / "startup").iterdir() if p.is_dir())

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
STATUSES = {"draft", "published", "retired"}


def _load(version_dir: Path) -> dict[str, object]:
    data: dict[str, object] = json.loads((version_dir / "template.json").read_text())
    return data


def _tools(meta: dict[str, object]) -> dict[str, str]:
    tools = meta["tools"]
    assert isinstance(tools, dict)
    return {str(k): str(v) for k, v in tools.items()}


def _run(*cmd: str) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)  # noqa: S603
    return result.stdout + result.stderr


def _dockerfile_pins() -> dict[str, str]:
    text = WORKER_DOCKERFILE.read_text()
    terraform = re.search(r"hashicorp/terraform:(\d+\.\d+\.\d+)", text)
    tflint = re.search(r"terraform-linters/tflint:v(\d+\.\d+\.\d+)", text)
    checkov = re.search(r"checkov==(\d+\.\d+\.\d+)", text)
    ruleset = re.search(r"ARG TFLINT_RULESET_AWS_VERSION=(\d+\.\d+\.\d+)", text)
    assert terraform and tflint and checkov and ruleset, "worker/Dockerfile pins not found"
    return {
        "terraform": terraform.group(1),
        "tflint": tflint.group(1),
        "checkov": checkov.group(1),
        "tflint_ruleset_aws": ruleset.group(1),
    }


@pytest.fixture(params=VERSION_DIRS, ids=lambda p: p.name)
def version_dir(request: pytest.FixtureRequest) -> Path:
    path: Path = request.param
    return path


def test_metadata_shape(version_dir: Path) -> None:
    meta = _load(version_dir)
    assert meta["template"] == "startup"
    assert meta["version"] == version_dir.name
    assert SEMVER.match(version_dir.name)
    assert meta["status"] in STATUSES
    assert meta["terraform"] == ">= 1.10.0"
    assert meta["aws_provider"] == "~> 5.47"
    review = meta["review"]
    assert isinstance(review, dict)
    assert set(review) == {"reviewed_by", "reviewed_at", "notes_ref"}


def test_layout(version_dir: Path) -> None:
    for name in ("modules", "root", "fixtures"):
        assert (version_dir / name).is_dir(), f"{version_dir.name}/{name} missing"


def test_pins_are_exact(version_dir: Path) -> None:
    for tool, version in _tools(_load(version_dir)).items():
        assert SEMVER.match(version), f"{tool} pin {version!r} is not an exact version"


def test_pins_match_worker_dockerfile(version_dir: Path) -> None:
    assert _tools(_load(version_dir)) == _dockerfile_pins()


def test_installed_terraform_matches_pin(version_dir: Path) -> None:
    out = json.loads(_run("terraform", "version", "-json"))
    assert out["terraform_version"] == _tools(_load(version_dir))["terraform"]


def test_installed_tflint_matches_pin(version_dir: Path) -> None:
    out = _run("tflint", "--version")
    assert f"TFLint version {_tools(_load(version_dir))['tflint']}" in out


def test_installed_checkov_matches_pin(version_dir: Path) -> None:
    out = _run("checkov", "--version").strip().splitlines()[-1].strip()
    assert out == _tools(_load(version_dir))["checkov"]


def test_installed_tflint_ruleset_matches_pin(version_dir: Path) -> None:
    version = _tools(_load(version_dir))["tflint_ruleset_aws"]
    plugin_dir = os.environ["TFLINT_PLUGIN_DIR"]
    installed = (
        Path(plugin_dir) / "github.com" / "terraform-linters" / "tflint-ruleset-aws" / version
    )
    assert (installed / "tflint-ruleset-aws").is_file(), f"ruleset {version} is not installed"
    # Exactly one version, so a stale plugin cannot be picked up by mistake.
    versions = [p.name for p in installed.parent.iterdir()]
    assert versions == [version]


def test_tflint_config_uses_the_pinned_ruleset(version_dir: Path) -> None:
    config = (version_dir / "tflint.hcl").read_text()
    version = _tools(_load(version_dir))["tflint_ruleset_aws"]
    assert f'version = "{version}"' in config
    assert 'source  = "github.com/terraform-linters/tflint-ruleset-aws"' in config
