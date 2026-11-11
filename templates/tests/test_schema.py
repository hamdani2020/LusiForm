"""Parameter schema and validator (startup-template tasks 2.1 to 2.3)."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest

from template_tools.schema import (
    SchemaError,
    apply_defaults,
    defaults,
    load_schema,
    parameter_paths,
    parameter_spec,
    validate_parameters,
)

TEMPLATES_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATHS = sorted((TEMPLATES_ROOT / "startup").glob("*/schema.json"))
UI_VALUES = json.loads(
    (Path(__file__).parent / "data" / "architecture_stage_values.json").read_text()
)

EXPECTED_PARAMETERS = [
    "network.az_count",
    "compute.task_size",
    "compute.min_tasks",
    "compute.max_tasks",
    "database.instance_class",
    "database.storage_gb",
    "database.backup_retention_days",
    "monitoring.log_retention_days",
]

# Independent of schema.json on purpose: a bound edited there must also be edited here.
BOUNDS = {
    "compute.min_tasks": (1, 10),
    "compute.max_tasks": (2, 20),
    "database.storage_gb": (20, 1000),
    "database.backup_retention_days": (1, 35),
}


@pytest.fixture(params=SCHEMA_PATHS, ids=lambda p: p.parent.name)
def schema_path(request: pytest.FixtureRequest) -> Path:
    path: Path = request.param
    return path


@pytest.fixture
def schema(schema_path: Path) -> dict[str, Any]:
    return load_schema(schema_path)


def _with(schema: dict[str, Any], path: str, value: object) -> dict[str, Any]:
    params = defaults(schema)
    module, _, name = path.partition(".")
    params[module][name] = value
    return params


def _only_error(schema: dict[str, Any], params: dict[str, Any]) -> str:
    errors = validate_parameters(schema, params)
    assert len(errors) == 1, errors
    return errors[0].message


# --- 2.1 the schema ----------------------------------------------------------------------


def test_schema_has_exactly_the_eight_parameters(schema: dict[str, Any]) -> None:
    # Adding a parameter is a deliberate template change: update this list with it.
    assert parameter_paths(schema) == EXPECTED_PARAMETERS


def test_every_parameter_is_typed_constrained_and_defaulted(schema: dict[str, Any]) -> None:
    for path in parameter_paths(schema):
        spec = parameter_spec(schema, path)
        assert spec["type"] in {"integer", "string"}, path
        assert "default" in spec, path
        assert spec["title"] and spec["description"], path
        assert "enum" in spec or ("minimum" in spec and "maximum" in spec), path


def test_no_free_form_strings(schema: dict[str, Any]) -> None:
    # A string parameter without an enum would let free text reach the rendered output.
    for path in parameter_paths(schema):
        spec = parameter_spec(schema, path)
        if spec["type"] == "string":
            assert "enum" in spec, f"{path} is a free-form string"


def test_no_out_of_scope_parameters(schema: dict[str, Any]) -> None:
    forbidden = re.compile(
        r"cidr|nat|region|eks|aurora|elasticache|cloudfront|waf|graviton|arm|account|vpc",
        re.IGNORECASE,
    )
    for path in parameter_paths(schema):
        assert not forbidden.search(path.split(".", 1)[1]), path
    assert set(schema["properties"]) == {"network", "compute", "database", "monitoring"}


def test_modules_and_additional_properties_are_closed(schema: dict[str, Any]) -> None:
    assert schema["additionalProperties"] is False
    for module_schema in schema["properties"].values():
        assert module_schema["additionalProperties"] is False


def test_cross_field_rule_is_declared(schema: dict[str, Any]) -> None:
    assert schema["x-rules"] == [
        {
            "id": "max_tasks_gte_min_tasks",
            "left": "compute.max_tasks",
            "operator": ">=",
            "right": "compute.min_tasks",
        }
    ]


def test_log_retention_values_are_valid_cloudwatch_values(schema: dict[str, Any]) -> None:
    cloudwatch = {1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192}
    values = set(parameter_spec(schema, "monitoring.log_retention_days")["enum"])
    assert values <= cloudwatch
    assert min(values) == 7 and max(values) == 365


# --- 2.2 / 2.3 the validator -------------------------------------------------------------


def test_defaults_are_valid(schema: dict[str, Any]) -> None:
    assert validate_parameters(schema, defaults(schema)) == []


def test_apply_defaults_fills_missing_without_mutating(schema: dict[str, Any]) -> None:
    given = {"compute": {"min_tasks": 3}}
    snapshot = copy.deepcopy(given)
    filled = apply_defaults(schema, given)
    assert given == snapshot
    assert filled["compute"]["min_tasks"] == 3
    assert filled["compute"]["max_tasks"] == 6
    assert validate_parameters(schema, filled) == []


def test_minimums_and_maximums_pass(schema: dict[str, Any]) -> None:
    for path, (low, high) in BOUNDS.items():
        for value in (low, high):
            params = _with(schema, path, value)
            # Keep the cross-field rule satisfiable at the extremes.
            params["compute"]["min_tasks"] = min(params["compute"]["min_tasks"], 2)
            params["compute"]["max_tasks"] = max(params["compute"]["max_tasks"], 2)
            assert validate_parameters(schema, params) == [], (path, value)


def test_schema_bounds_match_the_expected_table(schema: dict[str, Any]) -> None:
    for path, (low, high) in BOUNDS.items():
        spec = parameter_spec(schema, path)
        assert (spec["minimum"], spec["maximum"]) == (low, high), path


@pytest.mark.parametrize(
    ("path", "value"),
    [(p, v) for p, (lo, hi) in BOUNDS.items() for v in (lo - 1, hi + 1)],
)
def test_out_of_range_is_rejected_naming_parameter_and_bound(
    schema: dict[str, Any], path: str, value: int
) -> None:
    low, high = BOUNDS[path]
    message = _only_error(schema, _with(schema, path, value))
    assert message == f"{path} must be between {low} and {high} (got {value})"


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("network.az_count", 3),
        ("network.az_count", 0),
        ("compute.task_size", "4vcpu-8gb"),
        ("database.instance_class", "db.r6g.large"),
        ("monitoring.log_retention_days", 8),
        ("monitoring.log_retention_days", 60),
        ("monitoring.log_retention_days", 180),
        ("monitoring.log_retention_days", 3650),
    ],
)
def test_value_outside_allowed_set_is_rejected(
    schema: dict[str, Any], path: str, value: object
) -> None:
    message = _only_error(schema, _with(schema, path, value))
    assert message.startswith(f"{path} must be one of: ")
    assert message.endswith(f"(got {value!r})")


@pytest.mark.parametrize(
    ("path", "value", "expected"),
    [
        ("compute.min_tasks", "2", "an integer"),
        ("compute.min_tasks", 2.5, "an integer"),
        ("compute.min_tasks", True, "an integer"),
        ("compute.min_tasks", None, "an integer"),
        ("network.az_count", "2", "an integer"),
        ("compute.task_size", 1, "a string"),
        ("database.instance_class", ["db.t4g.micro"], "a string"),
    ],
)
def test_wrong_type_is_rejected(
    schema: dict[str, Any], path: str, value: object, expected: str
) -> None:
    message = _only_error(schema, _with(schema, path, value))
    assert message.startswith(f"{path} must be {expected}")


def test_cross_field_rule_rejects_max_below_min(schema: dict[str, Any]) -> None:
    params = defaults(schema)
    params["compute"].update(min_tasks=5, max_tasks=3)
    message = _only_error(schema, params)
    assert message == (
        "compute.max_tasks must be greater than or equal to compute.min_tasks "
        "(got 3, but compute.min_tasks is 5)"
    )


def test_cross_field_rule_allows_equal_and_extremes(schema: dict[str, Any]) -> None:
    for low, high in [(4, 4), (10, 10), (1, 2), (10, 20)]:
        params = defaults(schema)
        params["compute"].update(min_tasks=low, max_tasks=high)
        assert validate_parameters(schema, params) == [], (low, high)


def test_cross_field_rule_skipped_when_an_operand_is_already_invalid(
    schema: dict[str, Any],
) -> None:
    params = defaults(schema)
    params["compute"].update(min_tasks=50, max_tasks=3)
    errors = validate_parameters(schema, params)
    assert [e.path for e in errors] == ["compute.min_tasks"]


def test_unknown_and_missing_parameters_are_rejected(schema: dict[str, Any]) -> None:
    params = defaults(schema)
    params["network"]["nat_mode"] = "shared"
    params["region"] = "eu-west-1"
    del params["database"]["storage_gb"]
    del params["monitoring"]
    messages = sorted(e.message for e in validate_parameters(schema, params))
    assert messages == [
        "database.storage_gb is required",
        "monitoring is required",
        "unknown parameter 'network.nat_mode'",
        "unknown parameter 'region'",
    ]


def test_non_object_inputs_are_rejected(schema: dict[str, Any]) -> None:
    assert [e.message for e in validate_parameters(schema, [])] == ["parameters must be an object"]
    params = defaults(schema)
    params["compute"] = "big"
    assert _only_error(schema, params) == "compute must be an object"


def test_all_errors_are_reported_together(schema: dict[str, Any]) -> None:
    params = defaults(schema)
    params["network"]["az_count"] = 3
    params["database"]["storage_gb"] = 5
    assert {e.path for e in validate_parameters(schema, params)} == {
        "network.az_count",
        "database.storage_gb",
    }


def test_rejected_values_are_not_echoed_in_full(schema: dict[str, Any]) -> None:
    message = _only_error(schema, _with(schema, "compute.task_size", "x" * 5000))
    assert len(message) < 300


def test_malformed_schema_is_refused(tmp_path: Path, schema_path: Path) -> None:
    broken = json.loads(schema_path.read_text())
    broken["properties"]["compute"]["properties"]["min_tasks"]["default"] = 99
    target = tmp_path / "schema.json"
    target.write_text(json.dumps(broken))
    with pytest.raises(SchemaError, match="compute.min_tasks"):
        load_schema(target)

    broken = json.loads(schema_path.read_text())
    broken["x-rules"][0]["right"] = "compute.nope"
    target.write_text(json.dumps(broken))
    with pytest.raises(SchemaError, match="unknown parameter"):
        load_schema(target)


# --- 2.3 UI and renderer share one definition --------------------------------------------


def test_schema_matches_architecture_stage_values(schema: dict[str, Any]) -> None:
    ui = {k: v for k, v in UI_VALUES.items() if not k.startswith("_")}
    assert sorted(ui) == sorted(parameter_paths(schema)), "UI and schema list different parameters"
    for path, shown in ui.items():
        spec = parameter_spec(schema, path)
        actual = {k: spec[k] for k in ("enum", "minimum", "maximum", "default") if k in spec}
        assert actual == shown, f"{path}: schema {actual} != Architecture stage {shown}"
