"""Credential and account-ID scan, and free-text isolation (startup-template task 10.4).

Every rendered project, and every stored golden file, is scanned for access keys, secret
material, literal passwords, 12-digit account IDs, and ARNs that contain an account. None may
appear. The scanner is tested with known-bad text so a clean result means something.

Free text is data (requirement 3.5): consultant-typed names reach the README only, escaped.
They never reach a resource name, a file name, or any Terraform file. Intake notes are not an
input to rendering at all.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest
from fixtures import VERSION_DIRS, load_fixtures, render_fixture
from reference_render import CONTEXT_NAMES, build_context, render_project

ACCOUNT_ID = re.compile(r"(?<![\w.-])\d{12}(?![\w.-])")
ARN_WITH_ACCOUNT = re.compile(r"arn:aws[a-z-]*:[a-z0-9-]+:[a-z0-9-]*:\d{12}:")
ACCESS_KEY = re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA|ANPA)[A-Z0-9]{16}\b")
SECRET_KEY_NAME = re.compile(r"(?i)aws_secret_access_key|secret_access_key|aws_session_token")
PRIVATE_KEY = re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----")
LITERAL_PASSWORD = re.compile(
    r"(?im)^\s*(?:master_)?(?:password|passwd|secret|token|api_?key)\s*=\s*\"[^\"$\s][^\"]*\""
)
URL_CREDENTIALS = re.compile(r"[a-z]+://[^/\s:@]+:[^/\s@]+@")

PATTERNS = {
    "account id": ACCOUNT_ID,
    "arn with account": ARN_WITH_ACCOUNT,
    "access key": ACCESS_KEY,
    "secret key name": SECRET_KEY_NAME,
    "private key": PRIVATE_KEY,
    "literal password": LITERAL_PASSWORD,
    "url credentials": URL_CREDENTIALS,
}

HOSTILE = (
    'Evil"; ${var.x} $(rm -rf /) {{ 7*7 }} {% if 1 %} [x](http://evil) <b>x</b> `id` '
    "../../etc/passwd lf-pwn"
)
HOSTILE_FRAGMENTS = ("Evil", "rm -rf", "7*7", "etc/passwd", "lf-pwn", "http://evil", "<b>")


def scan_text(text: str) -> list[str]:
    return [label for label, pattern in PATTERNS.items() if pattern.search(text)]


@pytest.fixture(params=VERSION_DIRS, ids=lambda p: p.name)
def version_dir(request: pytest.FixtureRequest) -> Path:
    path: Path = request.param
    return path


# --- The scanner has teeth ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("account = 123456789012", "account id"),
        ('role = "arn:aws:iam::123456789012:role/x"', "arn with account"),
        ("key = AKIAIOSFODNN7EXAMPLE", "access key"),
        ("temporary = ASIAIOSFODNN7EXAMPLE", "access key"),
        ("aws_secret_access_key = abc", "secret key name"),
        ("-----BEGIN RSA PRIVATE KEY-----", "private key"),
        ('password = "hunter2hunter2"', "literal password"),
        ('  master_password = "x1y2z3"', "literal password"),
        ('api_key = "abcdef"', "literal password"),
        ("see https://user:pass@example.com/path", "url credentials"),
    ],
)
def test_the_scanner_detects_known_bad_text(text: str, expected: str) -> None:
    assert expected in scan_text(text)


@pytest.mark.parametrize(
    "text",
    [
        "manage_master_user_password = true",
        "password = var.db_password",
        'default = "registry.example.com/your-team/your-app:1.0.0"',
        'terraform init -backend-config="bucket=<state-bucket>"',
        "size = 1073741824",
        "secret_arn = module.database.master_user_secret_arn",
        'arn = "arn:${local.partition}:iam::${local.account_id}:root"',
        "v1.2.3 and 10.0.0.0/16 and 2026",
    ],
)
def test_the_scanner_ignores_safe_text(text: str) -> None:
    assert scan_text(text) == []


# --- Rendered output and golden files are clean ------------------------------------------


def test_rendered_output_is_clean_for_every_fixture(version_dir: Path) -> None:
    fixtures = load_fixtures(version_dir)
    per_project = 5 + len(list(version_dir.glob("modules/*/*.tf")))  # root files + module files
    checked = 0
    for name, fixture in fixtures.items():
        for path, content in render_fixture(version_dir, fixture).items():
            checked += 1
            assert scan_text(content.decode("utf-8")) == [], f"{name}/{path}"
    assert checked == len(fixtures) * per_project, "the scan should cover every rendered file"


def test_golden_files_are_clean(version_dir: Path) -> None:
    checked = 0
    for path in (version_dir / "fixtures" / "golden").rglob("*"):
        if path.is_file():
            checked += 1
            assert scan_text(path.read_text()) == [], str(path)
    assert checked >= 5 * 6


def test_the_template_modules_and_root_templates_are_clean(version_dir: Path) -> None:
    for pattern in ("modules/*/*.tf", "root/*.tmpl", "tflint.hcl"):
        for path in version_dir.glob(pattern):
            assert scan_text(path.read_text()) == [], str(path)


def test_the_policy_and_catalog_hold_no_account_or_credentials(version_dir: Path) -> None:
    for name in ("sandbox-policy.json", "iam-catalog.json", "inventory.json", "template.json"):
        assert scan_text((version_dir / name).read_text()) == [], name


def test_a_planted_credential_in_a_module_would_be_found(version_dir: Path, tmp_path: Path) -> None:
    # End to end: plant one of each in a copy of a rendered project and scan it.
    files = render_fixture(version_dir, load_fixtures(version_dir)["default"])
    planted = (
        files["modules/compute/main.tf"].decode() + '\nlocals { k = "AKIAIOSFODNN7EXAMPLE" }\n'
    )
    assert "access key" in scan_text(planted)
    planted = files["main.tf"].decode() + "\n# account 123456789012\n"
    assert "account id" in scan_text(planted)


# --- Free text is data -------------------------------------------------------------------


def test_names_reach_only_the_readme_for_every_fixture(version_dir: Path) -> None:
    for name, fixture in load_fixtures(version_dir).items():
        normal = render_fixture(version_dir, fixture)
        hostile = render_project(
            version_dir,
            fixture.parameters,
            region=fixture.region,
            name_prefix=fixture.name_prefix,
            project_name=HOSTILE,
            customer_name=HOSTILE,
        )
        assert list(normal) == list(hostile), f"{name}: file names depend on the names"
        for path, content in hostile.items():
            if path == "README.md":
                continue
            assert content == normal[path], f"{name}/{path} depends on the names"
            text = content.decode("utf-8")
            for fragment in HOSTILE_FRAGMENTS:
                assert fragment not in text, f"{name}/{path} contains {fragment!r}"


def test_hostile_names_are_escaped_in_the_readme(version_dir: Path) -> None:
    fixture = load_fixtures(version_dir)["default"]
    readme = render_project(
        version_dir,
        fixture.parameters,
        name_prefix=fixture.name_prefix,
        project_name=HOSTILE,
        customer_name=HOSTILE,
    )["README.md"].decode()
    assert "{{ 7*7 }}" not in readme and "{% if 1 %}" not in readme
    assert "[x](http://evil)" not in readme and "<b>x</b>" not in readme
    assert "\\{\\{ 7\\*7 \\}\\}" in readme


def test_no_file_name_or_resource_name_contains_a_name(version_dir: Path) -> None:
    for name, fixture in load_fixtures(version_dir).items():
        for path in render_fixture(version_dir, fixture):
            assert fixture.project_name.lower().replace(" ", "") not in path.lower(), (name, path)
            assert re.fullmatch(r"[A-Za-z0-9_./-]+", path), path


def test_names_are_not_used_to_build_the_name_prefix(version_dir: Path) -> None:
    # name_prefix is its own input, derived from the project id upstream, never from typed text.
    for fixture in load_fixtures(version_dir).values():
        slug = re.sub(r"[^a-z0-9]", "", fixture.project_name.lower())
        assert slug not in fixture.name_prefix


def test_intake_notes_are_not_an_input_to_rendering(version_dir: Path) -> None:
    parameters = set(inspect.signature(render_project).parameters)
    parameters |= set(inspect.signature(build_context).parameters)
    assert not {p for p in parameters if "note" in p.lower() or "intake" in p.lower()}
    fixture = load_fixtures(version_dir)["default"]
    context = build_context(version_dir, fixture.parameters)
    assert set(context) == set(CONTEXT_NAMES), (
        "nothing but the documented context reaches a template"
    )


def test_free_text_cannot_inject_template_syntax_into_a_terraform_file(version_dir: Path) -> None:
    fixture = load_fixtures(version_dir)["default"]
    output = render_project(
        version_dir,
        fixture.parameters,
        name_prefix=fixture.name_prefix,
        project_name="{{ name_prefix }}{% for x in y %}",
        customer_name="${var.region}",
    )
    for path, content in output.items():
        if path != "README.md":
            assert b"{%" not in content, path
    readme = output["README.md"].decode()
    # Escaped as text and never evaluated: the expression was not replaced by the prefix.
    assert "\\{\\{ name\\_prefix \\}\\}" in readme
    assert "lf-fix-default{" not in readme
    assert "$\\{var.region\\}" in readme
