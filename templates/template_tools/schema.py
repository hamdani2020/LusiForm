"""Parameter schema loading and validation for the startup template.

`schema.json` is the single definition of the parameters a consultant may adjust. This
module reads the subset of JSON Schema that file uses (object nesting, `type`, `enum`,
`minimum`, `maximum`, `default`, `additionalProperties`, `required`) plus the `x-rules`
extension for cross-field rules. It has no third-party dependencies so the API, the
worker, and tests can all use it.

Parameters are addressed as `<module>.<name>`, for example `compute.min_tasks`. Every
error names the parameter and the bound it broke (requirement 2.3).
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

Schema = dict[str, Any]
Params = dict[str, Any]

_MAX_ECHO = 40
_OPERATORS = {">="}


class SchemaError(ValueError):
    """The schema file itself is malformed or uses something this validator lacks."""


@dataclass(frozen=True)
class ParameterError:
    """One validation failure. `path` is the dotted parameter name (or a module name)."""

    path: str
    message: str


def load_schema(path: Path) -> Schema:
    """Read a schema file and check it only uses what the validator understands."""
    schema: Schema = json.loads(path.read_text())
    _check_schema(schema)
    return schema


def parameter_paths(schema: Schema) -> list[str]:
    """Every parameter as `<module>.<name>`, in schema order."""
    return [f"{module}.{name}" for module, name, _ in _parameters(schema)]


def parameter_spec(schema: Schema, path: str) -> Schema:
    """The schema entry for one dotted parameter name."""
    module, _, name = path.partition(".")
    try:
        spec: Schema = schema["properties"][module]["properties"][name]
    except KeyError:
        raise KeyError(f"unknown parameter {path!r}") from None
    return spec


def defaults(schema: Schema) -> Params:
    """The default value of every parameter, nested by module."""
    result: Params = {}
    for module, name, spec in _parameters(schema):
        result.setdefault(module, {})[name] = copy.deepcopy(spec["default"])
    return result


def apply_defaults(schema: Schema, params: Params) -> Params:
    """Return a copy of `params` with missing parameters filled from the defaults.

    Unknown keys and wrongly typed modules are left alone so validation reports them.
    """
    result = copy.deepcopy(params)
    for module, values in defaults(schema).items():
        current = result.setdefault(module, {})
        if not isinstance(current, dict):
            continue
        for name, value in values.items():
            current.setdefault(name, value)
    return result


def validate_parameters(schema: Schema, params: object) -> list[ParameterError]:
    """Validate a full parameter set. An empty list means it is valid."""
    errors: list[ParameterError] = []
    if not isinstance(params, dict):
        return [ParameterError("", "parameters must be an object")]

    modules: Schema = schema["properties"]
    for key in params:
        if key not in modules:
            errors.append(ParameterError(str(key), f"unknown parameter {_echo(key)}"))

    for module, module_schema in modules.items():
        if module not in params:
            errors.append(ParameterError(module, f"{module} is required"))
            continue
        values = params[module]
        if not isinstance(values, dict):
            errors.append(ParameterError(module, f"{module} must be an object"))
            continue
        for key in values:
            if key not in module_schema["properties"]:
                errors.append(
                    ParameterError(
                        f"{module}.{key}", f"unknown parameter {_echo(f'{module}.{key}')}"
                    )
                )
        for name, spec in module_schema["properties"].items():
            path = f"{module}.{name}"
            if name not in values:
                errors.append(ParameterError(path, f"{path} is required"))
                continue
            error = _check_value(path, spec, values[name])
            if error is not None:
                errors.append(error)

    errors.extend(_check_rules(schema, params, errors))
    return errors


# ---------------------------------------------------------------------------
# Internals


def _parameters(schema: Schema) -> list[tuple[str, str, Schema]]:
    return [
        (module, name, spec)
        for module, module_schema in schema["properties"].items()
        for name, spec in module_schema["properties"].items()
    ]


def _echo(value: object) -> str:
    """A bounded representation of a rejected value for an error message."""
    text = repr(value)
    return text if len(text) <= _MAX_ECHO else text[: _MAX_ECHO - 3] + "..."


def _is_type(value: object, type_name: str) -> bool:
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "string":
        return isinstance(value, str)
    raise SchemaError(f"unsupported type {type_name!r}")


def _check_value(path: str, spec: Schema, value: object) -> ParameterError | None:
    type_name: str = spec["type"]
    if not _is_type(value, type_name):
        return ParameterError(path, f"{path} must be {_article(type_name)} (got {_echo(value)})")

    allowed = spec.get("enum")
    if allowed is not None and value not in allowed:
        options = ", ".join(str(v) for v in allowed)
        return ParameterError(path, f"{path} must be one of: {options} (got {_echo(value)})")

    minimum, maximum = spec.get("minimum"), spec.get("maximum")
    if not isinstance(value, int) or (minimum is None and maximum is None):
        return None
    if minimum is not None and maximum is not None:
        if not minimum <= value <= maximum:
            return ParameterError(
                path, f"{path} must be between {minimum} and {maximum} (got {_echo(value)})"
            )
    elif minimum is not None and value < minimum:
        return ParameterError(path, f"{path} must be at least {minimum} (got {_echo(value)})")
    elif maximum is not None and value > maximum:
        return ParameterError(path, f"{path} must be at most {maximum} (got {_echo(value)})")
    return None


def _article(type_name: str) -> str:
    return f"an {type_name}" if type_name[0] in "aeiou" else f"a {type_name}"


def _get(params: Params, path: str) -> object:
    """The value at a dotted path, or None when the module or name is absent or malformed."""
    module, _, name = path.partition(".")
    values = params.get(module)
    return values.get(name) if isinstance(values, dict) else None


def _check_rules(
    schema: Schema, params: Params, existing: list[ParameterError]
) -> list[ParameterError]:
    """Cross-field rules. A rule is skipped when an operand already failed on its own."""
    broken = {e.path for e in existing}
    errors: list[ParameterError] = []
    for rule in schema.get("x-rules", []):
        left, right = rule["left"], rule["right"]
        if left in broken or right in broken:
            continue
        left_value, right_value = _get(params, left), _get(params, right)
        # An operand that is missing or the wrong type is already reported on its own.
        # `operator` is ">=", the only one _check_schema allows.
        if not (isinstance(left_value, int) and isinstance(right_value, int)):
            continue
        if not left_value >= right_value:
            errors.append(
                ParameterError(
                    left,
                    f"{left} must be greater than or equal to {right} "
                    f"(got {left_value}, but {right} is {right_value})",
                )
            )
    return errors


def _check_schema(schema: Schema) -> None:
    modules = schema.get("properties")
    if not isinstance(modules, dict) or not modules:
        raise SchemaError("schema has no modules")
    for module, module_schema in modules.items():
        if module_schema.get("type") != "object":
            raise SchemaError(f"module {module!r} must be an object")
        for name, spec in module_schema.get("properties", {}).items():
            path = f"{module}.{name}"
            if spec.get("type") not in {"integer", "string"}:
                raise SchemaError(f"{path}: unsupported type {spec.get('type')!r}")
            if "default" not in spec:
                raise SchemaError(f"{path}: missing default")
            error = _check_value(path, spec, spec["default"])
            if error is not None:
                raise SchemaError(f"default for {error.message}")
    paths = set(parameter_paths(schema))
    for rule in schema.get("x-rules", []):
        if rule.get("operator") not in _OPERATORS:
            raise SchemaError(f"rule {rule.get('id')!r}: unsupported operator")
        for side in ("left", "right"):
            if rule.get(side) not in paths:
                raise SchemaError(f"rule {rule.get('id')!r}: unknown parameter {rule.get(side)!r}")
