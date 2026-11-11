# Design: Startup Template

## Overview

This design defines the files, schema, module interfaces, and tests that make up
the startup reference architecture. The renderer (generation spec) consumes it;
the validators (validation spec) gate it; the diagram and estimate specs derive
from its resource inventory. Everything here lives under `templates/` and is
versioned as files, as the Technical Design requires.

It realizes `requirements.md` and follows `tech.md`, `terraform.md`, and
`security.md`.

## Layout

```
templates/
  startup/
    1.0.0/                        # one directory per template version (immutable once published)
      template.json               # metadata: version, status, review, tool versions
      schema.json                 # parameter schema (JSON Schema)
      inventory.json              # resource inventory, one entry per resource block (see below)
      iam-catalog.json            # IAM actions each resource type needs (hand-maintained)
      iam-reference.json          # AWS's facts about those actions (generated, committed)
      sandbox-policy.json         # cross-account role policy documents, generated from the above
      modules/
        network/    main.tf variables.tf outputs.tf versions.tf
        compute/    main.tf variables.tf outputs.tf versions.tf
        database/   main.tf variables.tf outputs.tf versions.tf
        monitoring/ main.tf variables.tf outputs.tf versions.tf
        iam/        main.tf variables.tf outputs.tf versions.tf
      tests/                      # Terraform tests per module, outside modules/ so they are never rendered
        network/ compute/ database/ monitoring/ iam/    (*.tftest.hcl)
        .terraform.lock.hcl       # provider lock used when module tests run
      root/                       # templates for the rendered root project
        main.tf.tmpl
        variables.tf.tmpl
        outputs.tf.tmpl
        terraform.tfvars.example.tmpl
        README.md.tmpl
      fixtures/
        params/                   # parameter sets used by tests (min, default, max, az1, az2)
        golden/                   # stored rendered output per parameter set
        insecure/                 # deliberately insecure project that must fail Checkov
  README.md
```

Modules are static HCL. The only generated parts are the `root/` templates and
the parameter values. A template version directory is never edited after it is
published; a change creates a new directory (`1.0.1`, `1.1.0`, and so on).

### template.json

```json
{
  "template": "startup",
  "version": "1.0.0",
  "status": "draft",
  "terraform": ">= 1.10.0",
  "aws_provider": "~> 5.47",
  "tools": { "tflint": "<pinned>", "checkov": "<pinned>" },
  "review": { "reviewed_by": null, "reviewed_at": null, "notes_ref": null }
}
```

`status` mirrors the `template_versions` row. A version cannot become
`published` while `review.reviewed_by` is null (Requirement 6). The check runs in
CI and in the publish step.

## Parameter schema

`schema.json` is JSON Schema. One definition feeds the renderer's validation and
the Architecture-stage UI, so allowed values never drift (Requirement 2.4). The
bounds below match the validated Architecture-stage screen.

| Parameter | Module | Type | Allowed | Default |
| --- | --- | --- | --- | --- |
| `compute.task_size` | compute | enum | `0.25vcpu-0.5gb`, `0.5vcpu-1gb`, `1vcpu-2gb`, `2vcpu-4gb` | `0.25vcpu-0.5gb` |
| `compute.min_tasks` | compute | integer | 1–10 | 2 |
| `compute.max_tasks` | compute | integer | 2–20, `>= min_tasks` | 6 |
| `database.instance_class` | database | enum | `db.t4g.micro`, `db.t4g.small`, `db.t4g.medium` | `db.t4g.micro` |
| `database.storage_gb` | database | integer | 20–1000 | 20 |
| `database.backup_retention_days` | database | integer | 1–35 | 7 |
| `network.az_count` | network | enum | 1, 2 | 2 |
| `monitoring.log_retention_days` | monitoring | enum | `7`, `14`, `30`, `90`, `365` | 30 |

Cross-field rules live in the schema (`max_tasks >= min_tasks`). Intake-derived
fields (region, workload) are not template parameters; the region is a project
input and the renderer passes it to the provider. Nothing in the schema selects a
service outside Requirement 1.

## Resource inventory

`inventory.json` lists every Terraform resource block the template can create: the module
that owns it, its address within the module, its type, how many instances it has, how it
is represented in the architecture graph, and its pricing hints. It is the single place
that answers "what is in the template":

- The **renderer** and **diagram** specs use it to build and check the
  architecture graph and the parity check. Each entry gives the graph address
  (`module.<module>.<address>`), whether the block is a drawn `node`, a `group`
  container (the VPC and subnets), or `hidden`, and its instance count (`fixed`, a
  template `parameter` such as `network.az_count`, or `optional` for the HTTPS listener).
- The **estimate** spec uses the pricing hints to query the AWS Pricing API.
- The **sandbox policy** is generated from it (see below).

The inventory is per block, not per type, because the graph has one node per resource
address and the same type appears more than once in a module (three subnet tiers, four
alarms, four roles). The set of Terraform types, 29 in all, is derived from it.

| Module | Resource types |
| --- | --- |
| network | `aws_vpc`, `aws_internet_gateway`, `aws_subnet`, `aws_route_table`, `aws_route_table_association`, `aws_route`, `aws_nat_gateway`, `aws_eip`, `aws_default_security_group`, `aws_flow_log` |
| compute | `aws_ecs_cluster`, `aws_ecs_task_definition`, `aws_ecs_service`, `aws_lb`, `aws_lb_target_group`, `aws_lb_listener`, `aws_security_group`, `aws_appautoscaling_target`, `aws_appautoscaling_policy` |
| database | `aws_db_instance`, `aws_db_subnet_group`, `aws_db_parameter_group`, `aws_security_group`, `aws_kms_key`, `aws_kms_alias` |
| monitoring | `aws_cloudwatch_log_group`, `aws_cloudwatch_metric_alarm`, `aws_kms_key`, `aws_kms_alias` |
| iam | `aws_iam_role`, `aws_iam_role_policy_attachment`, `aws_iam_policy` |

An entry looks like:

```json
{
  "module": "network",
  "address": "aws_nat_gateway.this",
  "type": "aws_nat_gateway",
  "representation": "node",
  "node": "nat_gateway",
  "instances": { "parameter": "network.az_count" },
  "pricing": [
    { "hint": "nat_gateway_hours", "service": "AmazonEC2" },
    { "hint": "nat_data_processed_gb", "service": "AmazonEC2" }
  ]
}
```

Pricing hints are the line items of the generation-pipeline estimate table, plus
`public_ipv4_hours` for the public IPv4 address charge on the NAT gateways' Elastic IPs,
which that table does not list. A test compares the inventory to the module files, so a
resource block cannot be added without it.

Route 53, ACM, and S3 are deliberately absent: the customer owns DNS and
certificates, and the template has no application bucket. (See open questions.)

## Module design

All modules take a `name_prefix` and `tags` input, expose only the outputs other
modules need, and avoid `timestamp()`, `random_*`, and data sources that vary by
account or time, so rendering stays deterministic.

### network

- One VPC. **Subnets are always created in two Availability Zones**, and the
  `az_count` parameter controls what runs in them (see decision below).
- Per AZ: a public subnet, a private application subnet, an isolated data subnet.
- Internet gateway for public subnets. NAT gateway per active AZ for private
  egress. Data subnets have no route to the internet.
- Default security group locked down. VPC flow logs enabled to CloudWatch.

**Decision: why two AZs of subnets even when `az_count = 1`.** An Application Load
Balancer and an RDS subnet group each require subnets in at least two AZs, so a
true single-AZ footprint cannot be built. The design therefore creates subnets in
two AZs always, and `az_count` controls the **workload**: number of NAT gateways,
where Fargate tasks are placed, and whether the database has a standby. With
`az_count = 1` the workload runs in the first AZ only and RDS is single-AZ; with
`az_count = 2` tasks spread across both AZs, a NAT gateway exists per AZ, and RDS
is Multi-AZ. This matches the Technical Design ("two AZs where the parameter
requires it") and the UI's 1 to 2 range. Flagged for expert review.

### compute

- ECS cluster with Container Insights, one Fargate service, one task definition.
  Task CPU and memory come from `task_size`. Desired count starts at `min_tasks`;
  Application Auto Scaling scales between `min_tasks` and `max_tasks` on CPU.
- Public ALB in the public subnets, security group allowing 80/443 from the
  internet and forwarding to the tasks. Tasks run in private subnets with a
  security group that only accepts traffic from the ALB.
- The container image is an input variable (`container_image`) supplied at deploy
  time through `terraform.tfvars.example`. No account-specific registry URL is
  baked into the template.
- Task execution role and task role come from the IAM module.

### database

- RDS PostgreSQL 16, engine version pinned, in the data subnets via a subnet
  group, no public access, storage encrypted with a customer-managed KMS key,
  storage autoscaling allowed up to a ceiling above `storage_gb`.
- `multi_az = (az_count == 2)`. Backup retention from `backup_retention_days`.
  Deletion protection and final snapshot configured for non-sandbox use; the
  sandbox teardown path (sandbox spec) must be able to destroy, so these are
  variables with safe defaults.
- Security group accepts PostgreSQL only from the compute tasks' security group.
- Master credentials are managed by RDS in Secrets Manager
  (`manage_master_user_password`); the template never contains a password.

### monitoring

- One CloudWatch log group for the ECS service, encrypted with KMS, with
  `log_retention_days`. A small set of alarms (ALB 5xx, ECS CPU, RDS CPU and free
  storage). No custom dashboards in the MVP.

### iam

- ECS task execution role (managed ECS execution policy) and a task role with only
  the permissions the workload declares. No wildcard resource grants. No inline
  policy with `*` actions.

## Rendered project

The renderer (generation spec) fills `root/*.tmpl` (Jinja2, plain `{{ dotted.name }}`
expressions only; the environment and context contract are in `templates/README.md`) and
writes parameter values into `variables.tf` defaults. The rendered root:

- declares `terraform { required_version = ">= 1.10.0" }` and the pinned provider;
- configures `backend "s3" { use_lockfile = true }` with **no** bucket, key, or
  account values, which are supplied at plan time with `-backend-config` by the
  worker, so no account ID is ever in the files;
- instantiates the five modules and wires their outputs;
- includes a generated README listing the template version, parameters, and
  commands to run the project.

## Cross-account sandbox policy

`sandbox-policy.json` is generated from `inventory.json`: for every resource type
in the inventory, it grants only the IAM actions needed to create, read, update,
and delete that type, scoped by resource ARN patterns and a tag condition on the
`lusiform-managed` tag where the service supports it. It is part of the template
version, so any change to the resource types or the policy requires a new version
(Requirement 5.4). The sandbox spec attaches this policy to the partner's
cross-account role. A test asserts the policy covers every inventory type and
grants nothing else.

### How it is built

Three committed inputs and one generator (`template_tools/sandbox_policy.py`):

- `iam-catalog.json` is hand-maintained. For each Terraform resource type it lists the IAM
  actions by role (create, write, read, tag), the resource types the actions create or
  touch, the ARN pattern of each, and a small set of `extras` the provider's own calls do
  not show (`iam:PassRole`, service-linked roles, the KMS grant and Secrets Manager secret
  that RDS creates on the caller's behalf). The action lists come from the API calls
  reachable from each resource in the pinned provider (`terraform-provider-aws` 5.100.0:
  create, read, update, delete, finders, waiters, and the generated tag helpers), checked by
  hand against AWS documentation.
- `iam-reference.json` is AWS's Service Authorization Reference, reduced to the actions and
  resource types the catalog uses by `scripts/build_iam_reference.py`: which resource types
  each action accepts and which condition keys apply. The generator and the tests both read
  this file, so neither needs the network.
- The generator refuses to emit anything the reference says AWS cannot do. A create must be
  gateable on `aws:RequestTag`, a change on `aws:ResourceTag`; an action with no resource
  type can only be `*`, and the catalog must accept that explicitly (`accepted_unscoped`:
  `ecs:DeregisterTaskDefinition`, and `kms:CreateKey`, which is gated on the request tag).

### Scoping

| Action role | Gate |
| --- | --- |
| create | `aws:RequestTag/lusiform-managed = true` on the resource created; `aws:ResourceTag` on existing resources the call uses (the VPC for a subnet) |
| change, delete | `aws:ResourceTag/lusiform-managed = true` |
| read | the resource ARNs and the resource tag where AWS supports resource-level permissions, otherwise `*` |
| tag on create | the request tag, plus `<service>:CreateAction` where AWS offers it (EC2, Elastic Load Balancing, ECS) |
| remove tags | the resource tag |

Names carry a second gate: every named resource derives its name from `name_prefix`, which
the modules require to start with `lf-`, so ARNs are scoped to `lf-*` for IAM roles and
policies, KMS aliases, log groups, alarms, load balancers, target groups, ECS resources, and
RDS resources. A test checks that the names in the modules match the patterns in the policy.
Resources identified only by a generated id (EC2, KMS keys, Application Auto Scaling
targets) rely on the tag.

The policy uses `${aws:PrincipalAccount}` for the account and `*` for the region, so it
holds no account ID. Only the `aws` partition is supported.

### Size

The full policy is about 18,000 characters, three times IAM's limit for one managed policy
(6,144, whitespace not counted). `sandbox-policy.json` therefore holds several documents,
each under 5,900 characters with a service's statements kept together; a role can hold ten
managed policies by default. The sandbox spec attaches all of them.

### Known gaps

AWS offers no way to scope these, so the policy is broader than the tag and name gates and
says so (listed in `iam-catalog.json` under `known_gaps`, each with a statement the tests name):

- The VPC's default security group is created untagged, so revoking its rules and tagging it
  (`DefaultSecurityGroup`) applies to any security group in the account.
- Application Auto Scaling checks the caller's CloudWatch permissions with calls that carry
  no alarm name, so alarm writes (`AutoScalingAlarmValidation`) apply to every alarm.
- `ecs:DeregisterTaskDefinition` applies to every task definition.
- `lf-*` IAM roles and policies can be created; attachment is limited to two AWS managed
  policies and `lf-*` policies, but an `lf-*` policy's content is not restricted.
- Tag-on-create for services without a `CreateAction` key (Logs, RDS, KMS, IAM, CloudWatch,
  Application Auto Scaling, Secrets Manager) is gated on the request tag only.

The Terraform state bucket is not covered; the sandbox spec must add it.

## Security posture (how Checkov stays clean)

- KMS customer-managed keys for RDS and CloudWatch log groups, with rotation on.
- RDS: encrypted, not public, backups on, deletion protection variable, IAM auth
  and enhanced monitoring where Checkov expects them.
- ALB: drops invalid headers, has deletion protection variable, access logging
  where it does not require an extra bucket (see open question on HTTPS and logs).
- VPC: default security group restricted, flow logs on.
- ECS: Container Insights on, no privileged containers, read-only root filesystem
  where compatible.
- IAM: no wildcard actions or resources.

Low and medium findings (for example a log retention shorter than one year) are
allowed to remain and are reported by the validation spec; only high severity
blocks. The pilot parameter sets must show zero high findings.

## Testing strategy

- **Schema tests:** every default, min, and max passes; each out-of-range and
  wrong-type value is rejected with a message naming the parameter and bound.
- **Module validation:** render each fixture parameter set (min, default, max,
  `az_count` 1, `az_count` 2) into a temporary project, then run `terraform fmt
  -check`, `terraform init -backend=false` plus `validate`, `tflint`, and
  `checkov`; assert all pass with zero high findings.
- **Insecure fixture:** a project with unencrypted RDS, a public database, and a
  wildcard IAM policy must fail Checkov, proving the gate catches violations.
- **No-credentials/account-ID scan:** grep rendered output for access-key
  patterns, 12-digit account IDs, and ARNs containing an account; fail on any hit.
- **Determinism:** render each fixture twice and compare hashes; compare against
  the stored golden output.
- **Inventory completeness:** every resource type found in the modules appears in
  `inventory.json`, and the sandbox policy covers exactly that set.
- **Version immutability:** a published version's file hashes must match a
  recorded manifest; any edit fails CI.
- **Review gate:** a test fails if a version marked `published` has no recorded
  reviewer.

## Open questions

1. **HTTPS on the ALB.** HTTPS needs an ACM certificate, which needs a domain the
   customer owns. Options: (a) HTTP only in the template (Checkov will flag the
   listener; confirm severity), (b) an optional `certificate_arn` input that
   switches the listener to HTTPS, (c) a self-signed or placeholder cert for
   sandbox. Default proposal: (b) with HTTP default in sandbox. Needs the AWS
   expert's call.
2. **Checkov severity.** As far as I know, open-source Checkov leaves the severity
   field empty unless it is connected to a Prisma Cloud or Bridgecrew key. The
   "high severity blocks export" rule therefore needs a severity map maintained by
   us (check ID to severity). This is a validation-spec decision, but the template
   fixtures depend on it. Verify against the pinned Checkov version.
3. **NAT per AZ.** One NAT gateway per active AZ is resilient but is the largest
   fixed cost. Confirm this is the intended default for `az_count = 2`; a shared
   NAT was removed from the parameter set on purpose.
4. **Estimate screen mismatch.** The Estimate stage mock still lists a Route 53
   hosted zone line item. The template does not create one. Either the mock
   changes or the inventory gains Route 53; this spec assumes the mock changes.
5. **KMS key count.** One key per module (database, monitoring) versus one shared
   key. Default: one per module for blast-radius separation.
6. **Reviewer and record.** Who the AWS-experienced reviewer is, and where the
   review record is stored (`notes_ref`).
7. **Deletion protection and sandbox teardown.** The database and load balancer default to
   `deletion_protection = true` and a final snapshot, which is the safe default for a
   handed-off project. A `terraform destroy` fails until those are turned off and applied.
   The sandbox spec must set `deletion_protection = false` (and may set
   `skip_final_snapshot = true`) for teardown. The final snapshot has a fixed name, so a
   second destroy of the same project name fails until the first snapshot is deleted.
8. **RDS engine version.** Pinned to the major version (`"16"`); RDS picks the current minor
   and applies minor upgrades. Pinning a minor risks naming a version AWS has retired.
9. **RDS log exports are off.** Enabling `enabled_cloudwatch_logs_exports` makes RDS create
   unencrypted log groups that Terraform does not manage and that survive teardown.
   Query logging is still configured in the parameter group. Revisit if the reviewer wants
   exports with pre-created, KMS-encrypted groups.
10. **ALB access logs are off.** They need an S3 bucket, which the template deliberately does
    not have. Expect Checkov to report this (the validation spec's severity map decides if
    it blocks).
11. **Plan-time lookups.** The monitoring and iam modules call `aws_caller_identity` (one local
    STS call) so key policies and trust policies can name the account without an account ID
    in the files. This is the one lookup NFR 1 could be read to forbid; confirm it is acceptable.
12. **Flow log role permissions are unverified.** The role is limited to the one flow log group
    (`CreateLogStream`, `PutLogEvents`, `DescribeLogStreams`). AWS documentation lists
    `CreateLogGroup` and `DescribeLogGroups` on `*`. The narrower policy is the intended
    design, but it can only be confirmed by a real apply, which this spec never does. Check
    during the first sandbox apply.
13. **Availability Zone names.** The network module takes the two zone names as an input
    (the root passes `<region>a` and `<region>b`) instead of looking them up, to keep
    rendering deterministic. Some accounts do not have `a` and `b` in every region.
14. **Egress is narrow.** Tasks may reach HTTPS on the internet (through NAT) and PostgreSQL
    in the VPC only. A workload that needs another outbound port needs a new template version.
15. **No provider lock file in the rendered project.** The root templates ship no
    `.terraform.lock.hcl`. A lock file committed from one machine would carry hashes for
    one platform only, and `terraform init` against the worker's filesystem provider mirror
    would fail on another CPU architecture. The worker creates the lock file at its first
    init. The sandbox spec's plan hash covers "the provider lock file"; confirm it hashes the
    one the worker generated, and decide whether the packaged zip should include it.
16. **Deploy-time inputs beyond the eight parameters.** The root also exposes
    `container_image` (required), `container_port`, `health_check_path`, `certificate_arn`,
    `deletion_protection`, and `skip_final_snapshot`. They are not template parameters, so
    they are not in `schema.json` or the Architecture stage, and changing them does not
    create a new project version. Confirm that is the intended split.
17. **Tags come from the provider.** Resources get `lusiform-managed` and the project tags
    through the provider's `default_tags`, not module inputs, so the sandbox policy's tag
    condition depends on Terraform sending them at create time. Verify at the first real
    apply, together with question 12.
18. **The sandbox policy has never run against an account.** Its tests prove it is consistent
    with AWS's reference, not that Terraform succeeds under it. A missing action shows up as an
    `AccessDenied` at apply, and a fix needs a new template version. Do a full create and
    destroy in a throwaway account before the pilot. The assumptions most likely to need a fix
    (all listed in `iam-catalog.json`): `${aws:PrincipalAccount}` inside `Resource` ARNs;
    Application Auto Scaling's permission check on `RegisterScalableTarget` and
    `PutScalingPolicy`; the secret and KMS grant RDS creates for the managed master password;
    and delivery of VPC flow logs with the narrow flow log role (question 12).
19. **Sandbox spec impact.** The policy is several documents (four today), each a managed
    policy of under 5,900 characters; the role needs all of them. The Terraform state bucket
    and any region restriction are not in them. `sandbox-deployment/design.md` describes one
    policy; it needs updating.
20. **`name_prefix` must start with `lf-`.** The modules enforce it because the sandbox policy
    scopes ARNs to `lf-*`. The generation spec must derive it that way, for example `lf-`
    plus the first eight hex characters of the project id.
21. **Estimate gaps.** The generation-pipeline estimate table has no line for the public IPv4
    address charge (about $3.65 a month per NAT gateway, plus the load balancer's addresses),
    which the inventory now hints as `public_ipv4_hours`. The RDS-managed secret (about $0.40
    a month) and the four CloudWatch alarms have no hint; they are small.
22. **Graph representation is a proposal.** The inventory marks the VPC and subnets as groups
    and eight resource kinds as nodes, matching the diagram spec's icon list. If the diagram
    spec wants other nodes drawn, that changes `inventory.json` and so needs a new template
    version.
