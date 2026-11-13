"""Reference renderer for the startup template. TEST ONLY.

This exists so the template can be validated (fmt, validate, tflint, Checkov) before the
real renderer exists. The real renderer is built in the generation-pipeline spec; it must
produce byte-identical output for the same inputs, and its golden tests replace this
helper. Nothing outside the template tests may import it.

The Jinja2 environment below is the contract the real renderer must follow:

- `StrictUndefined`: a template that uses a name the context does not supply is an error.
- autoescape off: the output is HCL and Markdown, not HTML.
- `keep_trailing_newline=True`: Jinja drops a file's final newline by default, which would
  fail `terraform fmt -check`.
- no `trim_blocks` / `lstrip_blocks`: the templates use plain `{{ dotted.name }}`
  expressions only (no block tags, comments, or filters), so whitespace settings cannot
  change the output.

Context keys the root templates may use:

    template_version        "1.0.0"
    terraform_constraint    ">= 1.10.0"      from template.json
    aws_provider_constraint "~> 5.47"        from template.json
    region                  "us-east-1"      the project's region
    name_prefix             "lf-0a1b2c3d"    derived from the project id, never typed text
    project_name            display text, already escaped for Markdown (README only)
    customer_name           display text, already escaped for Markdown (README only)
    modules                 {"network": {...}, "compute": {...}, "database": {...},
                             "monitoring": {...}}  the parameters, nested by module
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, StrictUndefined

from template_tools.schema import apply_defaults, load_schema, validate_parameters

ROOT_TEMPLATES = (
    "main.tf",
    "variables.tf",
    "outputs.tf",
    "terraform.tfvars.example",
    "README.md",
)

# Context names the root templates are allowed to reference. A test checks the templates
# use nothing else, so the real renderer's context contract stays small and explicit.
CONTEXT_NAMES = (
    "template_version",
    "terraform_constraint",
    "aws_provider_constraint",
    "region",
    "name_prefix",
    "project_name",
    "customer_name",
    "modules",
)

_MARKDOWN_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+!|<>~])")


def escape_markdown(text: str) -> str:
    """Backslash-escape Markdown syntax so display text cannot change the document."""
    return _MARKDOWN_SPECIAL.sub(r"\\\1", text).replace("\r", " ").replace("\n", " ")


def environment() -> Environment:
    return Environment(
        undefined=StrictUndefined,
        autoescape=False,  # noqa: S701  (the output is HCL and Markdown, not HTML)
        keep_trailing_newline=True,
    )


def build_context(
    version_dir: Path,
    params: dict[str, Any],
    *,
    region: str = "us-east-1",
    name_prefix: str = "lf-0a1b2c3d",
    project_name: str = "Example project",
    customer_name: str = "Example customer",
) -> dict[str, Any]:
    """Validate the parameters against the schema and build the template context."""
    schema = load_schema(version_dir / "schema.json")
    full = apply_defaults(schema, params)
    errors = validate_parameters(schema, full)
    if errors:
        raise ValueError("; ".join(e.message for e in errors))
    meta = json.loads((version_dir / "template.json").read_text())
    return {
        "template_version": meta["version"],
        "terraform_constraint": meta["terraform"],
        "aws_provider_constraint": meta["aws_provider"],
        "region": region,
        "name_prefix": name_prefix,
        "project_name": escape_markdown(project_name),
        "customer_name": escape_markdown(customer_name),
        "modules": full,
    }


def render_project(version_dir: Path, params: dict[str, Any], **kwargs: str) -> dict[str, bytes]:
    """Render the project: root files plus the module `.tf` files, as `{path: bytes}`.

    Paths use `/` and are returned sorted. Only `modules/<name>/*.tf` is copied from the
    template; module tests and fixtures never reach a rendered project.
    """
    context = build_context(version_dir, params, **kwargs)
    env = environment()
    files: dict[str, bytes] = {}

    for name in ROOT_TEMPLATES:
        source = (version_dir / "root" / f"{name}.tmpl").read_text(encoding="utf-8")
        files[name] = env.from_string(source).render(**context).encode("utf-8")

    modules_dir = version_dir / "modules"
    for module in sorted(p for p in modules_dir.iterdir() if p.is_dir()):
        for tf_file in sorted(module.glob("*.tf")):
            files[f"modules/{module.name}/{tf_file.name}"] = tf_file.read_bytes()

    return dict(sorted(files.items()))


def write_project(files: dict[str, bytes], destination: Path) -> None:
    """Write a rendered project to disk."""
    for relative, content in files.items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
