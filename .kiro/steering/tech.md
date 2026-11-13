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

- Networking: a single region, one VPC, public and isolated data subnets in two AZs
  (the workload runs in one by default; two is a parameter). No NAT gateway: Fargate
  tasks run in the public subnets with public IPs, protected by security groups.
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

Docker is the main development environment. Every app runs through Docker
Compose, and every command runs inside a container, except Terraform, which runs on
the host. See `docker.md` for the service layout. Use single-run test modes, never
watch mode. Verify builds and run the relevant checks after every change.

Run the stack:

```
docker compose up --build                      # web :5173, api :8000, db, localstack, worker
docker compose down                            # stop (keeps volumes)
```

`common/` (shared config and logging; its tools come from the api image):

```
docker compose run --rm --no-deps -w /app/common api ruff check .
docker compose run --rm --no-deps -w /app/common api ruff format --check .
docker compose run --rm --no-deps -w /app/common api mypy .
docker compose run --rm --no-deps -w /app/common api pytest -q
```

`api/` (pytest needs the compose `db`: migration, schema, and isolation tests create
throwaway databases on it):

```
docker compose run --rm --no-deps api uv run ruff check .
docker compose run --rm --no-deps api uv run ruff format --check .
docker compose run --rm --no-deps api uv run mypy .
docker compose run --rm api uv run pytest                        # everything
docker compose run --rm api uv run pytest tests/isolation        # tenant isolation suite
docker compose run --rm api uv run pytest tests/test_migrations.py  # upgrade/downgrade round trip
docker compose run --rm --no-deps api python -m tools.check_tenant_access app  # tenant-access guard
```

`worker/`:

```
docker compose run --rm --no-deps worker uv run ruff check .
docker compose run --rm --no-deps worker uv run ruff format --check .
docker compose run --rm --no-deps worker uv run mypy .
docker compose run --rm --no-deps worker uv run pytest
```

`web/`:

```
docker compose run --rm --no-deps web pnpm lint
docker compose run --rm --no-deps web pnpm typecheck
docker compose run --rm --no-deps web pnpm test --run
docker compose run --rm --no-deps web pnpm build
```

Database (Alembic; migrations stay data-free):

```
docker compose run --rm migrate                                  # alembic upgrade head
docker compose run --rm migrate alembic current
docker compose run --rm migrate alembic revision --autogenerate -m "message"
docker compose run --rm api python -m app.bootstrap_operator \
  --partner-name Lusiform --email you@example.com --cognito-sub SUB   # first platform operator
```

`templates/` (the startup template; the suite runs in the `worker` container, which carries the
pinned Terraform, tflint, and Checkov, and never plans or applies):

```
templates/scripts/run-tests.sh -q                                # whole suite: schema, modules, validators, determinism, publication
templates/scripts/run-tests.sh -k pins                           # pytest arguments pass through
templates/scripts/run-tests.sh tests/test_modules_static.py      # fast, no Terraform
docker compose run --rm --no-deps -w /app/templates worker uv run --frozen --project /app/worker ruff check --config /app/worker/pyproject.toml .
docker compose run --rm --no-deps -w /app/templates worker uv run --frozen --project /app/worker mypy --config-file /app/worker/pyproject.toml template_tools tests scripts
terraform fmt -check -recursive templates                        # on the host
# inside the worker container (prefix: docker compose run --rm --no-deps -w /app/templates worker uv run --frozen --project /app/worker):
python -m template_tools.sandbox_policy startup/1.0.0 [--check]  # write or verify sandbox-policy.json
python tests/update_golden.py startup/1.0.0                      # regenerate golden files after an intended change; review the diff
python -m template_tools.publication check startup/1.0.0         # review gate and manifest
python -m template_tools.publication manifest startup/1.0.0      # write manifest.json (published versions only)
python -m template_tools.publication row startup/1.0.0           # template_versions row values (writes nothing)
```

`infra/` (Terraform on the host; two cloud environments, `staging` and `prod`):

```
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra/envs/staging init -backend=false && terraform -chdir=infra/envs/staging validate
cd infra/modules/<module> && terraform init -backend=false && terraform test   # mocked AWS
terraform -chdir=infra/envs/staging plan -out=plan.tfplan        # real AWS; review, then apply the saved plan
```

Dependencies:

```
docker compose run --rm api uv add <pkg>==<version>              # worker: same, with worker
docker compose run --rm web pnpm add -E <pkg>@<version>
docker compose build <service>                                   # after any dependency change
```

CI (`.github/workflows/ci.yml`) runs the same commands: one job per package, plus the
tenant isolation suite, the tenant-access guard, and `infra` (fmt, validate, module
tests; never plan or apply).

## Dependencies

Pin versions. Prefer well-known, actively maintained packages. Flag anything that
looks like a typosquat before adding it.
