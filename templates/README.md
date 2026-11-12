# templates

The startup reference architecture: the one fixed template Lusiform generates for
every project in the MVP, stored as versioned Terraform modules with a parameter
schema. This is the product's output for customers. It is separate from `infra/`,
which deploys Lusiform itself.

Scope is fixed: networking, compute (ECS Fargate), database (RDS PostgreSQL),
logging and monitoring (CloudWatch), and IAM. No EKS, Aurora, ElastiCache,
CloudFront, WAF, third AZ, or Graviton. See `.kiro/specs/startup-template/` and
`.kiro/steering/terraform.md`.

## Layout

```
templates/
  startup/
    <semver>/                 one directory per template version
      template.json           version, status, tool pins, review record
      schema.json             parameter schema (JSON Schema)
      inventory.json          every resource block the template can create
      iam-catalog.json        IAM actions each resource type needs (hand-maintained)
      iam-reference.json      AWS's facts about those actions (generated, committed)
      sandbox-policy.json     cross-account policy documents (generated)
      modules/                static HCL: network, compute, database, monitoring, iam
        <module>/             main.tf variables.tf outputs.tf versions.tf
      root/                   Jinja2 templates for the rendered root project (*.tmpl)
      tests/<module>/         Terraform tests (*.tftest.hcl, mocked AWS provider)
      tests/.terraform.lock.hcl  provider lock used when the module tests run
      tflint.hcl              tflint config for rendered projects (AWS ruleset, pinned)
      fixtures/               params/, golden/, insecure/, checkov-accepted.json
  template_tools/             schema validation and sandbox policy generator (standard library only)
  scripts/                    test runner, IAM reference builder
  tests/                      pytest suite for the template
```

`1.0.0` is a draft until the expert review in task 12 of the `startup-template` spec.

Module tests live in `startup/<version>/tests/`, outside `modules/`, so test fixtures
(fake ARNs and account IDs) can never be copied into a rendered project. The renderer
copies `modules/*/*.tf` only.

## Modules

| Module | Owns | Takes from other modules |
| --- | --- | --- |
| `network` | VPC, subnets in two zones, NAT per active zone, routes, flow log | flow log group (monitoring), flow log role (iam) |
| `monitoring` | KMS key, log groups, four alarms | ALB, ECS, and RDS identifiers (compute, database) |
| `iam` | ECS execution and task roles, flow log role, RDS monitoring role | flow log group (monitoring), DB secret ARN (database) |
| `database` | RDS PostgreSQL 16, KMS key, subnet and parameter groups, security group | data subnets (network), task security group (compute), monitoring role (iam) |
| `compute` | ECS Fargate service, ALB, auto scaling, security groups | subnets (network), roles (iam), log group (monitoring), DB endpoint and secret (database) |

The modules reference each other's outputs but form no resource-level cycle; the root
project wires them together.

Rules the modules follow: AWS provider `~> 5.47` and Terraform `>= 1.10.0`; no
`timestamp()`, `random_*`, or account-specific values; no credentials; the only data
sources are `aws_caller_identity` (one local STS call, for the KMS key policies and the trust
policy conditions), `aws_partition`, and `aws_region`; no IAM wildcard action or bare `*`
resource.

## Versioning rules

- A template version is a semver directory, for example `1.0.4`. Do not confuse it
  with a project version, which is rendered as `v1`, `v2`, and so on.
- A change to any module, `schema.json`, `inventory.json`, or `sandbox-policy.json`
  creates a new version directory. Never edit a published version.
- `status` in `template.json` is `draft`, `published`, or `retired`, and mirrors the
  `template_versions` row. A version cannot be `published` until
  `review.reviewed_by` and `review.reviewed_at` are set.
- The tool pins in `template.json` (`terraform`, `tflint`, `checkov`) must equal the
  pins in `worker/Dockerfile`. A test fails if they drift.
- Generated output is deterministic: the same parameters and template version give
  byte-identical files. Modules avoid `timestamp()`, `random_*`, and account- or
  time-dependent data sources.
- Never run `terraform apply` from this directory. Validation stops at `fmt`,
  `validate`, `tflint`, and `checkov`.

## Root project templates

`root/` holds five Jinja2 templates: `main.tf`, `variables.tf`, `outputs.tf`,
`terraform.tfvars.example`, and `README.md`. The renderer fills them and copies
`modules/*/*.tf` beside them, giving a project with `main.tf` at the top and the five
modules under `modules/`. Rendering is a pure function: the same inputs give the same
bytes.

The root declares Terraform `>= 1.10.0`, the pinned AWS provider, and an S3 backend with
`use_lockfile = true` and `encrypt = true`. The bucket, key, and region are supplied at
init with `-backend-config`, so no account value is in the files. The provider tags every
resource with `lusiform-managed`, `lusiform-project`, and `lusiform-template-version`
through `default_tags`. The project ships no `.terraform.lock.hcl`: the worker creates it at
the first `terraform init` against its provider mirror, so it holds the right platform
hashes.

**Renderer contract.** The templates use only plain `{{ dotted.name }}` expressions: no
block tags, comments, or filters. The Jinja2 environment must use `StrictUndefined`,
autoescape off, and `keep_trailing_newline=True` (Jinja otherwise drops the final newline,
which fails `terraform fmt -check`). The context is:

| Name | Value |
| --- | --- |
| `template_version` | `1.0.0`, from `template.json` |
| `terraform_constraint` | `>= 1.10.0`, from `template.json` |
| `aws_provider_constraint` | `~> 5.47`, from `template.json` |
| `region` | the project's region |
| `name_prefix` | derived from the project id: `lf-` followed by lowercase letters, digits, and hyphens, 4 to 24 characters, not ending in a hyphen (for example `lf-0a1b2c3d`); never typed text. The sandbox policy scopes ARNs to `lf-*`, so the modules refuse any other prefix |
| `project_name`, `customer_name` | display text, already escaped for Markdown; used in `README.md` only |
| `modules` | the parameters nested by module, for example `modules.compute.min_tasks` |

`tests/reference_render.py` is a test-only implementation of this contract. The real
renderer in the generation-pipeline spec must match its output byte for byte, and its
golden tests replace the helper.

## Resource inventory

`inventory.json` has one entry per Terraform resource block in `modules/`: its module, its
address within the module (so the graph address is `module.<module>.<address>`), its type,
how many instances it has, how it is drawn, and its pricing hints.

- `representation`: `node` (drawn as a diagram node of the named `node` type), `group`
  (drawn as a container: the VPC and the subnets, with a `tier`), or `hidden` (listed in
  the graph's `hidden` set).
- `instances`: `{"fixed": n}`, `{"parameter": "network.az_count"}` for a count set by a
  template parameter, or `{"optional": "certificate_arn"}` for 0 or 1 set by a deploy-time
  input that is not a parameter.
- `pricing`: hints for the estimate service. Each names a billable line item and the Pricing
  API service code; the filters and quantity formulas live in the estimate service. Beyond
  the line items in the generation-pipeline design, `public_ipv4_hours` covers the public IPv4
  address charge on the NAT gateways' Elastic IPs.

A test compares the inventory to the module files block for block, including each `count`
expression, so a new or changed block cannot be missed.

## Sandbox policy

The partner's sandbox role is given exactly the permissions the template's resource types
need. `sandbox-policy.json` is generated, not written by hand:

```
iam-catalog.json    what each Terraform resource type needs (you edit this)
iam-reference.json  AWS's own list of actions, resource types, and condition keys
inventory.json      which resource types exist
        │
        ▼  python -m template_tools.sandbox_policy startup/<version>
sandbox-policy.json
```

The file holds several IAM policy documents because the whole policy is larger than IAM's
6,144-character limit for one managed policy; a role can hold ten. Each document stays under
5,900 characters and keeps each service's statements together.

**How actions are scoped.** Creating a resource is allowed only when the request carries the
`lusiform-managed` tag (the root project's `default_tags` set it). Changing or deleting a
resource, and reading it where AWS supports resource-level permissions, requires the resource
to carry that tag. Names are scoped to `lf-*` wherever a resource has a name. Tag-on-create
is limited to the creating action where AWS offers that condition. IAM role attachment is
limited to the two AWS managed policies the template uses and the project's own `lf-*`
policies; `iam:PassRole` is limited to the four named roles and the service that receives
each. Where AWS offers no way to scope an action, the generator refuses unless the catalog
lists it under `accepted_unscoped`, and every broader-than-intended statement is named in
`known_gaps`.

**Commands** (run in the worker container; the repo has no Python on the host):

```
# rewrite or check the policy after editing the catalog or the inventory
docker compose run --rm --no-deps -w /app/templates worker \
  python -m template_tools.sandbox_policy startup/1.0.0
docker compose run --rm --no-deps -w /app/templates worker \
  python -m template_tools.sandbox_policy startup/1.0.0 --check

# refresh the AWS reference (rare): download the nine service files from
# https://servicereference.us-east-1.amazonaws.com/v1/<prefix>/<prefix>.json
# (ec2, elasticloadbalancing, ecs, application-autoscaling, cloudwatch, logs, rds, kms, iam,
# secretsmanager) into a git-ignored directory, then
docker compose run --rm --no-deps -w /app/templates worker \
  python scripts/build_iam_reference.py <dir> startup/1.0.0 --retrieved YYYY-MM-DD
```

**What is and is not verified.** The tests check the policy against the committed AWS
reference: every action exists, is paired with resource types AWS says it accepts, and every
condition key applies to every action in its statement, so no statement is silently dead.
The action lists come from the AWS provider's source (version 5.100.0) and AWS
documentation. The policy has not been run against an account; `iam-catalog.json` lists the
assumptions that only a real apply can confirm.

## Validation fixtures

`startup/<version>/fixtures/` holds what the validators run against:

- `params/` five named parameter sets: `default` (empty, so every default applies), `minimum`
  and `maximum` (the ends of every range), and `az1` and `az2` (mid-range sizing in one and
  two zones). Each also fixes the region, the name prefix, and the display names, so a render
  depends on nothing else.
- `golden/<name>/` the rendered root files exactly as the reference renderer writes them, and
  `manifest.json` with the SHA-256 of every rendered file. Module files are copied unchanged
  from `modules/`, so their hashes pin them without storing five copies. Any difference fails.
- `insecure/` a deliberately insecure project (unencrypted public database, wildcard IAM,
  SSH open to the world). It is never rendered; the tests show Checkov fails it.
- `checkov-accepted.json` the Checkov findings this template version is allowed to have, with
  a severity and a reason for each, and the checks that must pass.

Each fixture is run through, in order: `terraform fmt -check`, `terraform init -backend=false`
then `validate`, tflint with the AWS ruleset, and Checkov. `tflint.hcl` is the tflint
configuration; the ruleset (version in `template.json`) is installed in the worker image.

Two things about the validators are easy to get wrong:

- **tflint must run with `--recursive`.** Run from the project root with only
  `--call-module-type=local`, tflint does not inspect the resources inside the modules; an
  invalid instance class in a module passed cleanly.
- **Checkov reports no severity.** Open-source Checkov 3.4.3 leaves it empty, so severity is
  Lusiform's. The rule is fail-closed: a failing check that is not accepted as LOW or MEDIUM
  is HIGH. `checkov-accepted.json` is the interim map for this template; its `must_pass`
  groups pin the encryption, public-exposure, and wildcard-IAM checks so they cannot stop
  running without a test failing.

If you change the template on purpose, regenerate the golden files and review the diff:

```
docker compose run --rm --no-deps -w /app/templates worker \
  python tests/update_golden.py startup/1.0.0
```

## Running the tests

Tests run in the `worker` container, which carries the pinned Terraform, tflint, and
Checkov. Nothing but Docker is needed on the host.

```
templates/scripts/run-tests.sh                          # whole suite
templates/scripts/run-tests.sh -k pins                  # pass pytest arguments through
templates/scripts/run-tests.sh tests/test_modules_static.py   # fast, no Terraform needed
```

The module tests run `terraform fmt -check`, `init -backend=false`, `validate`, and
`terraform test` with a mocked AWS provider for each module. They never plan or apply
against AWS and need no credentials. The first run downloads the AWS provider (several
hundred MB) into `templates/.tf-plugin-cache/`, which is git-ignored and reused after that.
