"""Static checks on the template modules (startup-template tasks 3 to 7).

These read the HCL as text. They enforce scope and safety rules that the Terraform tests
cannot express: which resource types may exist, no wildcard IAM, no hardcoded account IDs
or credentials, no non-deterministic functions, and that every IAM policy is covered by the
policy lint in tests/iam/iam.tftest.hcl.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

TEMPLATES_ROOT = Path(__file__).resolve().parent.parent
VERSION_DIRS = sorted(p for p in (TEMPLATES_ROOT / "startup").iterdir() if p.is_dir())
MODULES = ["network", "monitoring", "iam", "database", "compute"]

RESOURCE = re.compile(r'^resource\s+"(aws_[a-z0-9_]+)"\s+"([a-z0-9_]+)"', re.MULTILINE)
DATA = re.compile(r'^data\s+"(aws_[a-z0-9_]+)"', re.MULTILINE)

# Resource-type prefixes that are out of scope for the MVP template (requirement 1.3).
FORBIDDEN_TYPES = (
    "aws_eks",
    "aws_rds_cluster",  # Aurora
    "aws_elasticache",
    "aws_cloudfront",
    "aws_wafv2",
    "aws_waf",
    "aws_shield",
    "aws_route53",
    "aws_acm",
    "aws_s3",
)

# Plan-time lookups the modules may use. caller identity is one local STS call; region and
# partition read provider configuration and make no API call.
ALLOWED_DATA = {"aws_caller_identity", "aws_partition", "aws_region"}

NON_DETERMINISTIC = re.compile(r"\b(timestamp|uuid|uuidv4|plantimestamp)\s*\(|\brandom_[a-z_]+")
ACCOUNT_ID = re.compile(r"(?<![\w-])\d{12}(?![\w-])")
ACCESS_KEY = re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b")


def _strip_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _module_text(version_dir: Path, module: str) -> str:
    files = sorted((version_dir / "modules" / module).glob("*.tf"))
    assert files, f"{module} has no .tf files"
    return "\n".join(_strip_comments(f.read_text()) for f in files)


@pytest.fixture(params=VERSION_DIRS, ids=lambda p: p.name)
def version_dir(request: pytest.FixtureRequest) -> Path:
    path: Path = request.param
    return path


def test_exactly_the_five_modules_exist(version_dir: Path) -> None:
    found = sorted(p.name for p in (version_dir / "modules").iterdir() if p.is_dir())
    assert found == sorted(MODULES)


@pytest.mark.parametrize("module", MODULES)
def test_module_has_the_standard_files(version_dir: Path, module: str) -> None:
    for name in ("main.tf", "variables.tf", "outputs.tf", "versions.tf"):
        assert (version_dir / "modules" / module / name).is_file(), f"{module}/{name}"
    assert (version_dir / "tests" / module).is_dir(), f"tests/{module}"
    assert list((version_dir / "tests" / module).glob("*.tftest.hcl")), f"no tftest for {module}"


@pytest.mark.parametrize("module", MODULES)
def test_module_pins_terraform_and_provider(version_dir: Path, module: str) -> None:
    text = (version_dir / "modules" / module / "versions.tf").read_text()
    assert 'required_version = ">= 1.10.0"' in text
    assert 'version = "~> 5.47"' in text


@pytest.mark.parametrize("module", MODULES)
def test_module_takes_name_prefix_and_tags(version_dir: Path, module: str) -> None:
    text = (version_dir / "modules" / module / "variables.tf").read_text()
    assert 'variable "name_prefix"' in text
    assert 'variable "tags"' in text


@pytest.mark.parametrize("module", MODULES)
def test_no_out_of_scope_resources(version_dir: Path, module: str) -> None:
    for resource_type, _ in RESOURCE.findall(_module_text(version_dir, module)):
        assert not resource_type.startswith(FORBIDDEN_TYPES), f"{module}: {resource_type}"


@pytest.mark.parametrize("module", MODULES)
def test_no_graviton_only_constructs(version_dir: Path, module: str) -> None:
    text = _module_text(version_dir, module)
    assert "ARM64" not in text
    assert "graviton" not in text.lower()


@pytest.mark.parametrize("module", MODULES)
def test_only_local_data_sources(version_dir: Path, module: str) -> None:
    used = set(DATA.findall(_module_text(version_dir, module)))
    assert used <= ALLOWED_DATA, f"{module}: unexpected data sources {used - ALLOWED_DATA}"


@pytest.mark.parametrize("module", MODULES)
def test_deterministic_constructs_only(version_dir: Path, module: str) -> None:
    match = NON_DETERMINISTIC.search(_module_text(version_dir, module))
    assert match is None, f"{module}: {match.group(0) if match else ''}"


@pytest.mark.parametrize("module", MODULES)
def test_no_account_ids_or_keys_in_module_files(version_dir: Path, module: str) -> None:
    text = _module_text(version_dir, module)
    assert ACCOUNT_ID.search(text) is None, f"{module}: contains a 12-digit number"
    assert ACCESS_KEY.search(text) is None, f"{module}: contains an access key pattern"
    assert not re.search(r'(?i)\b(password|secret_key|access_key)\s*=\s*"[^"]+"', text)


@pytest.mark.parametrize("module", MODULES)
def test_no_hardcoded_region_or_zone_names(version_dir: Path, module: str) -> None:
    text = _module_text(version_dir, module)
    assert not re.search(r"\b[a-z]{2}-[a-z]+-\d[a-z]?\b", text), f"{module}: region or zone literal"


def test_module_tests_use_mocked_providers_only(version_dir: Path) -> None:
    for test_file in (version_dir / "tests").rglob("*.tftest.hcl"):
        assert 'mock_provider "aws"' in test_file.read_text(), f"{test_file.name} is not mocked"


# --- IAM policy lint (task 5.2) ----------------------------------------------------------------


def test_iam_has_no_wildcard_action_or_resource_in_source(version_dir: Path) -> None:
    text = _module_text(version_dir, "iam")
    assert not re.search(r'(Action|Resource)\s*=\s*"\*"', text)
    assert not re.search(r'(Action|Resource)\s*=\s*\[[^\]]*"\*"', text)
    assert not re.search(r'"[a-z0-9-]+:\*"', text), "service-wide action wildcard"


def test_iam_has_no_inline_policies(version_dir: Path) -> None:
    # Inline policies would sit outside the aws_iam_policy lint, so they are not allowed.
    types = {t for t, _ in RESOURCE.findall(_module_text(version_dir, "iam"))}
    assert not types & {
        "aws_iam_role_policy",
        "aws_iam_user_policy",
        "aws_iam_group_policy",
        "aws_iam_user",
        "aws_iam_access_key",
    }


def test_every_iam_policy_is_covered_by_the_tftest_lint(version_dir: Path) -> None:
    text = _module_text(version_dir, "iam")
    policies = {n for t, n in RESOURCE.findall(text) if t == "aws_iam_policy"}
    assert policies, "the iam module should define policies"
    lint = (version_dir / "tests" / "iam" / "iam.tftest.hcl").read_text()
    lint_block = lint.split('run "no_policy_uses_a_wildcard', 1)[1].split("\nrun ", 1)[0]
    for name in policies:
        assert f"aws_iam_policy.{name}," in lint_block, f"aws_iam_policy.{name} is not linted"


# --- Secrets -----------------------------------------------------------------------------------


def test_database_never_sets_a_password(version_dir: Path) -> None:
    text = _module_text(version_dir, "database")
    assert "manage_master_user_password = true" in text
    assert not re.search(r"^\s*password(_wo)?\s*=", text, re.MULTILINE)


def test_secret_values_are_never_output(version_dir: Path) -> None:
    for module in MODULES:
        outputs = (version_dir / "modules" / module / "outputs.tf").read_text()
        assert not re.search(r"master_user_secret\[0\]\.(kms_key_id|secret_status)", outputs)
        assert "password" not in outputs.lower()
