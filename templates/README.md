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
      inventory.json          every resource type the template can create
      sandbox-policy.json     cross-account policy derived from the inventory
      modules/                static HCL: network, compute, database, monitoring, iam
        <module>/             main.tf variables.tf outputs.tf versions.tf
      root/                   Jinja2 templates for the rendered root project (*.tmpl)
      tests/<module>/         Terraform tests (*.tftest.hcl, mocked AWS provider)
      tests/.terraform.lock.hcl  provider lock used when the module tests run
      fixtures/               params/, golden/, insecure/ used by tests
  template_tools/             schema validation (standard library only)
  scripts/                    test runner
  tests/                      pytest suite for the template
```

`inventory.json` and `sandbox-policy.json` are added by later tasks of the
`startup-template` spec. `1.0.0` is a draft until then.

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
sources are `aws_caller_identity` (one local STS call, for the KMS key policy and trust
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
| `name_prefix` | derived from the project id (3 to 24 characters, lowercase letters, digits, hyphens); never typed text |
| `project_name`, `customer_name` | display text, already escaped for Markdown; used in `README.md` only |
| `modules` | the parameters nested by module, for example `modules.compute.min_tasks` |

`tests/reference_render.py` is a test-only implementation of this contract. The real
renderer in the generation-pipeline spec must match its output byte for byte, and its
golden tests replace the helper.

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
