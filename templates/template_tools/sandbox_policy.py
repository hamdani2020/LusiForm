"""Derive the cross-account sandbox policy from a template version's inventory.

Inputs, all under `templates/startup/<version>/`:

- `inventory.json`      the resource blocks the template can create (task 9.1)
- `iam-catalog.json`    the IAM actions each Terraform resource type needs (hand-maintained)
- `iam-reference.json`  AWS's own facts about those actions and resource types

Output: `sandbox-policy.json`, an IAM policy document. The sandbox role gets exactly this
policy, so a change to the template's resource types needs a new template version.

How actions are scoped (the catalog says which role each action plays for its resource type):

- create   gated on the request tag (`aws:RequestTag/lusiform-managed`); existing resources
           the call touches (the VPC for a subnet) are gated on the resource tag.
- write    gated on the resource tag.
- read     scoped to the resource ARNs when AWS supports resource-level permissions for the
           action, otherwise `*`; gated on the resource tag where the resource type has one.
- tag      tag-on-create is gated on the request tag and, where AWS offers the key, on the
           CreateAction; changes to existing tags on the resource tag.

ARNs also carry the `lf-` name prefix where the resource has a name. Where AWS offers no way
to scope an action, the generator refuses unless the catalog lists it in `accepted_unscoped`.

Run `python -m template_tools.sandbox_policy <version-dir>` to rewrite the file, or add
`--check` to fail when the committed file is out of date.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

Json = dict[str, Any]

# Statement order and Sid names. Anything not listed sorts last by prefix.
SERVICE_TITLES = {
    "ec2": "Ec2",
    "elasticloadbalancing": "Elb",
    "ecs": "Ecs",
    "application-autoscaling": "AppAutoScaling",
    "cloudwatch": "CloudWatch",
    "logs": "Logs",
    "rds": "Rds",
    "kms": "Kms",
    "iam": "Iam",
    "secretsmanager": "SecretsManager",
}
SERVICE_ORDER = list(SERVICE_TITLES)
ROLE_TITLES = {
    "request": "CreateTagged",
    "request-any": "CreateTaggedAnyResource",
    "tag-create": "TagOnCreate",
    "resource": "ChangeTagged",
    "name": "ByName",
    "any-read": "ReadAny",
    "any-write": "ChangeAnyResource",
}
ROLE_ORDER = list(ROLE_TITLES)

# IAM allows 6,144 characters (whitespace not counted) in a customer managed policy and ten
# managed policies per role by default. Documents stay under this, with headroom.
MAX_DOCUMENT_CHARACTERS = 5900
SCHEMA = "lusiform.sandbox-policy/1"


# Tag actions that remove tags. Only the others can tag a resource as it is created.
REMOVE_TAG_PREFIXES = ("Delete", "Untag", "Remove")


class PolicyError(ValueError):
    """The catalog asks for something the reference says AWS cannot do, or is incomplete."""


@dataclass
class Grant:
    """One permission before statements are merged."""

    role: str
    service: str
    actions: set[str]
    resources: set[str]
    condition: Json = field(default_factory=dict)
    create_actions: set[str] = field(default_factory=set)
    why: str = ""


@dataclass(frozen=True)
class Result:
    document: Json  # the wrapper written to sandbox-policy.json
    statements: list[Json]  # every statement, in order
    actions_by_type: dict[str, set[str]]
    unscoped: set[str]


# --- Reference helpers -------------------------------------------------------------------


class Reference:
    def __init__(self, data: Json) -> None:
        self.actions: dict[str, Json] = data["actions"]

    def info(self, action: str) -> Json:
        try:
            return self.actions[action]
        except KeyError:
            raise PolicyError(
                f"{action} is not in iam-reference.json; rebuild the reference"
            ) from None

    def labels(self, action: str) -> set[str]:
        return set(self.info(action)["resources"])

    def total(self, action: str) -> int:
        return int(self.info(action)["resource_types"])

    def supports(self, action: str, label: str | None, key_prefix: str) -> bool:
        info = self.info(action)
        keys = set(info["keys"])
        if label is not None:
            keys |= set(info["resources"].get(label, []))
        return any(k.startswith(key_prefix) for k in keys)


def service_of(action: str) -> str:
    return action.split(":", 1)[0]


# --- Conditions --------------------------------------------------------------------------


def _merge_conditions(*parts: Json) -> Json:
    merged: Json = {}
    for part in parts:
        for operator, keys in part.items():
            target = merged.setdefault(operator, {})
            for key, value in keys.items():
                if key in target and target[key] != value:
                    raise PolicyError(f"conflicting condition values for {operator} {key}")
                target[key] = value
    return merged


def _tag_condition(kind: str, tag: Json) -> Json:
    return {"StringEquals": {f"aws:{kind}Tag/{tag['key']}": tag["value"]}}


# --- Generation --------------------------------------------------------------------------


def derive(inventory: Json, catalog: Json, reference_data: Json) -> Result:
    ref = Reference(reference_data)
    tag = catalog["tag"]
    arns: dict[str, list[str]] = catalog["arns"]
    name_only = set(catalog["name_only"])
    accepted_unscoped: dict[str, str] = catalog["accepted_unscoped"]

    types = sorted({entry["type"] for entry in inventory["resources"]})
    missing = [t for t in types if t not in catalog["types"]]
    if missing:
        raise PolicyError(f"no catalog entry for resource types: {missing}")
    orphans = [t for t in catalog["types"] if t not in types]
    if orphans:
        raise PolicyError(f"catalog entries for types not in the inventory: {orphans}")

    grants: list[Grant] = []
    actions_by_type: dict[str, set[str]] = {t: set() for t in types}
    unscoped: set[str] = set()

    def patterns(label: str) -> set[str]:
        if label not in arns:
            raise PolicyError(f"no ARN pattern for resource type {label}")
        return set(arns[label])

    def gated(label: str) -> bool:
        return label not in name_only

    def add(
        role: str, action: str, resources: set[str], condition: Json | None = None, **kw: Any
    ) -> None:
        grants.append(
            Grant(role, service_of(action), {action}, set(resources), condition or {}, **kw)
        )

    def resource_grants(t: str, action: str, labels: list[str], tag_kind: str) -> None:
        """Grants for an action on existing resources (write, read, or `uses` on create)."""
        info_labels = ref.labels(action)
        matched = [label for label in labels if label in info_labels]
        if not matched:
            if ref.total(action) == 0:
                role = "any-read" if tag_kind == "read" else "any-write"
                if role == "any-write" and action not in accepted_unscoped:
                    raise PolicyError(
                        f"{t}: {action} cannot be scoped to resources; add it to accepted_unscoped"
                    )
                if role == "any-write":
                    unscoped.add(action)
                add(role, action, {"*"})
                return
            # The action accepts resource types beyond the type's own labels (for example a
            # describe call that reads the VPC); scope it to every catalog type it accepts.
            matched = sorted(info_labels)
            if not matched:
                raise PolicyError(
                    f"{t}: {action} needs a resource type that has no ARN pattern in the catalog"
                )
        for label in matched:
            if gated(label):
                if not ref.supports(action, label, "aws:ResourceTag/"):
                    raise PolicyError(f"{t}: {action} does not support aws:ResourceTag on {label}")
                add("resource", action, patterns(label), _tag_condition("Resource", tag))
            else:
                add("name", action, patterns(label))

    for t in types:
        entry = catalog["types"][t]
        creates: list[str] = entry.get("creates", [])
        uses: list[str] = entry.get("uses", [])
        own = creates + uses

        for action in entry.get("create", []):
            actions_by_type[t].add(action)
            labels = ref.labels(action)
            made = [label for label in creates if label in labels]
            touched = [label for label in uses if label in labels]
            if not made and not touched and ref.total(action) > 0:
                raise PolicyError(f"{t}: {action} accepts none of {creates + uses}")
            if ref.total(action) == 0:
                if not ref.supports(action, None, "aws:RequestTag/"):
                    raise PolicyError(f"{t}: {action} cannot be gated on the request tag")
                if action not in accepted_unscoped:
                    raise PolicyError(f"{t}: {action} applies to '*'; add it to accepted_unscoped")
                unscoped.add(action)
                add("request-any", action, {"*"}, _tag_condition("Request", tag))
            for label in made:
                if gated(label):
                    if not ref.supports(action, label, "aws:RequestTag/"):
                        raise PolicyError(
                            f"{t}: {action} does not support aws:RequestTag on {label}"
                        )
                    add("request", action, patterns(label), _tag_condition("Request", tag))
                else:
                    add("name", action, patterns(label))
            for label in touched:
                if gated(label):
                    if not ref.supports(action, label, "aws:ResourceTag/"):
                        raise PolicyError(
                            f"{t}: {action} does not support aws:ResourceTag on {label}"
                        )
                    add("resource", action, patterns(label), _tag_condition("Resource", tag))
                else:
                    add("name", action, patterns(label))

        for action in entry.get("write", []):
            actions_by_type[t].add(action)
            resource_grants(t, action, own, "write")

        for action in entry.get("read", []):
            actions_by_type[t].add(action)
            resource_grants(t, action, own, "read")

        for action in entry.get("tag", []):
            actions_by_type[t].add(action)
            labels = ref.labels(action)
            targets = [label for label in creates if label in labels]
            if not targets:
                raise PolicyError(f"{t}: tag action {action} accepts none of {creates}")
            create_names = {a.split(":", 1)[1] for a in entry.get("create", [])}
            removes_tags = action.split(":", 1)[1].startswith(REMOVE_TAG_PREFIXES)
            for label in targets:
                if not gated(label):
                    add("name", action, patterns(label))
                    continue
                if not removes_tags and ref.supports(action, label, "aws:RequestTag/"):
                    create_key = f"{service_of(action)}:CreateAction"
                    has_create_action = create_key in ref.info(action)["keys"]
                    add(
                        "tag-create",
                        action,
                        patterns(label),
                        _tag_condition("Request", tag),
                        create_actions=create_names if has_create_action else set(),
                    )
                if ref.supports(action, label, "aws:ResourceTag/"):
                    add("resource", action, patterns(label), _tag_condition("Resource", tag))
                else:
                    add("name", action, patterns(label))

    # Extras: statements the provider's own calls do not show.
    extras: list[Grant] = []
    for extra in catalog["extras"]:
        if not any(t in types for t in extra["for"]):
            continue
        resources: set[str] = set()
        for resource in extra["resources"]:
            resources |= patterns(resource) if resource in arns else {resource}
        condition: Json = extra.get("condition", {})
        if extra.get("tag") == "resource":
            condition = _merge_conditions(_tag_condition("Resource", tag), condition)
        actions = set(extra["actions"])
        for t in extra["for"]:
            if t in actions_by_type:
                actions_by_type[t] |= actions
        extras.append(
            Grant(
                "extra:" + extra["id"],
                service_of(sorted(actions)[0]),
                actions,
                resources,
                condition,
                why=extra.get("why", ""),
            )
        )

    tagged = _assemble(grants, extras)
    statements = [statement for _, statement in tagged]
    document = _package(inventory, tagged)
    return Result(document, statements, actions_by_type, unscoped)


def _assemble(grants: list[Grant], extras: list[Grant]) -> list[tuple[str, Json]]:
    """Merge grants into statements: one per (service, role), actions and ARNs unioned.

    Unioning is safe within a service: AWS checks each action only against the resource types
    that action accepts, so an ARN meant for another action's resource type is never matched.
    """
    groups: dict[tuple[str, str, str], Grant] = {}
    for g in grants:
        key = (g.service, g.role, json.dumps(g.condition, sort_keys=True))
        merged = groups.get(key)
        if merged is None:
            groups[key] = Grant(
                g.role,
                g.service,
                set(g.actions),
                set(g.resources),
                g.condition,
                set(g.create_actions),
            )
        else:
            merged.actions |= g.actions
            merged.resources |= g.resources
            merged.create_actions |= g.create_actions

    ordered = sorted(
        groups.values(),
        key=lambda g: (
            SERVICE_ORDER.index(g.service) if g.service in SERVICE_ORDER else len(SERVICE_ORDER),
            g.service,
            ROLE_ORDER.index(g.role),
        ),
    )

    statements: list[tuple[str, Json]] = []
    used: dict[str, int] = defaultdict(int)
    for g in ordered:
        condition = json.loads(json.dumps(g.condition))
        if g.role == "tag-create" and g.create_actions:
            condition = _merge_conditions(
                condition, {"StringEquals": {f"{g.service}:CreateAction": sorted(g.create_actions)}}
            )
        base = f"{SERVICE_TITLES.get(g.service, g.service.title())}{ROLE_TITLES[g.role]}"
        used[base] += 1
        sid = base if used[base] == 1 else f"{base}{used[base]}"
        statements.append((g.service, _statement(sid, g.actions, g.resources, condition)))

    for g in sorted(extras, key=lambda g: g.role):
        statements.append(
            (g.service, _statement(g.role.split(":", 1)[1], g.actions, g.resources, g.condition))
        )

    return statements


def characters(value: Json | list[Json]) -> int:
    """Policy size as IAM counts it: characters in the compact JSON, whitespace excluded."""
    return len("".join(json.dumps(value, separators=(",", ":")).split()))


def _package(inventory: Json, tagged: list[tuple[str, Json]]) -> Json:
    """Pack statements into documents that fit the managed policy size limit.

    Statements of one service stay together. Services are placed largest first into the first
    document with room, so the result is deterministic.
    """
    by_service: dict[str, list[Json]] = defaultdict(list)
    for service, statement in tagged:
        by_service[service].append(statement)

    overhead = characters({"Version": "2012-10-17", "Statement": []})

    def order(service: str) -> int:
        return SERVICE_ORDER.index(service) if service in SERVICE_ORDER else len(SERVICE_ORDER)

    sizes = {svc: characters(sts) for svc, sts in by_service.items()}
    bins: list[dict[str, Any]] = []
    for service in sorted(by_service, key=lambda svc: (-sizes[svc], order(svc), svc)):
        if sizes[service] + overhead > MAX_DOCUMENT_CHARACTERS:
            raise PolicyError(f"the {service} statements alone exceed one policy document")
        for candidate in bins:
            if candidate["size"] + sizes[service] <= MAX_DOCUMENT_CHARACTERS:
                candidate["services"].append(service)
                candidate["size"] += sizes[service]
                break
        else:
            bins.append({"services": [service], "size": overhead + sizes[service]})

    bins.sort(key=lambda b: min(order(svc) for svc in b["services"]))
    documents: list[Json] = []
    for number, candidate in enumerate(bins, start=1):
        services = sorted(candidate["services"], key=lambda svc: (order(svc), svc))
        statements = [st for svc in services for st in by_service[svc]]
        policy = {"Version": "2012-10-17", "Statement": statements}
        documents.append(
            {
                "name": f"part{number}",
                "services": services,
                "characters": characters(policy),
                "policy": policy,
            }
        )

    return {
        "schema": SCHEMA,
        "template": inventory["template"],
        "version": inventory["version"],
        "max_document_characters": 6144,
        "documents": documents,
    }


def _statement(sid: str, actions: set[str], resources: set[str], condition: Json) -> Json:
    # A single action or resource is written as a string, several as a sorted list.
    action: str | list[str] = sorted(actions) if len(actions) > 1 else sorted(actions)[0]
    resource: str | list[str] = sorted(resources) if len(resources) > 1 else sorted(resources)[0]
    statement: Json = {"Sid": sid, "Effect": "Allow", "Action": action, "Resource": resource}
    if condition:
        statement["Condition"] = {
            op: dict(sorted(keys.items())) for op, keys in sorted(condition.items())
        }
    return statement


# --- Files -------------------------------------------------------------------------------


def render(document: Json) -> str:
    return json.dumps(document, indent=2) + "\n"


def generate(version_dir: Path) -> Result:
    inventory = json.loads((version_dir / "inventory.json").read_text())
    catalog = json.loads((version_dir / "iam-catalog.json").read_text())
    reference = json.loads((version_dir / "iam-reference.json").read_text())
    return derive(inventory, catalog, reference)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate or check sandbox-policy.json")
    parser.add_argument("version_dir", type=Path)
    parser.add_argument("--check", action="store_true", help="fail if the file is out of date")
    args = parser.parse_args(argv)

    result = generate(args.version_dir)
    text = render(result.document)
    target = args.version_dir / "sandbox-policy.json"
    if args.check:
        if not target.is_file() or target.read_text() != text:
            command = f"python -m template_tools.sandbox_policy {args.version_dir}"
            print(f"{target} is out of date; run {command}")
            return 1
        print(f"{target} is up to date")
        return 0
    target.write_text(text)
    docs = result.document["documents"]
    sizes = ", ".join(f"{d['name']}={d['characters']}" for d in docs)
    count = len(result.statements)
    print(f"wrote {target} ({count} statements in {len(docs)} documents; characters: {sizes})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
