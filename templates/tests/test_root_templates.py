"""Root project templates and the reference render helper (startup-template tasks 8.1, 8.2).

The first group checks the templates as text and through Jinja2 (no Terraform needed). The
last group renders real projects and runs `terraform fmt`, `init -backend=false`,
`validate`, and `graph` on them with the pinned Terraform. Nothing plans or applies.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest
from fixtures import load_fixtures
from jinja2 import Environment, StrictUndefined, UndefinedError
from reference_render import (
    CONTEXT_NAMES,
    ROOT_TEMPLATES,
    build_context,
    environment,
    escape_markdown,
    render_project,
    write_project,
)
from tf_runner import INIT_TIMEOUT, lock_file, output, terraform

from template_tools.schema import load_schema, parameter_paths

TEMPLATES_ROOT = Path(__file__).resolve().parent.parent
VERSION_DIRS = sorted(p for p in (TEMPLATES_ROOT / "startup").iterdir() if p.is_dir())

EXPRESSION = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)
DOTTED_NAME = re.compile(r"^[a-z_]+(\.[a-z_]+)*$")

# The parameter sets are the template fixtures (fixtures/params/); fmt and validate run on the
# same projects in test_validators.py.
PARAM_SETS: dict[str, dict[str, Any]] = {
    name: fixture.parameters for name, fixture in load_fixtures(VERSION_DIRS[0]).items()
}


@pytest.fixture(params=VERSION_DIRS, ids=lambda p: p.name)
def version_dir(request: pytest.FixtureRequest) -> Path:
    path: Path = request.param
    return path


def _template_text(version_dir: Path, name: str) -> str:
    return (version_dir / "root" / f"{name}.tmpl").read_text(encoding="utf-8")


def _rendered_text(files: dict[str, bytes], name: str) -> str:
    return files[name].decode("utf-8")


# --- 8.1 the templates -------------------------------------------------------------------


def test_exactly_the_five_root_templates_exist(version_dir: Path) -> None:
    found = sorted(p.name for p in (version_dir / "root").iterdir())
    assert found == sorted(f"{name}.tmpl" for name in ROOT_TEMPLATES)


def test_templates_use_only_plain_expressions(version_dir: Path) -> None:
    # No block tags, comments, or filters: the output cannot depend on whitespace settings
    # or on filters the real renderer might not provide.
    for name in ROOT_TEMPLATES:
        text = _template_text(version_dir, name)
        assert "{%" not in text and "%}" not in text, f"{name}: block tag"
        assert "{#" not in text and "#}" not in text, f"{name}: Jinja comment"
        for expression in EXPRESSION.findall(text):
            assert DOTTED_NAME.match(expression.strip()), f"{name}: {expression.strip()!r}"
        stripped = EXPRESSION.sub("", text)
        assert "{{" not in stripped and "}}" not in stripped, f"{name}: unbalanced expression"


def test_templates_use_exactly_the_documented_context(version_dir: Path) -> None:
    used: set[str] = set()
    for name in ROOT_TEMPLATES:
        for expression in EXPRESSION.findall(_template_text(version_dir, name)):
            used.add(expression.strip().split(".")[0])
    assert used == set(CONTEXT_NAMES)


def test_module_parameters_in_templates_exist_in_the_schema(version_dir: Path) -> None:
    schema = load_schema(version_dir / "schema.json")
    known = set(parameter_paths(schema))
    seen: set[str] = set()
    for name in ROOT_TEMPLATES:
        for expression in EXPRESSION.findall(_template_text(version_dir, name)):
            parts = expression.strip().split(".")
            if parts[0] == "modules":
                assert len(parts) == 3, f"{name}: {expression.strip()!r}"
                seen.add(f"{parts[1]}.{parts[2]}")
    assert seen <= known, f"templates reference unknown parameters: {seen - known}"
    assert seen == known, f"parameters missing from the root templates: {known - seen}"


def test_free_text_names_are_used_only_in_the_readme(version_dir: Path) -> None:
    for name in ROOT_TEMPLATES:
        text = _template_text(version_dir, name)
        uses_names = "project_name" in text or "customer_name" in text
        assert uses_names == (name == "README.md"), name


def test_a_missing_context_value_is_an_error(version_dir: Path) -> None:
    context = build_context(version_dir, {})
    del context["name_prefix"]
    with pytest.raises(UndefinedError):
        environment().from_string(_template_text(version_dir, "variables.tf")).render(**context)


def test_trailing_newline_is_kept(version_dir: Path) -> None:
    # Jinja drops the final newline by default, which would fail `terraform fmt -check`.
    default = Environment(undefined=StrictUndefined, autoescape=False)  # noqa: S701
    text = _template_text(version_dir, "outputs.tf")
    assert not default.from_string(text).render().endswith("\n")
    assert environment().from_string(text).render().endswith("\n")


# --- 8.1 what the rendered root contains -------------------------------------------------


def test_root_declares_terraform_and_provider_constraints(version_dir: Path) -> None:
    meta = json.loads((version_dir / "template.json").read_text())
    main = _rendered_text(render_project(version_dir, {}), "main.tf")
    assert f'required_version = "{meta["terraform"]}"' in main
    assert f'version = "{meta["aws_provider"]}"' in main
    assert 'source  = "hashicorp/aws"' in main
    assert meta["terraform"] == ">= 1.10.0"


def test_backend_uses_s3_lock_file_and_no_account_specific_values(version_dir: Path) -> None:
    files = render_project(version_dir, {})
    main = _rendered_text(files, "main.tf")
    match = re.search(r'backend "s3" \{(.*?)\n  \}', main, re.DOTALL)
    assert match, "no S3 backend block"
    body = match.group(1)
    assert "use_lockfile = true" in body
    # Bucket, key, and region are supplied with -backend-config at init time.
    keys = set(re.findall(r"^\s*([a-z_]+)\s*=", body, re.MULTILINE))
    assert keys == {"use_lockfile", "encrypt"}
    for text in (_rendered_text(files, name) for name in ROOT_TEMPLATES):
        assert "dynamodb_table" not in text


def test_root_wires_the_five_modules_from_local_paths(version_dir: Path) -> None:
    main = _rendered_text(render_project(version_dir, {}), "main.tf")
    assert sorted(re.findall(r'^module "([a-z]+)"', main, re.MULTILINE)) == [
        "compute",
        "database",
        "iam",
        "monitoring",
        "network",
    ]
    assert sorted(re.findall(r'source = "(\./modules/[a-z]+)"', main)) == [
        "./modules/compute",
        "./modules/database",
        "./modules/iam",
        "./modules/monitoring",
        "./modules/network",
    ]


def test_every_resource_is_tagged_as_lusiform_managed(version_dir: Path) -> None:
    main = _rendered_text(render_project(version_dir, {}), "main.tf")
    assert '"lusiform-managed"          = "true"' in main
    assert '"lusiform-template-version" = "1.0.0"' in main


def test_container_image_is_required_and_has_no_registry_default(version_dir: Path) -> None:
    variables = _rendered_text(render_project(version_dir, {}), "variables.tf")
    block = re.search(r'variable "container_image" \{(.*?)\n\}', variables, re.DOTALL)
    assert block and "default" not in block.group(1)


def _variable_default(variables: str, name: str) -> str:
    block = re.search(rf'variable "{name}" \{{(.*?)\n\}}', variables, re.DOTALL)
    assert block, f"variable {name} missing"
    default = re.search(r"default\s*=\s*(.+)", block.group(1))
    assert default, f"variable {name} has no default"
    return default.group(1).strip()


@pytest.mark.parametrize("set_name", PARAM_SETS)
def test_parameter_values_are_written_as_defaults_and_in_the_tfvars_example(
    version_dir: Path, set_name: str
) -> None:
    schema = load_schema(version_dir / "schema.json")
    context = build_context(version_dir, PARAM_SETS[set_name])
    files = render_project(version_dir, PARAM_SETS[set_name])
    variables = _rendered_text(files, "variables.tf")
    tfvars = _rendered_text(files, "terraform.tfvars.example")
    for path in parameter_paths(schema):
        module, name = path.split(".")
        value = context["modules"][module][name]
        expected = json.dumps(value)
        assert _variable_default(variables, name) == expected, path
        assert re.search(rf"^{name}\s*=\s*{re.escape(expected)}$", tfvars, re.MULTILINE), path


def test_region_and_name_prefix_are_written(version_dir: Path) -> None:
    files = render_project(version_dir, {}, region="eu-west-1", name_prefix="lf-ffff0000")
    variables = _rendered_text(files, "variables.tf")
    assert _variable_default(variables, "region") == '"eu-west-1"'
    assert _variable_default(variables, "name_prefix") == '"lf-ffff0000"'
    tfvars = _rendered_text(files, "terraform.tfvars.example")
    assert 'region                = "eu-west-1"' in tfvars


def test_deletion_protection_defaults_to_on(version_dir: Path) -> None:
    variables = _rendered_text(render_project(version_dir, {}), "variables.tf")
    assert _variable_default(variables, "deletion_protection") == "true"
    assert _variable_default(variables, "skip_final_snapshot") == "false"


def test_outputs_never_expose_a_secret_value(version_dir: Path) -> None:
    outputs = _rendered_text(render_project(version_dir, {}), "outputs.tf")
    assert "sensitive" not in outputs
    assert not re.search(r"password|secret_string|master_user_secret\[", outputs, re.IGNORECASE)
    assert "database_secret_arn" in outputs  # the ARN only


# --- 8.2 the render helper ---------------------------------------------------------------


def test_project_layout(version_dir: Path) -> None:
    files = render_project(version_dir, {})
    expected_root = set(ROOT_TEMPLATES)
    assert {p for p in files if "/" not in p} == expected_root
    modules = sorted({p.split("/")[1] for p in files if p.startswith("modules/")})
    assert modules == ["compute", "database", "iam", "monitoring", "network"]
    assert all(p.endswith(".tf") for p in files if p.startswith("modules/"))
    assert list(files) == sorted(files), "files are returned sorted by path"


def test_no_module_tests_or_fixtures_are_rendered(version_dir: Path) -> None:
    for path in render_project(version_dir, {}):
        assert "tftest" not in path and "fixtures" not in path and "tests/" not in path


@pytest.mark.parametrize("set_name", PARAM_SETS)
def test_rendering_is_deterministic(version_dir: Path, set_name: str) -> None:
    first = render_project(version_dir, PARAM_SETS[set_name])
    second = render_project(version_dir, copy.deepcopy(PARAM_SETS[set_name]))
    assert first == second


def test_output_is_utf8_lf_with_a_final_newline(version_dir: Path) -> None:
    for path, content in render_project(version_dir, {}).items():
        text = content.decode("utf-8")
        assert "\r" not in text, path
        assert text.endswith("\n") and not text.endswith("\n\n"), path
        assert "\t" not in text, path


def test_invalid_parameters_are_refused_before_rendering(version_dir: Path) -> None:
    with pytest.raises(ValueError, match="compute.min_tasks must be between 1 and 10"):
        render_project(version_dir, {"compute": {"min_tasks": 11}})
    with pytest.raises(ValueError, match="network.az_count"):
        render_project(version_dir, {"network": {"az_count": 3}})


def test_rendered_output_has_no_credentials_or_account_ids(version_dir: Path) -> None:
    for path, content in render_project(version_dir, {}).items():
        text = content.decode("utf-8")
        assert not re.search(r"(?<![\w-])\d{12}(?![\w-])", text), f"{path}: 12-digit number"
        assert not re.search(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b", text), f"{path}: access key"
        assert not re.search(r"arn:aws[a-z-]*:[a-z0-9-]+:[a-z0-9-]*:\d{12}:", text), path


def test_no_certification_or_sla_claims(version_dir: Path) -> None:
    pattern = re.compile(
        r"SOC ?2|PCI|HIPAA|ISO ?27001|FedRAMP|\bSLA\b|uptime|guarantee|compliant|compliance",
        re.IGNORECASE,
    )
    for path, content in render_project(version_dir, {}).items():
        if not path.startswith("modules/"):
            assert not pattern.search(content.decode("utf-8")), path


# --- Free text is data (requirement 3.5) -------------------------------------------------


HOSTILE = 'Evil"; ${var.x} $(rm -rf /) {{ 7*7 }} {% if 1 %} [x](http://evil) <b>x</b> `id`'


def test_free_text_names_reach_only_the_readme_and_are_escaped(version_dir: Path) -> None:
    files = render_project(version_dir, {}, project_name=HOSTILE, customer_name=HOSTILE)
    for path, content in files.items():
        text = content.decode("utf-8")
        if path == "README.md":
            assert "{{ 7*7 }}" not in text and "{% if 1 %}" not in text
            assert "[x](http://evil)" not in text and "<b>x</b>" not in text
            assert "\\{\\{ 7\\*7 \\}\\}" in text
        else:
            for fragment in ("Evil", "rm -rf", "7*7", "http://evil", "<b>"):
                assert fragment not in text, f"{path} contains {fragment!r}"


def test_markdown_escaping_covers_the_syntax_characters() -> None:
    assert escape_markdown("a*b_c`d[e](f)#g|h<i>") == "a\\*b\\_c\\`d\\[e\\]\\(f\\)\\#g\\|h\\<i\\>"
    assert "\n" not in escape_markdown("line one\nline two")


def test_names_do_not_change_any_terraform_file(version_dir: Path) -> None:
    plain = render_project(version_dir, {}, project_name="A", customer_name="B")
    other = render_project(version_dir, {}, project_name=HOSTILE, customer_name=HOSTILE)
    assert {k: v for k, v in plain.items() if k != "README.md"} == {
        k: v for k, v in other.items() if k != "README.md"
    }


# --- 8.2 the rendered project builds a dependency graph ----------------------------------


@pytest.mark.parametrize("set_name", ["default", "az1"])
def test_rendered_project_has_no_dependency_cycle(
    version_dir: Path,
    set_name: str,
    tmp_path: Path,
) -> None:
    # monitoring and compute reference each other's outputs, so check the graph builds.
    # `terraform graph` needs an initialised backend, so this copy drops the S3 backend
    # block (the dependency structure does not depend on it) and initialises locally.
    files = render_project(version_dir, PARAM_SETS[set_name])
    main = files["main.tf"].decode("utf-8")
    stripped = re.sub(
        r'\n  # State location.*?\n  backend "s3" \{.*?\n  \}\n', "\n", main, flags=re.DOTALL
    )
    assert 'backend "s3"' not in stripped and stripped != main
    files["main.tf"] = stripped.encode("utf-8")
    write_project(files, tmp_path)
    lock = lock_file(version_dir)
    if lock.is_file():
        shutil.copy(lock, tmp_path / ".terraform.lock.hcl")
    init = terraform(["init", "-input=false", "-no-color"], tmp_path, INIT_TIMEOUT)
    assert init.returncode == 0, f"terraform init failed:\n{output(init)}"
    result = terraform(["graph", "-no-color"], tmp_path)
    assert result.returncode == 0, f"terraform graph failed:\n{output(result)}"
    assert "Cycle" not in result.stdout + result.stderr
