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
      inventory.json              # resource inventory (see below)
      sandbox-policy.json         # cross-account role policy, derived from inventory
      modules/
        network/    main.tf variables.tf outputs.tf
        compute/    main.tf variables.tf outputs.tf
        database/   main.tf variables.tf outputs.tf
        monitoring/ main.tf variables.tf outputs.tf
        iam/        main.tf variables.tf outputs.tf
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
| `monitoring.log_retention_days` | monitoring | enum | CloudWatch-valid values from 7 to 365 | 30 |

Cross-field rules live in the schema (`max_tasks >= min_tasks`). Intake-derived
fields (region, workload) are not template parameters; the region is a project
input and the renderer passes it to the provider. Nothing in the schema selects a
service outside Requirement 1.

## Resource inventory

`inventory.json` lists every Terraform resource type the template can create, the
module that owns it, the graph node type it maps to, and a pricing hint. It is the
single place that answers "what is in the template":

- The **renderer** and **diagram** specs use it to build and check the
  architecture graph and the parity check.
- The **estimate** spec uses the pricing hints to query the AWS Pricing API.
- The **sandbox policy** is generated from it (see below).

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
  "type": "aws_nat_gateway",
  "module": "network",
  "node": "nat_gateway",
  "pricing": { "service": "AmazonEC2", "dimension": "nat-gateway-hours" }
}
```

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

The renderer (generation spec) fills `root/*.tmpl` and writes parameter values
into `variables.tf` defaults. The rendered root:

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
