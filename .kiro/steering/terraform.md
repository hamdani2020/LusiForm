---
inclusion: fileMatch
fileMatchPattern: ['templates/**', 'infra/**', '**/*.tf', '**/*.tf.j2', '**/*.tftpl']
---

# Terraform conventions

Applies when working in `templates/` (the product's generated output) or
`infra/` (the platform's own infrastructure). See tech.md and security.md for the
rules these build on.

## Versions

- Terraform `>= 1.10` so S3-native state locking is available.
- `backend "s3"` with `use_lockfile = true`. No DynamoDB lock table.
- AWS provider pinned, for example `~> 5.47`. Commit `.terraform.lock.hcl`.

## templates/ (the startup reference architecture)

- Modules only: networking, compute (ECS Fargate), database (RDS PostgreSQL),
  logging and monitoring (CloudWatch), IAM (least privilege).
- Each module has a parameter schema with types, allowed values, and ranges.
  Validate parameters against the schema before rendering.
- Keep to the template scope. No EKS, Aurora, ElastiCache, CloudFront, WAF, third
  AZ, or Graviton in the MVP template.
- Rendering is pure: same intake + same template version → byte-identical output.
  Golden/hash tests compare rendered output to stored fixtures.
- No hardcoded credentials or account IDs in rendered output. A test asserts this
  on every template change.
- A template version is immutable. Changing a module or its schema creates a new
  template version (draft → published → retired).

## Validation gate

Rendered projects must pass, in this order:

1. `terraform fmt -check`
2. `terraform init -backend=false` then `terraform validate`
3. `tflint` with the AWS ruleset
4. `checkov` on the rendered directory

Pin tflint and Checkov in the worker image. A high-severity Checkov finding
blocks export and sandbox deployment, with no bypass.

## Sandbox state and apply

- Plan against the project's own state in S3 with S3 locking.
- The plan hash covers rendered files, variables, the provider lock file, and the
  state serial. Apply only a saved plan whose hash matches an approval, and only
  if the state serial is unchanged. Otherwise re-plan.
- The cross-account role trusts only the worker role, uses a per-partner external
  ID from Secrets Manager, and is limited to the template's resource types.

## infra/ (the platform itself)

- Reviewed like any other code. Two cloud environments, `staging` and `prod`.
  Development is local (Docker Compose with LocalStack), never a cloud environment.
- This is distinct from `templates/`. Platform infra runs Lusiform; templates are
  what Lusiform generates for customers.
