"""The resource inventory (startup-template task 9.1 and the inventory half of 9.3).

`inventory.json` must describe the modules exactly: every resource block, no extras, with
the right type and instance count. Later specs build the architecture graph, the diagram
parity check, and the estimate from it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from hcl_scan import Block, resource_blocks

from template_tools.schema import load_schema, parameter_paths

TEMPLATES_ROOT = Path(__file__).resolve().parent.parent
VERSION_DIRS = sorted(p for p in (TEMPLATES_ROOT / "startup").iterdir() if p.is_dir())
MODULES = ["network", "compute", "database", "monitoring", "iam"]

# The node types the diagram has icons for (diagram spec). The template has no NAT gateway, so
# that icon is never used. This is the subset the template draws and the group kinds it draws.
NODE_TYPES = {
    "internet_gateway",
    "load_balancer",
    "ecs_service",
    "rds_instance",
    "log_group",
    "kms_key",
    "iam_role",
}
GROUP_KINDS = {"vpc", "subnet"}
TIERS = {"public", "data"}

# Pricing hints: id -> Pricing API service code. The estimate service owns the filters.
PRICING_HINTS = {
    "fargate_vcpu_hours": "AmazonECS",
    "fargate_memory_gb_hours": "AmazonECS",
    "alb_hours": "AWSELB",
    "alb_lcu_hours": "AWSELB",
    "rds_instance_hours": "AmazonRDS",
    "rds_storage_gb_month": "AmazonRDS",
    "cloudwatch_logs_ingested_gb": "AmazonCloudWatch",
    "kms_key_months": "awskms",
    "data_transfer_out_gb": "AWSDataTransfer",
    "public_ipv4_hours": "AmazonVPC",
}


@pytest.fixture(params=VERSION_DIRS, ids=lambda p: p.name)
def version_dir(request: pytest.FixtureRequest) -> Path:
    path: Path = request.param
    return path


def _inventory(version_dir: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((version_dir / "inventory.json").read_text())
    return data


def _entries(version_dir: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = _inventory(version_dir)["resources"]
    return entries


def _expected_instances(block: Block, schema_paths: list[str]) -> dict[str, Any]:
    """What the inventory must say for a block, from its `count` expression."""
    count = block.count
    if count is None:
        return {"fixed": 1}
    if count == "length(local.zone_indexes)":
        return {"fixed": 2}
    variable = re.fullmatch(r"var\.([a-z_]+)", count)
    if variable:
        matches = [p for p in schema_paths if p.endswith(f".{variable.group(1)}")]
        assert len(matches) == 1, (
            f"{block.address}: count var.{variable.group(1)} is not a parameter"
        )
        assert matches[0].split(".")[0] == block.module, (
            f"{block.address}: parameter of another module"
        )
        return {"parameter": matches[0]}
    optional = re.fullmatch(r"local\.https_enabled \? 1 : 0", count)
    if optional:
        return {"optional": "certificate_arn"}
    raise AssertionError(f"{block.module}/{block.address}: unrecognised count expression {count!r}")


# --- Structure ---------------------------------------------------------------------------


def test_header(version_dir: Path) -> None:
    inventory = _inventory(version_dir)
    meta = json.loads((version_dir / "template.json").read_text())
    assert inventory["schema"] == "lusiform.inventory/1"
    assert inventory["template"] == meta["template"]
    assert inventory["version"] == meta["version"] == version_dir.name


def test_entries_have_the_required_fields(version_dir: Path) -> None:
    for entry in _entries(version_dir):
        label = f"{entry.get('module')}/{entry.get('address')}"
        base = {"module", "address", "type", "representation", "instances", "pricing"}
        assert base <= set(entry), label
        assert entry["module"] in MODULES, label
        assert entry["address"].startswith(f"{entry['type']}."), label
        assert entry["representation"] in {"node", "group", "hidden"}, label
        assert list(entry["instances"]) in (["fixed"], ["parameter"], ["optional"]), label


def test_addresses_are_unique(version_dir: Path) -> None:
    keys = [(e["module"], e["address"]) for e in _entries(version_dir)]
    assert len(keys) == len(set(keys))


def test_representation_fields(version_dir: Path) -> None:
    for entry in _entries(version_dir):
        label = f"{entry['module']}/{entry['address']}"
        extra = set(entry) - {"module", "address", "type", "representation", "instances", "pricing"}
        if entry["representation"] == "node":
            assert entry["node"] in NODE_TYPES, label
            assert extra == {"node"}, label
        elif entry["representation"] == "group":
            assert entry["group"] in GROUP_KINDS, label
            assert extra == ({"group", "tier"} if entry["group"] == "subnet" else {"group"}), label
            if entry["group"] == "subnet":
                assert entry["tier"] in TIERS, label
        else:
            assert not extra, label


def test_every_node_type_is_used(version_dir: Path) -> None:
    used = {e["node"] for e in _entries(version_dir) if e["representation"] == "node"}
    assert used == NODE_TYPES


def test_a_node_type_maps_to_one_terraform_type(version_dir: Path) -> None:
    mapping: dict[str, set[str]] = {}
    for entry in _entries(version_dir):
        if entry["representation"] == "node":
            mapping.setdefault(entry["node"], set()).add(entry["type"])
    assert all(len(types) == 1 for types in mapping.values()), mapping


# --- The inventory matches the modules ---------------------------------------------------


def test_inventory_matches_the_module_resource_blocks_exactly(version_dir: Path) -> None:
    blocks = {(b.module, b.address, b.type) for b in resource_blocks(version_dir / "modules")}
    inventory = {(e["module"], e["address"], e["type"]) for e in _entries(version_dir)}
    assert not blocks - inventory, (
        f"in modules but not in the inventory: {sorted(blocks - inventory)}"
    )
    assert not inventory - blocks, (
        f"in the inventory but not in modules: {sorted(inventory - blocks)}"
    )


def test_instance_counts_match_the_count_expressions(version_dir: Path) -> None:
    schema_paths = parameter_paths(load_schema(version_dir / "schema.json"))
    by_key = {(e["module"], e["address"]): e for e in _entries(version_dir)}
    for block in resource_blocks(version_dir / "modules"):
        expected = _expected_instances(block, schema_paths)
        assert by_key[(block.module, block.address)]["instances"] == expected, block.address


def test_parameter_references_exist_in_the_schema(version_dir: Path) -> None:
    paths = set(parameter_paths(load_schema(version_dir / "schema.json")))
    for entry in _entries(version_dir):
        if "parameter" in entry["instances"]:
            assert entry["instances"]["parameter"] in paths, entry["address"]


def test_optional_instances_name_a_root_variable(version_dir: Path) -> None:
    root_variables = (version_dir / "root" / "variables.tf.tmpl").read_text()
    for entry in _entries(version_dir):
        if "optional" in entry["instances"]:
            variable = entry["instances"]["optional"]
            assert f'variable "{variable}"' in root_variables, entry["address"]


def test_the_inventory_lists_data_sources_nowhere(version_dir: Path) -> None:
    assert not any(e["type"].startswith("data.") for e in _entries(version_dir))


# --- Expected shape of the template ------------------------------------------------------


def test_the_set_of_terraform_types(version_dir: Path) -> None:
    types = sorted({e["type"] for e in _entries(version_dir)})
    assert types == sorted(
        [
            "aws_appautoscaling_policy",
            "aws_appautoscaling_target",
            "aws_cloudwatch_log_group",
            "aws_cloudwatch_metric_alarm",
            "aws_db_instance",
            "aws_db_parameter_group",
            "aws_db_subnet_group",
            "aws_default_security_group",
            "aws_ecs_cluster",
            "aws_ecs_service",
            "aws_ecs_task_definition",
            "aws_flow_log",
            "aws_iam_policy",
            "aws_iam_role",
            "aws_iam_role_policy_attachment",
            "aws_internet_gateway",
            "aws_kms_alias",
            "aws_kms_key",
            "aws_lb",
            "aws_lb_listener",
            "aws_lb_target_group",
            "aws_route",
            "aws_route_table",
            "aws_route_table_association",
            "aws_security_group",
            "aws_subnet",
            "aws_vpc",
        ]
    )


def test_there_is_no_nat_gateway_and_the_standby_follows_az_count(version_dir: Path) -> None:
    by_address = {f"{e['module']}.{e['address']}": e for e in _entries(version_dir)}
    assert not [a for a in by_address if "nat" in a or "private_app" in a or "aws_eip" in a]
    assert by_address["network.aws_subnet.public"]["instances"] == {"fixed": 2}
    assert by_address["database.aws_db_instance.this"]["instances"] == {"fixed": 1}


def test_nothing_out_of_scope_in_the_inventory(version_dir: Path) -> None:
    forbidden = ("aws_eks", "aws_rds_cluster", "aws_elasticache", "aws_cloudfront", "aws_wafv2")
    for entry in _entries(version_dir):
        assert not entry["type"].startswith(forbidden), entry["type"]


# --- Pricing hints -----------------------------------------------------------------------


def test_pricing_hints_are_known_and_carry_the_right_service_code(version_dir: Path) -> None:
    for entry in _entries(version_dir):
        for hint in entry["pricing"]:
            assert set(hint) == {"hint", "service"}, entry["address"]
            assert hint["hint"] in PRICING_HINTS, hint
            assert hint["service"] == PRICING_HINTS[hint["hint"]], hint


def test_every_pricing_hint_is_attached_somewhere(version_dir: Path) -> None:
    used = {h["hint"] for e in _entries(version_dir) for h in e["pricing"]}
    assert used == set(PRICING_HINTS)


def test_billable_resources_carry_hints(version_dir: Path) -> None:
    by_address = {f"{e['module']}.{e['address']}": e for e in _entries(version_dir)}

    def hints(address: str) -> set[str]:
        return {h["hint"] for h in by_address[address]["pricing"]}

    assert hints("compute.aws_ecs_service.app") == {
        "fargate_vcpu_hours",
        "fargate_memory_gb_hours",
        "public_ipv4_hours",
    }
    assert hints("database.aws_db_instance.this") == {"rds_instance_hours", "rds_storage_gb_month"}
    assert {"alb_hours", "alb_lcu_hours"} <= hints("compute.aws_lb.this")
    assert hints("monitoring.aws_kms_key.logs") == {"kms_key_months"}
    assert hints("database.aws_kms_key.database") == {"kms_key_months"}
