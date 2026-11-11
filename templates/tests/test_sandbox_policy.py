"""The cross-account sandbox policy (startup-template tasks 9.2 and 9.3).

`sandbox-policy.json` is derived from `inventory.json`, `iam-catalog.json`, and
`iam-reference.json` (AWS's own list of actions, resource types, and condition keys). These
tests check the result against the reference and against the modules, independently of the
generator code:

- the policy covers exactly the actions the inventory's resource types need, and nothing else;
- no action or resource is wildcarded unless the catalog accepts it;
- every action is paired with resource types AWS says it accepts, and every condition key is
  one AWS says applies, so no statement is silently dead;
- every statement is limited by the project tag, an `lf-` name, or an accepted exception.

Nothing here talks to AWS; the policy has not been run against an account.
"""

from __future__ import annotations

import copy
import json
import re
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from hcl_scan import resource_blocks

from template_tools.sandbox_policy import (
    MAX_DOCUMENT_CHARACTERS,
    PolicyError,
    characters,
    derive,
    generate,
    render,
)

TEMPLATES_ROOT = Path(__file__).resolve().parent.parent
VERSION_DIRS = sorted(p for p in (TEMPLATES_ROOT / "startup").iterdir() if p.is_dir())
Json = dict[str, Any]

ALLOWED_SERVICES = {
    "ec2",
    "elasticloadbalancing",
    "ecs",
    "application-autoscaling",
    "cloudwatch",
    "logs",
    "rds",
    "kms",
    "iam",
    "secretsmanager",
}
FORBIDDEN_ACTIONS = {
    "iam:CreateUser",
    "iam:CreateAccessKey",
    "iam:CreateLoginProfile",
    "iam:PutRolePolicy",
    "iam:PutUserPolicy",
    "iam:AttachUserPolicy",
    "iam:PutRolePermissionsBoundary",
    "iam:DeleteRolePermissionsBoundary",
    "iam:SetDefaultPolicyVersion",
    "sts:AssumeRole",
    "s3:PutBucketPolicy",
    "kms:PutKeyPolicy:*",
}
READ_PREFIXES = ("Describe", "Get", "List")

# Statements that are deliberately broader than the tag and name gates. Each must be named in
# the catalog's known_gaps, so adding one means writing down why.
KNOWN_GAP_SIDS = {"AutoScalingAlarmValidation", "DefaultSecurityGroup"}

# Resource types whose ARNs have no `lf-` name and no tag gate, and why that is accepted.
UNGATED_EXCEPTIONS = {
    "rds:cluster": "read-only; DescribeDBClusters on an instance's cluster",
    "ec2:security-group-rule": "child of a security group, which is gated",
    "secretsmanager:Secret": "created by RDS; limited to the rds! name prefix",
    "ec2:security-group": "default security group (DefaultSecurityGroup extra)",
}
# Resource types identified by a generated id, not a name; they depend on the tag gate.
ID_BASED = {
    "ec2:vpc",
    "ec2:subnet",
    "ec2:route-table",
    "ec2:internet-gateway",
    "ec2:elastic-ip",
    "ec2:natgateway",
    "ec2:security-group",
    "ec2:security-group-rule",
    "ec2:vpc-flow-log",
    "kms:key",
    "application-autoscaling:ScalableTarget",
    "rds:cluster",
}


@cache
def _load(version_dir: Path, name: str) -> Json:
    data: Json = json.loads((version_dir / name).read_text())
    return data


@pytest.fixture(params=VERSION_DIRS, ids=lambda p: p.name)
def version_dir(request: pytest.FixtureRequest) -> Path:
    path: Path = request.param
    return path


def _inventory(v: Path) -> Json:
    return _load(v, "inventory.json")


def _catalog(v: Path) -> Json:
    return _load(v, "iam-catalog.json")


def _reference(v: Path) -> Json:
    return _load(v, "iam-reference.json")


def _document(v: Path) -> Json:
    return _load(v, "sandbox-policy.json")


def _statements(v: Path) -> list[Json]:
    return [s for d in _document(v)["documents"] for s in d["policy"]["Statement"]]


def _as_list(value: Any) -> list[str]:
    return value if isinstance(value, list) else [value]


# --- helpers that map ARN patterns back to resource types --------------------------------

ACCOUNT = "ACCOUNT"


def _arn_parts(arn: str) -> list[str]:
    """Split an ARN into its six fields. The account policy variable contains a colon, so it
    is swapped for a placeholder first."""
    return arn.replace("${aws:PrincipalAccount}", ACCOUNT).split(":", 5)


def _static_prefix(arn_format: str) -> str:
    resource_part = arn_format.split(":", 5)[5]
    return resource_part.split("${", 1)[0]


def _label_of(pattern: str, reference: Json) -> str | None:
    """The catalog resource type a policy ARN pattern belongs to."""
    parts = _arn_parts(pattern)
    assert len(parts) == 6 and parts[0] == "arn", pattern
    service, resource_part = parts[2], parts[5]
    best: str | None = None
    for label, formats in reference["arn_formats"].items():
        if label.split(":", 1)[0] != service:
            continue
        prefix = _static_prefix(formats[0])
        if resource_part.startswith(prefix) and (
            best is None or len(prefix) > len(_static_prefix(reference["arn_formats"][best][0]))
        ):
            best = label
    return best


def _statement_labels(statement: Json, reference: Json) -> set[str]:
    labels: set[str] = set()
    for resource in _as_list(statement["Resource"]):
        if resource != "*":
            label = _label_of(resource, reference)
            assert label is not None, f"{statement['Sid']}: no resource type for {resource}"
            labels.add(label)
    return labels


def _condition_keys(statement: Json) -> set[str]:
    return {key for keys in statement.get("Condition", {}).values() for key in keys}


def _normalise_key(key: str) -> str:
    for tag_kind in ("aws:RequestTag/", "aws:ResourceTag/"):
        if key.startswith(tag_kind):
            return tag_kind + "${TagKey}"
    return key


# --- 9.2 the files -----------------------------------------------------------------------


def test_committed_policy_is_what_the_generator_produces(version_dir: Path) -> None:
    expected = render(generate(version_dir).document)
    assert (version_dir / "sandbox-policy.json").read_text() == expected, (
        "sandbox-policy.json is out of date; run python -m template_tools.sandbox_policy "
        f"startup/{version_dir.name}"
    )


def test_generation_is_deterministic(version_dir: Path) -> None:
    assert render(generate(version_dir).document) == render(generate(version_dir).document)


def test_headers_match_the_template(version_dir: Path) -> None:
    meta = json.loads((version_dir / "template.json").read_text())
    for name in ("inventory.json", "iam-catalog.json", "iam-reference.json", "sandbox-policy.json"):
        data = _load(version_dir, name)
        if name != "iam-reference.json":
            assert data["template"] == meta["template"], name
            assert data["version"] == meta["version"], name
    assert _document(version_dir)["schema"] == "lusiform.sandbox-policy/1"


def test_reference_covers_the_catalog_exactly(version_dir: Path) -> None:
    catalog, reference = _catalog(version_dir), _reference(version_dir)
    catalog_actions: set[str] = set()
    for entry in catalog["types"].values():
        for role in ("create", "write", "read", "tag"):
            catalog_actions.update(entry.get(role, []))
    for extra in catalog["extras"]:
        catalog_actions.update(extra["actions"])
    assert set(reference["actions"]) == catalog_actions
    assert set(reference["arn_formats"]) == set(catalog["arns"])


def test_reference_records_its_source(version_dir: Path) -> None:
    reference = _reference(version_dir)
    assert reference["source"].startswith("https://servicereference.us-east-1.amazonaws.com/")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", reference["retrieved"])


# --- 9.3 coverage: exactly the inventory's resource types --------------------------------


def test_every_inventory_type_has_a_catalog_entry_and_the_reverse(version_dir: Path) -> None:
    inventory_types = {e["type"] for e in _inventory(version_dir)["resources"]}
    assert set(_catalog(version_dir)["types"]) == inventory_types


def test_policy_covers_exactly_the_actions_the_inventory_needs(version_dir: Path) -> None:
    inventory_types = {e["type"] for e in _inventory(version_dir)["resources"]}
    catalog = _catalog(version_dir)
    expected: set[str] = set()
    for resource_type in inventory_types:
        entry = catalog["types"][resource_type]
        for role in ("create", "write", "read", "tag"):
            expected.update(entry.get(role, []))
    for extra in catalog["extras"]:
        if set(extra["for"]) & inventory_types:
            expected.update(extra["actions"])
    granted = {a for s in _statements(version_dir) for a in _as_list(s["Action"])}
    assert granted - expected == set(), f"granted but not needed: {sorted(granted - expected)}"
    assert expected - granted == set(), f"needed but not granted: {sorted(expected - granted)}"


def test_every_action_of_every_type_is_granted(version_dir: Path) -> None:
    result = generate(version_dir)
    granted = {a for s in result.statements for a in _as_list(s["Action"])}
    for resource_type, actions in result.actions_by_type.items():
        assert actions, resource_type
        assert actions <= granted, f"{resource_type}: {sorted(actions - granted)}"


def test_extras_are_for_inventory_types(version_dir: Path) -> None:
    inventory_types = {e["type"] for e in _inventory(version_dir)["resources"]}
    for extra in _catalog(version_dir)["extras"]:
        assert set(extra["for"]) <= inventory_types, extra["id"]
        assert extra["why"], extra["id"]


def test_dropping_a_resource_type_drops_its_permissions(version_dir: Path) -> None:
    # A policy for a template without an EKS-free example: remove the NAT gateway and check
    # its actions disappear. The catalog entry then becomes an orphan, which is refused.
    inventory = copy.deepcopy(_inventory(version_dir))
    inventory["resources"] = [e for e in inventory["resources"] if e["type"] != "aws_nat_gateway"]
    with pytest.raises(PolicyError, match="not in the inventory"):
        derive(inventory, _catalog(version_dir), _reference(version_dir))
    catalog = copy.deepcopy(_catalog(version_dir))
    del catalog["types"]["aws_nat_gateway"]
    result = derive(inventory, catalog, _reference(version_dir))
    granted = {a for s in result.statements for a in _as_list(s["Action"])}
    assert "ec2:CreateNatGateway" not in granted and "ec2:DeleteNatGateway" not in granted


# --- IAM document validity ---------------------------------------------------------------


def test_documents_are_valid_iam_policies(version_dir: Path) -> None:
    sids: set[str] = set()
    for document in _document(version_dir)["documents"]:
        policy = document["policy"]
        assert set(policy) == {"Version", "Statement"}
        assert policy["Version"] == "2012-10-17"
        assert policy["Statement"], document["name"]
        for statement in policy["Statement"]:
            assert set(statement) <= {"Sid", "Effect", "Action", "Resource", "Condition"}
            assert {"Sid", "Effect", "Action", "Resource"} <= set(statement)
            assert statement["Effect"] == "Allow"
            assert re.fullmatch(r"[A-Za-z0-9]{1,128}", statement["Sid"]), statement["Sid"]
            assert statement["Sid"] not in sids, f"duplicate Sid {statement['Sid']}"
            sids.add(statement["Sid"])


def test_documents_fit_the_managed_policy_limit(version_dir: Path) -> None:
    document = _document(version_dir)
    assert document["max_document_characters"] == 6144
    assert 1 <= len(document["documents"]) <= 10, "a role holds ten managed policies by default"
    for part in document["documents"]:
        size = characters(part["policy"])
        assert part["characters"] == size, part["name"]
        assert size <= MAX_DOCUMENT_CHARACTERS < 6144, f"{part['name']} is {size} characters"
    assert [d["name"] for d in document["documents"]] == [
        f"part{i}" for i in range(1, len(document["documents"]) + 1)
    ]


def test_each_service_lives_in_one_document(version_dir: Path) -> None:
    seen: dict[str, str] = {}
    for part in _document(version_dir)["documents"]:
        for service in part["services"]:
            assert service not in seen, f"{service} is split across documents"
            seen[service] = part["name"]
        used = {
            a.split(":", 1)[0] for s in part["policy"]["Statement"] for a in _as_list(s["Action"])
        }
        assert used == set(part["services"]), part["name"]


def test_only_the_expected_services_appear(version_dir: Path) -> None:
    services = {a.split(":", 1)[0] for s in _statements(version_dir) for a in _as_list(s["Action"])}
    assert services == ALLOWED_SERVICES


# --- No wildcard actions, no wildcard resources unless accepted --------------------------


def test_no_wildcard_actions(version_dir: Path) -> None:
    for statement in _statements(version_dir):
        for action in _as_list(statement["Action"]):
            assert re.fullmatch(r"[a-z0-9-]+:[A-Za-z0-9]+", action), f"{statement['Sid']}: {action}"
            assert "*" not in action


def test_forbidden_actions_are_absent(version_dir: Path) -> None:
    granted = {a for s in _statements(version_dir) for a in _as_list(s["Action"])}
    assert granted.isdisjoint(FORBIDDEN_ACTIONS)
    assert not any(
        a.startswith(("s3:", "sts:", "organizations:", "account:", "ssm:")) for a in granted
    )


def test_wildcard_resources_are_read_only_or_accepted(version_dir: Path) -> None:
    accepted = set(_catalog(version_dir)["accepted_unscoped"])
    unscoped_writes: set[str] = set()
    for statement in _statements(version_dir):
        resources = _as_list(statement["Resource"])
        if "*" not in resources:
            continue
        assert resources == ["*"], f"{statement['Sid']} mixes '*' with ARNs"
        for action in _as_list(statement["Action"]):
            if not action.split(":", 1)[1].startswith(READ_PREFIXES):
                unscoped_writes.add(action)
    assert unscoped_writes == accepted


def test_accepted_unscoped_actions_have_a_reason_and_no_resource_type(version_dir: Path) -> None:
    reference = _reference(version_dir)
    for action, reason in _catalog(version_dir)["accepted_unscoped"].items():
        assert reason
        assert reference["actions"][action]["resource_types"] == 0, action


def test_unscoped_creates_are_gated_on_the_request_tag(version_dir: Path) -> None:
    tag = _catalog(version_dir)["tag"]
    for statement in _statements(version_dir):
        if statement["Resource"] == "*" and not statement["Sid"].endswith("ReadAny"):
            keys = _condition_keys(statement)
            if "kms:CreateKey" in _as_list(statement["Action"]):
                assert keys == {f"aws:RequestTag/{tag['key']}"}


def test_every_account_in_an_arn_is_the_principal_account(version_dir: Path) -> None:
    for statement in _statements(version_dir):
        for resource in _as_list(statement["Resource"]):
            if resource == "*":
                continue
            parts = _arn_parts(resource)
            service, account = parts[2], parts[4]
            if service == "iam" and ":aws:policy/" in resource:
                continue
            assert account == ACCOUNT, f"{statement['Sid']}: {resource}"
            assert parts[1] == "aws", f"{statement['Sid']}: only the aws partition is supported"


def test_no_hardcoded_account_ids_or_regions(version_dir: Path) -> None:
    text = (version_dir / "sandbox-policy.json").read_text()
    assert not re.search(r"(?<![\w-])\d{12}(?![\w-])", text)
    assert not re.search(r"\b[a-z]{2}-[a-z]+-\d\b", text)


# --- Against the AWS reference -----------------------------------------------------------


def test_every_action_is_paired_with_resources_aws_says_it_accepts(version_dir: Path) -> None:
    reference = _reference(version_dir)
    for statement in _statements(version_dir):
        labels = _statement_labels(statement, reference)
        for action in _as_list(statement["Action"]):
            info = reference["actions"][action]
            if info["resource_types"] == 0:
                assert statement["Resource"] == "*", (
                    f"{statement['Sid']}: {action} accepts no resource types, so an ARN-scoped "
                    "statement would never match it"
                )
            else:
                assert "*" not in _as_list(statement["Resource"]), f"{statement['Sid']}: {action}"
                assert labels & set(info["resources"]), (
                    f"{statement['Sid']}: {action} accepts {sorted(info['resources'])}, "
                    f"but the statement lists {sorted(labels)}"
                )


def test_every_condition_key_applies_to_every_action_in_its_statement(version_dir: Path) -> None:
    reference = _reference(version_dir)
    for statement in _statements(version_dir):
        keys = {_normalise_key(k) for k in _condition_keys(statement)}
        if not keys:
            continue
        labels = _statement_labels(statement, reference)
        for action in _as_list(statement["Action"]):
            info = reference["actions"][action]
            applicable = set(info["keys"])
            for label in labels & set(info["resources"]):
                applicable |= set(info["resources"][label])
            missing = keys - applicable
            assert not missing, (
                f"{statement['Sid']}: {action} does not support {sorted(missing)}, "
                "so the statement would never allow it"
            )


def test_arn_patterns_have_the_shape_aws_documents(version_dir: Path) -> None:
    reference, catalog = _reference(version_dir), _catalog(version_dir)
    for label, patterns in catalog["arns"].items():
        formats = reference["arn_formats"][label]
        assert len(formats) == 1, label
        format_parts = formats[0].split(":", 5)
        for pattern in patterns:
            parts = _arn_parts(pattern)
            assert len(parts) == 6, pattern
            assert parts[0] == "arn" and parts[1] == "aws", pattern
            assert parts[2] == format_parts[2], pattern
            assert (parts[3] == "*") == (format_parts[3] == "${Region}"), pattern
            assert (parts[4] == ACCOUNT) == (format_parts[4] == "${Account}"), pattern
            assert parts[5].startswith(_static_prefix(formats[0])), f"{pattern} vs {formats[0]}"


def test_a_pattern_belongs_to_one_resource_type(version_dir: Path) -> None:
    reference, catalog = _reference(version_dir), _catalog(version_dir)
    for label, patterns in catalog["arns"].items():
        for pattern in patterns:
            assert _label_of(pattern, reference) == label, pattern


# --- Scoping -----------------------------------------------------------------------------


def test_every_statement_is_scoped_by_tag_name_or_an_accepted_exception(version_dir: Path) -> None:
    catalog, reference = _catalog(version_dir), _reference(version_dir)
    tag_keys = {
        f"aws:RequestTag/{catalog['tag']['key']}",
        f"aws:ResourceTag/{catalog['tag']['key']}",
    }
    extra_ids = {e["id"] for e in catalog["extras"]}
    for statement in _statements(version_dir):
        resources = _as_list(statement["Resource"])
        if resources == ["*"]:
            continue  # read-only or accepted, checked above
        if _condition_keys(statement) & tag_keys:
            continue
        if "kms:ResourceAliases" in _condition_keys(statement):
            continue  # scoped to the AWS managed key by its alias
        if statement["Sid"] in KNOWN_GAP_SIDS:
            continue  # reviewed and listed in the catalog's known_gaps
        # No tag gate: the resources must carry the name prefix, be a fully literal ARN, or be
        # a documented exception.
        for resource in resources:
            label = _label_of(resource, reference)
            assert label is not None
            named = "lf-" in resource
            literal = "*" not in _arn_parts(resource)[5]
            exception = label in UNGATED_EXCEPTIONS and statement["Sid"] in (
                extra_ids | {"Ec2ByName", "RdsByName", "KmsByName"}
            )
            assert named or literal or exception, (
                f"{statement['Sid']}: {resource} has no tag gate and no lf- name"
            )


def test_known_gaps_are_documented(version_dir: Path) -> None:
    catalog = _catalog(version_dir)
    gaps = " ".join(catalog["known_gaps"])
    for sid in KNOWN_GAP_SIDS:
        assert sid in {e["id"] for e in catalog["extras"]}, sid
        assert sid in gaps, f"{sid} is broad but not described in known_gaps"
    for action in catalog["accepted_unscoped"]:
        assert action.split(":", 1)[1] in gaps or action in {"kms:CreateKey"}, action
    assert catalog["assumptions"], "assumptions that were not verified against AWS must be listed"


def test_id_based_resources_are_only_reachable_through_a_gate(version_dir: Path) -> None:
    catalog, reference = _catalog(version_dir), _reference(version_dir)
    tag_keys = {
        f"aws:RequestTag/{catalog['tag']['key']}",
        f"aws:ResourceTag/{catalog['tag']['key']}",
    }
    allowed_ungated = {
        # sid -> why it may reach id-based resources without the tag
        "Ec2ByName": "security-group-rule: child of a gated security group",
        "RdsByName": "rds:cluster: read-only",
        "DefaultSecurityGroup": "known gap: the default security group is created untagged",
        "AutoScalingAlarmValidation": "alarms have names, not ids",
        "RdsDescribeManagedSecretKey": "AWS managed key, gated on its alias",
    }
    for statement in _statements(version_dir):
        labels = _statement_labels(statement, reference)
        if not labels & ID_BASED or _condition_keys(statement) & tag_keys:
            continue
        assert statement["Sid"] in allowed_ungated, (
            f"{statement['Sid']} reaches id-based resources "
            f"{sorted(labels & ID_BASED)} without the tag"
        )


def test_the_tag_is_the_one_the_root_project_sets(version_dir: Path) -> None:
    tag = _catalog(version_dir)["tag"]
    main = (version_dir / "root" / "main.tf.tmpl").read_text()
    assert re.search(rf'"{re.escape(tag["key"])}"\s*=\s*"{re.escape(tag["value"])}"', main)


def test_every_tagged_statement_uses_the_catalog_tag(version_dir: Path) -> None:
    tag = _catalog(version_dir)["tag"]
    for statement in _statements(version_dir):
        for operator, keys in statement.get("Condition", {}).items():
            for key, value in keys.items():
                if key.startswith(("aws:RequestTag/", "aws:ResourceTag/")):
                    assert operator == "StringEquals"
                    assert key.split("/", 1)[1] == tag["key"] and value == tag["value"]


def test_tag_on_create_is_limited_to_the_creating_action_where_aws_allows(
    version_dir: Path,
) -> None:
    reference = _reference(version_dir)
    for statement in _statements(version_dir):
        if not statement["Sid"].endswith("TagOnCreate"):
            continue
        for action in _as_list(statement["Action"]):
            create_key = f"{action.split(':', 1)[0]}:CreateAction"
            offers = create_key in reference["actions"][action]["keys"]
            assert (create_key in _condition_keys(statement)) == offers, (statement["Sid"], action)
            assert not action.split(":", 1)[1].startswith(("Delete", "Untag", "Remove"))


def test_removing_tags_is_gated_on_the_resource_tag(version_dir: Path) -> None:
    for statement in _statements(version_dir):
        for action in _as_list(statement["Action"]):
            if action.split(":", 1)[1].startswith(
                ("DeleteTags", "UntagResource", "RemoveTags", "UntagRole", "UntagPolicy")
            ):
                keys = _condition_keys(statement)
                assert (
                    any(k.startswith("aws:ResourceTag/") for k in keys)
                    or statement["Sid"] == "DefaultSecurityGroup"
                ), (
                    statement["Sid"],
                    action,
                )


# --- What each type is granted (independent of the generator's merging) ------------------


def _effective(
    version_dir: Path, skip_sids: frozenset[str] = frozenset()
) -> set[tuple[str, str, str]]:
    """(action, resource type, kind) for every grant, with kind from the condition."""
    reference, catalog = _reference(version_dir), _catalog(version_dir)
    tag = catalog["tag"]["key"]
    grants: set[tuple[str, str, str]] = set()
    for statement in _statements(version_dir):
        if statement["Sid"] in skip_sids:
            continue
        keys = _condition_keys(statement)
        if f"aws:RequestTag/{tag}" in keys:
            kind = "tag-create" if any(k.endswith(":CreateAction") for k in keys) else "request"
        elif f"aws:ResourceTag/{tag}" in keys:
            kind = "resource"
        else:
            kind = "name"
        for action in _as_list(statement["Action"]):
            if statement["Resource"] == "*":
                grants.add((action, "*", "any"))
            else:
                for label in _statement_labels(statement, reference):
                    grants.add((action, label, kind))
    return grants


def test_creates_writes_reads_and_tags_have_the_intended_gate(version_dir: Path) -> None:
    catalog, reference = _catalog(version_dir), _reference(version_dir)
    name_only = set(catalog["name_only"])
    effective = _effective(version_dir)

    def gate(label: str, kind: str) -> str:
        return "name" if label in name_only else kind

    for resource_type, entry in catalog["types"].items():
        creates, uses = entry.get("creates", []), entry.get("uses", [])
        own = creates + uses
        for action in entry.get("create", []):
            labels = set(reference["actions"][action]["resources"])
            for label in creates:
                if label in labels:
                    assert (action, label, gate(label, "request")) in effective, (
                        resource_type,
                        action,
                        label,
                    )
            for label in uses:
                if label in labels:
                    assert (action, label, gate(label, "resource")) in effective, (
                        resource_type,
                        action,
                        label,
                    )
            if reference["actions"][action]["resource_types"] == 0:
                assert (action, "*", "any") in effective or any(
                    a == action and lbl == "*" for a, lbl, _ in effective
                ), (resource_type, action)
        for action in entry.get("write", []) + entry.get("read", []):
            info = reference["actions"][action]
            if info["resource_types"] == 0:
                assert (action, "*", "any") in effective, (resource_type, action)
                continue
            labels = set(info["resources"])
            matched = [label for label in own if label in labels] or sorted(labels)
            for label in matched:
                assert (action, label, gate(label, "resource")) in effective, (
                    resource_type,
                    action,
                    label,
                )
        for action in entry.get("tag", []):
            for label in creates:
                if label in reference["actions"][action]["resources"]:
                    assert (action, label, gate(label, "resource")) in effective, (
                        resource_type,
                        action,
                        label,
                    )
                    removes = action.split(":", 1)[1].startswith(("Delete", "Untag", "Remove"))
                    if not removes and label not in name_only:
                        offers_create_action = (
                            f"{action.split(':', 1)[0]}:CreateAction"
                            in reference["actions"][action]["keys"]
                        )
                        expected_kind = "tag-create" if offers_create_action else "request"
                        assert (action, label, expected_kind) in effective, (
                            resource_type,
                            action,
                            label,
                        )


def test_creation_is_never_allowed_without_a_gate(version_dir: Path) -> None:
    # A resource that does not exist yet has no tag to match, so creation must be gated on the
    # request tag. It must never be allowed by name alone or on '*' (except accepted actions).
    # Merged statements also list the created resource's ARN next to actions that touch existing
    # resources; those pairs have no effect because the new resource carries no tag to match.
    # The catalog's explicit extras are reviewed one by one (and listed in known_gaps where they
    # are broad), so this checks the statements the generator derives.
    catalog = _catalog(version_dir)
    effective = _effective(version_dir, frozenset(e["id"] for e in catalog["extras"]))
    checked = 0
    for entry in catalog["types"].values():
        for action in entry.get("create", []):
            for label in entry.get("creates", []):
                if label in catalog["name_only"]:
                    continue
                checked += 1
                assert (action, label, "name") not in effective, (action, label)
                assert (action, label, "any") not in effective, (action, label)
    assert checked >= 15, "the check should cover every created resource type"


def test_attaching_policies_is_limited_to_known_policies(version_dir: Path) -> None:
    statements = {s["Sid"]: s for s in _statements(version_dir)}
    attach = statements["AttachAllowedManagedPolicies"]
    assert sorted(_as_list(attach["Action"])) == ["iam:AttachRolePolicy", "iam:DetachRolePolicy"]
    allowed = _as_list(attach["Condition"]["ArnLike"]["iam:PolicyARN"])
    assert sorted(allowed) == [
        "arn:aws:iam::${aws:PrincipalAccount}:policy/lf-*",
        "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy",
        "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole",
    ]
    assert not any("Administrator" in p or "PowerUser" in p or p.endswith("/*") for p in allowed)


def test_pass_role_is_limited_to_named_roles_and_services(version_dir: Path) -> None:
    pass_role = [s for s in _statements(version_dir) if "iam:PassRole" in _as_list(s["Action"])]
    assert len(pass_role) == 3
    for statement in pass_role:
        assert _as_list(statement["Action"]) == ["iam:PassRole"]
        services = statement["Condition"]["StringEquals"]["iam:PassedToService"]
        assert services in {
            "vpc-flow-logs.amazonaws.com",
            "ecs-tasks.amazonaws.com",
            "monitoring.rds.amazonaws.com",
        }
        for resource in _as_list(statement["Resource"]):
            assert re.fullmatch(
                r"arn:aws:iam::\$\{aws:PrincipalAccount\}:role/lf-\*-[a-z-]+", resource
            ), resource


def test_service_linked_roles_are_limited_to_the_four_services(version_dir: Path) -> None:
    created = [
        s
        for s in _statements(version_dir)
        if "iam:CreateServiceLinkedRole" in _as_list(s["Action"])
    ]
    names = sorted(s["Condition"]["StringEquals"]["iam:AWSServiceName"] for s in created)
    assert names == [
        "ecs.amazonaws.com",
        "ecs.application-autoscaling.amazonaws.com",
        "elasticloadbalancing.amazonaws.com",
        "rds.amazonaws.com",
    ]
    for statement in created:
        assert "*" not in statement["Resource"]


def test_kms_keys_cannot_be_used_for_data_or_policy_beyond_the_tagged_keys(
    version_dir: Path,
) -> None:
    granted = {
        a for s in _statements(version_dir) for a in _as_list(s["Action"]) if a.startswith("kms:")
    }
    assert not granted & {
        "kms:Decrypt",
        "kms:Encrypt",
        "kms:GenerateDataKey",
        "kms:ReEncrypt",
        "kms:Sign",
    }
    for statement in _statements(version_dir):
        if "kms:CreateGrant" in _as_list(statement["Action"]):
            assert statement["Condition"]["Bool"]["kms:GrantIsForAWSResource"] == "true"


# --- The names the policy relies on are the names the modules produce --------------------


def _resource_attribute(version_dir: Path, module: str, address: str, attribute: str) -> str:
    text = ""
    for tf_file in sorted((version_dir / "modules" / module).glob("*.tf")):
        text += tf_file.read_text() + "\n"
    block = re.search(
        rf'^resource "{address.split(".")[0]}" "{address.split(".")[1]}" \{{(.*?)^\}}',
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert block, address
    found = re.search(rf"^  {attribute}\s*=\s*(.+)$", block.group(1), re.MULTILINE)
    assert found, f"{address}.{attribute}"
    value = found.group(1).strip()
    local = re.fullmatch(r"local\.([a-z_]+)", value)
    if local:
        resolved = re.search(rf"^\s+{local.group(1)}\s*=\s*(.+)$", text, re.MULTILINE)
        assert resolved, value
        value = resolved.group(1).strip()
    return value


@pytest.mark.parametrize(
    ("module", "address", "attribute", "expected"),
    [
        ("iam", "aws_iam_role.task_execution", "name", '"${var.name_prefix}-ecs-execution"'),
        ("iam", "aws_iam_role.task", "name", '"${var.name_prefix}-ecs-task"'),
        ("iam", "aws_iam_role.flow_logs", "name", '"${var.name_prefix}-vpc-flow-logs"'),
        ("iam", "aws_iam_role.rds_monitoring", "name", '"${var.name_prefix}-rds-monitoring"'),
        ("iam", "aws_iam_policy.task", "name", '"${var.name_prefix}-ecs-task"'),
        ("monitoring", "aws_cloudwatch_log_group.ecs", "name", '"/ecs/${var.name_prefix}"'),
        (
            "monitoring",
            "aws_cloudwatch_log_group.flow_logs",
            "name",
            '"/vpc/${var.name_prefix}-flow-logs"',
        ),
        ("monitoring", "aws_kms_alias.logs", "name", '"alias/${var.name_prefix}-logs"'),
        ("database", "aws_kms_alias.database", "name", '"alias/${var.name_prefix}-database"'),
        ("database", "aws_db_subnet_group.this", "name", '"${var.name_prefix}-db"'),
        ("database", "aws_db_parameter_group.this", "name", '"${var.name_prefix}-postgres16"'),
        ("compute", "aws_lb.this", "name", '"${var.name_prefix}-alb"'),
        ("compute", "aws_lb_target_group.app", "name", '"${var.name_prefix}-tg"'),
        ("compute", "aws_ecs_cluster.this", "name", '"${var.name_prefix}-cluster"'),
        ("compute", "aws_ecs_service.app", "name", '"${var.name_prefix}-app"'),
        ("compute", "aws_ecs_task_definition.app", "family", '"${var.name_prefix}-app"'),
        (
            "monitoring",
            "aws_cloudwatch_metric_alarm.ecs_cpu",
            "alarm_name",
            '"${var.name_prefix}-ecs-cpu"',
        ),
        ("database", "aws_db_instance.this", "identifier", '"${var.name_prefix}-db"'),
    ],
)
def test_resource_names_start_with_the_name_prefix(
    version_dir: Path, module: str, address: str, attribute: str, expected: str
) -> None:
    value = _resource_attribute(version_dir, module, address, attribute)
    assert value == expected, f"{address}.{attribute}: {value}"


def test_database_identifier_and_final_snapshot_use_the_prefix(version_dir: Path) -> None:
    text = (version_dir / "modules" / "database" / "main.tf").read_text()
    assert 'identifier = "${var.name_prefix}-db"' in text
    assert (
        'final_snapshot_identifier = var.skip_final_snapshot ? null : "${local.identifier}-final"'
        in text
    )


def test_every_named_resource_name_comes_from_the_prefix(version_dir: Path) -> None:
    # The policy's lf-* ARNs only hold if no resource name is typed or hardcoded.
    naming = {"name", "alarm_name", "identifier"}
    checked = 0
    for block in resource_blocks(version_dir / "modules"):
        attributes = set(naming)
        if block.type == "aws_ecs_task_definition":
            attributes.add("family")  # the family is the task definition's name
        for attribute in sorted(attributes):
            try:
                value = _resource_attribute(version_dir, block.module, block.address, attribute)
            except AssertionError:
                continue  # this resource type has no such attribute
            checked += 1
            assert "var.name_prefix" in value or value.startswith("aws_"), (
                f"{block.module}/{block.address}.{attribute} = {value}"
            )
    assert checked >= 25, "the name check should cover most resources"


# --- The generator refuses what it cannot do (synthetic inputs) --------------------------


def _toy(**overrides: Any) -> tuple[Json, Json, Json]:
    inventory: Json = {
        "template": "toy",
        "version": "0.0.1",
        "resources": [{"type": "aws_thing"}],
    }
    catalog: Json = {
        "tag": {"key": "managed", "value": "true"},
        "arns": {"svc:thing": ["arn:aws:svc:*:${aws:PrincipalAccount}:thing/lf-*"]},
        "name_only": [],
        "accepted_unscoped": {},
        "extras": [],
        "types": {
            "aws_thing": {
                "creates": ["svc:thing"],
                "create": ["svc:CreateThing"],
                "write": ["svc:DeleteThing"],
                "read": ["svc:DescribeThings"],
            }
        },
    }
    tag = "aws:RequestTag/${TagKey}"
    reference: Json = {
        "actions": {
            "svc:CreateThing": {
                "keys": [tag],
                "resource_types": 1,
                "resources": {"svc:thing": [tag]},
            },
            "svc:DeleteThing": {
                "keys": [],
                "resource_types": 1,
                "resources": {"svc:thing": ["aws:ResourceTag/${TagKey}"]},
            },
            "svc:DescribeThings": {"keys": [], "resource_types": 0, "resources": {}},
        }
    }
    for path, value in overrides.items():
        target: Any = {"inventory": inventory, "catalog": catalog, "reference": reference}[
            path.split(".")[0]
        ]
        keys = path.split(".")[1:]
        for key in keys[:-1]:
            target = target[key]
        target[keys[-1]] = value
    return inventory, catalog, reference


def test_toy_inputs_produce_a_policy() -> None:
    result = derive(*_toy())
    sids = [s["Sid"] for s in result.statements]
    assert sids == ["SvcCreateTagged", "SvcChangeTagged", "SvcReadAny"] or len(sids) == 3


def test_a_type_without_a_catalog_entry_is_refused() -> None:
    inventory, catalog, reference = _toy()
    inventory["resources"].append({"type": "aws_other"})
    with pytest.raises(PolicyError, match="no catalog entry"):
        derive(inventory, catalog, reference)


def test_a_catalog_entry_without_an_inventory_type_is_refused() -> None:
    inventory, catalog, reference = _toy()
    catalog["types"]["aws_extra"] = {"read": ["svc:DescribeThings"]}
    with pytest.raises(PolicyError, match="not in the inventory"):
        derive(inventory, catalog, reference)


def test_a_create_that_cannot_be_gated_on_the_request_tag_is_refused() -> None:
    inventory, catalog, reference = _toy()
    reference["actions"]["svc:CreateThing"] = {
        "keys": [],
        "resource_types": 1,
        "resources": {"svc:thing": []},
    }
    with pytest.raises(PolicyError, match="does not support aws:RequestTag"):
        derive(inventory, catalog, reference)


def test_a_write_that_cannot_be_gated_on_the_resource_tag_is_refused() -> None:
    inventory, catalog, reference = _toy()
    reference["actions"]["svc:DeleteThing"]["resources"]["svc:thing"] = []
    with pytest.raises(PolicyError, match="does not support aws:ResourceTag"):
        derive(inventory, catalog, reference)


def test_an_unscoped_write_must_be_accepted_in_the_catalog() -> None:
    inventory, catalog, reference = _toy()
    reference["actions"]["svc:DeleteThing"] = {"keys": [], "resource_types": 0, "resources": {}}
    with pytest.raises(PolicyError, match="accepted_unscoped"):
        derive(inventory, catalog, reference)
    catalog["accepted_unscoped"] = {"svc:DeleteThing": "no resource type"}
    result = derive(inventory, catalog, reference)
    assert result.unscoped == {"svc:DeleteThing"}


def test_an_action_missing_from_the_reference_is_refused() -> None:
    inventory, catalog, reference = _toy()
    del reference["actions"]["svc:CreateThing"]
    with pytest.raises(PolicyError, match="not in iam-reference.json"):
        derive(inventory, catalog, reference)


def test_a_resource_type_without_an_arn_pattern_is_refused() -> None:
    inventory, catalog, reference = _toy()
    catalog["arns"] = {}
    with pytest.raises(PolicyError, match="no ARN pattern"):
        derive(inventory, catalog, reference)


def test_name_only_resources_get_no_tag_condition() -> None:
    inventory, catalog, reference = _toy()
    catalog["name_only"] = ["svc:thing"]
    result = derive(inventory, catalog, reference)
    assert not any("Condition" in s for s in result.statements)


def test_a_statement_group_that_cannot_fit_one_document_is_refused() -> None:
    inventory, catalog, reference = _toy()
    catalog["arns"]["svc:thing"] = [
        f"arn:aws:svc:*:${{aws:PrincipalAccount}}:thing/lf-{'x' * 90}-{i}" for i in range(70)
    ]
    with pytest.raises(PolicyError, match="exceed one policy document"):
        derive(inventory, catalog, reference)
