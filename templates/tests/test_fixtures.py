"""The parameter fixtures (startup-template task 10.1)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fixtures import VERSION_DIRS, load_fixtures, render_fixture

from template_tools.schema import (
    apply_defaults,
    defaults,
    load_schema,
    parameter_paths,
    parameter_spec,
    validate_parameters,
)

EXPECTED = {"default", "minimum", "maximum", "az1", "az2"}
FIELDS = {
    "name",
    "description",
    "region",
    "name_prefix",
    "project_name",
    "customer_name",
    "parameters",
}


@pytest.fixture(params=VERSION_DIRS, ids=lambda p: p.name)
def version_dir(request: pytest.FixtureRequest) -> Path:
    path: Path = request.param
    return path


def test_the_five_required_fixtures_exist(version_dir: Path) -> None:
    assert set(load_fixtures(version_dir)) == EXPECTED


def test_every_fixture_is_valid_against_the_schema(version_dir: Path) -> None:
    schema = load_schema(version_dir / "schema.json")
    for fixture in load_fixtures(version_dir).values():
        full = apply_defaults(schema, fixture.parameters)
        assert validate_parameters(schema, full) == [], fixture.name


def test_fixture_files_have_only_the_known_fields(version_dir: Path) -> None:
    for path in (version_dir / "fixtures" / "params").glob("*.json"):
        import json

        assert set(json.loads(path.read_text())) == FIELDS, path.name


def test_names_and_prefixes_are_unique_and_valid(version_dir: Path) -> None:
    fixtures = load_fixtures(version_dir).values()
    prefixes = [f.name_prefix for f in fixtures]
    assert len(prefixes) == len(set(prefixes))
    for prefix in prefixes:
        assert re.fullmatch(r"lf-[a-z0-9]([a-z0-9-]{0,19}[a-z0-9])?", prefix), prefix
    for fixture in fixtures:
        assert fixture.description, fixture.name


def test_the_default_fixture_is_the_schema_defaults(version_dir: Path) -> None:
    schema = load_schema(version_dir / "schema.json")
    fixture = load_fixtures(version_dir)["default"]
    assert fixture.parameters == {}
    assert apply_defaults(schema, fixture.parameters) == defaults(schema)


def test_minimum_is_the_bottom_of_every_range(version_dir: Path) -> None:
    schema = load_schema(version_dir / "schema.json")
    full = apply_defaults(schema, load_fixtures(version_dir)["minimum"].parameters)
    for path in parameter_paths(schema):
        spec = parameter_spec(schema, path)
        module, name = path.split(".")
        value = full[module][name]
        if "minimum" in spec:
            assert value == spec["minimum"], path
        elif spec["type"] == "integer":
            assert value == min(spec["enum"]), path
    assert full["compute"]["task_size"] == parameter_spec(schema, "compute.task_size")["enum"][0]
    assert (
        full["database"]["instance_class"]
        == parameter_spec(schema, "database.instance_class")["enum"][0]
    )


def test_maximum_is_the_top_of_every_range(version_dir: Path) -> None:
    schema = load_schema(version_dir / "schema.json")
    full = apply_defaults(schema, load_fixtures(version_dir)["maximum"].parameters)
    for path in parameter_paths(schema):
        spec = parameter_spec(schema, path)
        module, name = path.split(".")
        value = full[module][name]
        if "maximum" in spec:
            assert value == spec["maximum"], path
        elif spec["type"] == "integer":
            assert value == max(spec["enum"]), path
    assert full["compute"]["task_size"] == parameter_spec(schema, "compute.task_size")["enum"][-1]
    assert (
        full["database"]["instance_class"]
        == parameter_spec(schema, "database.instance_class")["enum"][-1]
    )


def test_zone_counts(version_dir: Path) -> None:
    schema = load_schema(version_dir / "schema.json")
    fixtures = load_fixtures(version_dir)
    counts = {
        name: apply_defaults(schema, f.parameters)["network"]["az_count"]
        for name, f in fixtures.items()
    }
    assert counts == {"default": 1, "minimum": 1, "maximum": 2, "az1": 1, "az2": 2}


def test_fixtures_cover_both_zone_counts_and_several_regions(version_dir: Path) -> None:
    fixtures = load_fixtures(version_dir).values()
    assert {f.region for f in fixtures} >= {"us-east-1", "eu-west-1", "us-west-2"}


def test_az1_and_az2_differ_from_the_extremes(version_dir: Path) -> None:
    schema = load_schema(version_dir / "schema.json")
    fixtures = load_fixtures(version_dir)
    full = {n: apply_defaults(schema, f.parameters) for n, f in fixtures.items()}
    for name in ("az1", "az2"):
        for other in ("minimum", "maximum"):
            assert full[name] != full[other], (name, other)
    assert full["az1"]["network"] != full["az2"]["network"]


def test_every_fixture_renders(version_dir: Path) -> None:
    for fixture in load_fixtures(version_dir).values():
        files = render_fixture(version_dir, fixture)
        assert "main.tf" in files and "README.md" in files, fixture.name
        variables = files["variables.tf"].decode()
        assert f'default     = "{fixture.region}"' in variables, fixture.name
        assert f'default     = "{fixture.name_prefix}"' in variables, fixture.name
