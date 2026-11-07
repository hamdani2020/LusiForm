# Tech stack and conventions

## Stack

- **Web:** React with Vite, TypeScript, shadcn/ui, Tailwind CSS.
- **API:** FastAPI (Python) on ECS Fargate. Handles auth, projects, intake,
  estimates, admin, approvals, and streaming agent responses.
- **Worker:** Python on ECS Fargate, pulling jobs from SQS. Renders Terraform and
  draw.io, runs validators, runs sandbox plan/apply/destroy, packages zips.
- **Agent:** Strands Agents (Python) on Amazon Nova models through Bedrock,
  running inside the API service. Nova Pro by default, Nova Lite for lower-cost
  calls. The agent is never "Claude" or any other model in UI or copy.
- **Data:** PostgreSQL (RDS). S3 for artifacts and zips. SQS for jobs. Cognito
  for auth. Secrets Manager for secrets. Bedrock for the agent. AWS Pricing API
  for cost.
- **Migrations:** Alembic, run as a one-off task before the service rolls.

## The startup reference architecture (the template)

One fixed template, stored as Terraform modules in `templates/`:

- Networking: a single region, one VPC, two AZs where a parameter requires it.
- Compute: ECS Fargate (serverless or small container footprint). Not EKS.
- Database: managed PostgreSQL on RDS. Not Aurora, unless a future template
  version adds it deliberately.
- Logging and basic monitoring: CloudWatch.
- IAM: least-privilege roles.

Do not introduce EKS, Aurora, ElastiCache, CloudFront, WAF, a third AZ, or
Graviton into the MVP template. Those were enterprise artifacts in the original
mockups and are out of scope.

## Terraform

- Pin a single Terraform version. Target **Terraform 1.10 or later**, which is
  required for native S3 state locking.
- **S3 state locking only.** Use the S3 backend with `use_lockfile = true`. Do
  not use a DynamoDB lock table; recent Terraform does S3-native locking.
- Pin the AWS provider (for example `~> 5.47`) and commit the provider lock file.
- Pin tflint and Checkov versions in the worker image so results are stable.
- Generated Terraform is deterministic: the same intake and template version
  produce byte-identical output. This is covered by golden/hash regression tests.
- Drop "OpenTofu compatible" claims unless we deliberately decide to support it.

## Determinism and single source

- Rendering first produces an **architecture graph**. That graph is the single
  source for both the Terraform modules and the draw.io diagram.
- Consultants never edit the graph directly. Changes come from the parameter form
  or the agent, which update the graph and re-render.
- The draw.io renderer uses one fixed layout algorithm, so the same graph always
  produces the same file.

## Pricing

- Costs come from the **AWS Pricing API** for the selected region. Never show a
  figure the model invented; UI numbers come from the estimate service.
- Cache prices per region and service code with a TTL. Store a price snapshot
  timestamp and the assumptions with each estimate.
- Changing an assumption creates a new estimate for the same version. It does not
  change that version's Terraform output.

## Commands

The repo is being built out. As each package gains a build, prefer its standard
tooling and record the exact commands here once they exist:

- `web/`: Vite + npm or pnpm scripts (dev, build, lint, test).
- `api/` and `worker/`: Python with a pinned toolchain; tests via pytest.
- Verify builds and run relevant tests after changes. Use single-run test modes,
  not watch mode.

## Dependencies

Pin versions. Prefer well-known, actively maintained packages. Flag anything that
looks like a typosquat before adding it.
