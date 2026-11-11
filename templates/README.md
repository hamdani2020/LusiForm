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
      root/                   templates for the rendered root project (*.tmpl)
      fixtures/               params/, golden/, insecure/ used by tests
  scripts/                    test runner
  tests/                      template test suite
```

`schema.json`, `inventory.json`, `sandbox-policy.json`, and the module contents are
added by later tasks of the `startup-template` spec. `1.0.0` is a draft until then.

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

## Running the tests

Tests run in the `worker` container, which carries the pinned Terraform, tflint, and
Checkov. Nothing but Docker is needed on the host.

```
templates/scripts/run-tests.sh            # whole suite
templates/scripts/run-tests.sh -k pins    # pass pytest arguments through
```
