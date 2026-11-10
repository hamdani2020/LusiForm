# Docker development environment

Docker is the main development environment for Lusiform. All apps run with
Docker Compose. Do not install or run Node, Python, uv, pnpm, tflint, or Checkov
on the host. Run them in containers.

MCP servers are outside this rule. Kiro connects to them from the host using
`.kiro/settings/mcp.json` (for example Stitch over HTTP). Never run, proxy, or
reach an MCP server through Docker or a container, and never add MCP servers to
`compose.yaml`. Use the MCP tools directly.

Terraform is the exception. Run `terraform` directly on the host (for `infra/`
and `templates/` work). Use the version pinned in tech.md and terraform.md
(1.10 or later). The worker image still bundles the pinned Terraform, tflint,
and Checkov for validation and sandbox jobs.

## Rules

- Start the stack with `docker compose up`. Long-running services (`docker compose
  up`, `logs -f`) are started with the background process tool, never the
  blocking shell tool.
- Run one-off commands with `docker compose run --rm <service> <cmd>` or
  `docker compose exec <service> <cmd>` when the service is already up.
- Never run `npm`, `pnpm`, `pytest`, `uv`, `pip`, `uvicorn`, `vite`, `alembic`,
  `tflint`, or `checkov` directly on the host. `terraform` is allowed on the host.
- Use single-run test modes, not watch mode.
- Pin base image tags (for example `python:3.12-slim`, `node:22-alpine`,
  `postgres:16`). No `latest`.
- Dev images use the same pinned Terraform, tflint, and Checkov versions as the
  worker image (see tech.md and terraform.md).
- No secrets in Dockerfiles, compose files, or committed `.env` files. Commit
  `.env.example` only. Real values stay in a git-ignored `.env`.
- Mount source code as bind mounts for hot reload. Keep dependencies
  (`node_modules`, `.venv`) in named volumes so host and container do not mix.

## Packages, tests, and tooling

Everything for the application happens in containers: installing packages,
running tests, linting, type-checking, migrations, and code generation.

- Add a Python package: `docker compose run --rm api uv add <pkg>` (use
  `worker` for worker-only packages). This updates `pyproject.toml` and
  `uv.lock` on the host through the bind mount. Commit both.
- Add a web package: `docker compose run --rm web pnpm add <pkg>`. Commit
  `package.json` and `pnpm-lock.yaml`.
- After a dependency change, rebuild: `docker compose build <service>`.
- Never run `pip install`, `npm install`, or `pnpm install` on the host, and
  never commit `node_modules` or `.venv`.
- Pin exact versions when adding packages (see tech.md).
- Tests run in containers against the compose `db`. The tenant isolation suite
  uses that Postgres, not a host install.
- Run shells in a container when you need one:
  `docker compose run --rm api bash`.

## Services (compose.yaml at the repo root)

| Service | Role | Notes |
| --- | --- | --- |
| `web` | Vite dev server | Hot reload, port 5173 |
| `api` | FastAPI with reload | Port 8000, routes under `/api` |
| `worker` | SQS job consumer | Same toolchain as `api`, includes Terraform, tflint, Checkov |
| `db` | PostgreSQL | Named volume for data, healthcheck required |
| `migrate` | Alembic one-off | Runs `alembic upgrade head`; `api` waits on it |
| `localstack` | Local S3, SQS, Secrets Manager | Dev only. Cognito and Bedrock are not emulated |

`api` and `worker` depend on `db` being healthy. `api` depends on `migrate`
completing successfully. Local dev must never use real sandbox credentials.

## Commands

```
docker compose up --build            # start everything
docker compose down                  # stop (keeps volumes)
docker compose run --rm migrate      # apply migrations
docker compose run --rm api uv run pytest
docker compose run --rm api uv run ruff check .
docker compose run --rm api uv run mypy .
docker compose run --rm worker uv run pytest
docker compose run --rm worker uv run ruff check .
docker compose run --rm worker uv run mypy .
docker compose run --rm --no-deps api python -m tools.check_tenant_access app  # tenant-access guard
docker compose run --rm web pnpm lint
docker compose run --rm web pnpm typecheck
docker compose run --rm web pnpm test --run
docker compose run --rm web pnpm build
docker compose run --rm api uv add <pkg>
docker compose run --rm web pnpm add <pkg>
```

Add `--no-deps` to a `run` command to skip starting `db`/`localstack` when the
command does not need them (lint, type-check, unit tests).

If image builds fail with DNS errors (`failed to lookup address`, `EAI_AGAIN`),
set `BUILD_DNS` (for example `BUILD_DNS=1.1.1.1 docker compose up --build`, or
in the git-ignored `.env`). It only overrides the resolver for `RUN` steps.

The `api_venv`, `worker_venv`, and `web_node_modules` named volumes are seeded
from the image the first time they are created. After a dependency change and
rebuild, `uv run` and the web startup install re-sync them; if a volume is
stuck stale, remove it (`docker volume rm lusiform_<name>`) and start again.

Keep this list in sync with the `foundation` spec tasks as services land.

## Where files go

- `compose.yaml` and `.env.example` at the repo root.
- One `Dockerfile` per app: `api/Dockerfile`, `worker/Dockerfile`,
  `web/Dockerfile`. Use multi-stage builds with a `dev` target for Compose and a
  production target for ECS.
- Add a `.dockerignore` to each app directory.
- Docker here is for local development. Platform infrastructure still deploys to
  ECS Fargate from `infra/`.
