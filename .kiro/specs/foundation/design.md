# Design: Foundation

## Overview

This design turns the foundation requirements into a concrete build: the monorepo
skeletons, Cognito authentication with a request-context dependency, the full
PostgreSQL schema via Alembic, and a repository layer that makes per-partner
isolation the only way to touch tenant data. It intentionally stops short of any
consultant feature and the Terraform template.

It realizes requirements 1–6 and the non-functional requirements in
`requirements.md`, and follows `structure.md`, `tech.md`, and `security.md`.

## Architecture

```
                         Cognito (hosted login, user pool)
                                     │ JWT (RS256, JWKS)
                                     ▼
  web/ (React, Vite) ──auth redirect──> API /api/* ──► RequestContext dependency
                                                 │         (verify JWT, resolve
                                                 │          partner_id + roles)
                                                 ▼
                                        Repository layer  ──► PostgreSQL (RDS)
                                        (applies partner_id)
                                                 │
                                                 ▼
                                        audit_events (append-only)

  worker/ ──polls──► SQS (skeleton only; no handlers in this spec)
```

Only the API talks to the tenant database, and only through the repository layer.
The worker in this spec is a runnable loop with no job handlers.

## Monorepo layout and tooling

```
api/        FastAPI app, Alembic migrations, repository layer, auth, tests
worker/     Queue-polling skeleton, shared config, tests
web/        Vite + React + TS + shadcn/ui + Tailwind, auth shell
templates/  Placeholder with a README; modules land in a later spec
infra/      Terraform for platform (Cognito, RDS, S3, SQS, ECS); stubs here
docs/       PRD and Technical Design
```

### Decisions

- **API language/runtime:** Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic,
  Pydantic v2. Dependency and tooling via `uv` with a pinned lockfile. Lint and
  format with Ruff; type-check with mypy; test with pytest.
- **Web:** Vite + React + TypeScript, shadcn/ui, Tailwind. Package manager pnpm.
  Lint with ESLint, test with Vitest.
- **Worker:** same Python toolchain as the API, sharing a small internal package
  for config and logging. No shared database access (see security.md).
- **Local development:** Docker Compose is the development environment. All
  apps, tests, and package installs run in containers; only Terraform runs on the
  host. See `.kiro/steering/docker.md`.
- **CI:** GitHub Actions, one workflow with a job per package (lint, type-check,
  test), plus the isolation suite as a dedicated job. This is the decision left
  open in requirements; GitHub Actions is the default unless you prefer another.
- **Health endpoint:** `GET /api/health` returns 200 with no auth, for load
  balancer checks and the scaffolding acceptance test.

The exact build and test commands are recorded in `tech.md` as each package lands
(Requirement 1.5).

## Authentication and request context

### Flow

1. The web app redirects an unauthenticated user to the Cognito hosted login.
2. Cognito returns to the web app's callback with an authorization code; the app
   exchanges it for access and refresh tokens (short-lived access token).
3. The web app sends the access token as `Authorization: Bearer <jwt>` on every
   `/api` call. It stores no long-lived secret; tokens are held in memory with
   refresh handled through the Cognito flow.
4. The API verifies the JWT on every protected route.

### JWT verification

- A FastAPI dependency `get_request_context` runs on every router except
  `/api/health` and the auth callback.
- It validates the token signature against Cognito's JWKS (cached, refreshed on
  key rotation), checks `iss`, `aud`/`client_id`, and `exp`.
- On missing, expired, or invalid token → 401.

### Resolving partner and roles

- From the verified token's subject (`sub`), the dependency loads the `users` row
  and its `user_roles`, producing a `RequestContext`:

```python
@dataclass(frozen=True)
class RequestContext:
    user_id: UUID
    partner_id: UUID
    roles: frozenset[Role]   # subset of {partner_admin, consultant, platform_operator}
    request_id: str
```

- Roles come from the database, never from a client-supplied claim (Requirement
  5.3).
- If the user has no active record for the resolved partner → 403 (Requirement
  2.5). A suspended partner or deactivated user also yields 403.
- `RequestContext` is the single object handlers and the repository layer read
  `partner_id` from. Handlers never accept `partner_id` as input.

### Authorization dependencies

- `require_roles(*roles)` is a dependency factory. Admin routers depend on
  `require_roles(partner_admin, platform_operator)`; operator-only routers depend
  on `require_roles(platform_operator)`. Others require only a valid context.
- Cross-partner operator routes live under a separate router prefix and always
  write an `audit_events` row for the access (Requirement 4.4).

## Data model

All tables use `UUID` primary keys (`gen_random_uuid()` via `pgcrypto`, or
application-generated UUIDv4). Timestamps are `timestamptz`. Tenant-scoped tables
carry `partner_id uuid not null references partners(id)`.

### Tables and their isolation class

| Table | partner_id | Mutability |
| --- | --- | --- |
| `partners` | tenant root | mutable (status) |
| `users` | yes | mutable; `unique(partner_id, email)` |
| `user_roles` | via user | mutable; role in enum |
| `projects` | yes | mutable metadata |
| `project_versions` | yes | **immutable** |
| `intake_drafts` | yes | mutable |
| `template_versions` | no (platform-global) | **immutable**; status draft/published/retired |
| `assumption_sets` | yes | mutable |
| `estimates` | yes | **immutable** |
| `generation_jobs` | yes | status transitions only |
| `artifacts` | yes | **append-only** |
| `validation_runs` | yes | **append-only** |
| `audit_events` | yes | **append-only** |
| `sandbox_accounts` | yes | mutable (trust status) |
| `architecture_graphs` | yes | **immutable** |
| `diagram_artifacts` | yes | status fields mutable |
| `deployment_plans` | yes | **immutable once created** |
| `plan_approvals` | via plan | **append-only** |
| `deployments` | via plan | status transitions only |

Notes:

- `template_versions` is platform-global (authored by platform operators, stored
  as files), so it carries no `partner_id`. Everything else tenant-owned does.
- Role is a Postgres enum or a check constraint limited to `partner_admin`,
  `consultant`, `platform_operator` (Requirement 3.4).
- `sandbox_accounts.external_id_ref` stores a Secrets Manager reference, never
  the external ID value (Requirement 3.8).

### Immutability and append-only enforcement

Two layers:

1. **Data layer:** repositories for immutable and append-only tables expose only
   `add` and read methods; no `update`/`delete`. This is the primary guard
   (Requirements 3.6, 3.7).
2. **Database:** a `BEFORE UPDATE OR DELETE` trigger on append-only tables
   (`audit_events`, `plan_approvals`, `artifacts`, `validation_runs`) raises an
   exception, so even a stray query cannot mutate history. Immutable version
   tables get the same trigger on UPDATE/DELETE.

### Migrations

- Alembic, one initial migration creating the whole schema, enums, constraints,
  and triggers. Run as a one-off ECS task before the service rolls.
- A migration test applies `upgrade head` then `downgrade base` on a disposable
  database and asserts a clean round trip (Requirement 3.5).

## Repository layer and tenant isolation

### Shape

- A `Repository` base takes the `RequestContext` and a session. Every query it
  builds against a tenant-scoped table adds `WHERE partner_id = :ctx.partner_id`.
  There is no code path to pass a different `partner_id`.
- Tenant-scoped repositories subclass it. Non-tenant tables (`template_versions`)
  use a separate base without partner filtering, reachable only from operator
  routes.
- A not-found lookup and a cross-partner lookup are indistinguishable: both raise
  the same `NotFound`, which handlers turn into 404 (Requirement 4.3). This is
  the 404-not-403 decision from the requirements review.

### Enforcement that nothing bypasses the layer

- Handlers and services receive repositories, never a raw session. The session
  factory is private to the data package.
- A custom lint check (a Ruff plugin or a small AST test run in CI) fails the
  build if `sqlalchemy` session execution, or imports of the ORM models, appear
  outside the repository package (Requirement 4.5). The check has an allowlist
  for the repository package and migrations.

### Isolation test suite

- A pytest suite runs against the compose `db` Postgres locally (a CI service in
  CI; avoid Docker-in-Docker testcontainers), seeds two
  partners A and B each with a user and a few rows across tenant tables.
- For every tenant-scoped endpoint, it issues B's request for A's resource and
  asserts 404, and asserts no write by B touches A's rows. A table-driven test
  enumerates endpoints so new ones are covered as they are added.
- Runs as its own CI job and must pass (Requirements 4.6, NFR 3).

## Audit and observability

- An `audit` helper appends an `audit_events` row inside the same transaction as
  the write it records, capturing actor, partner, action, target type/id, and
  before/after JSON. Admin writes and (later) generation/deployment actions call
  it (Requirement 6.1).
- Logging is structured JSON (one logger config shared by API and worker) to
  stdout for CloudWatch, carrying request id, partner id, user id, and project id
  from the context. A redaction filter drops known sensitive keys and never logs
  intake free text, secrets, or credentials (Requirements 6.2, 6.3).
- `request_id` is generated per request and added to the context and every log
  line.

## Security notes specific to this spec

- JWT verification is mandatory on all protected routes; only `/api/health` and
  the auth callback are open (NFR 2).
- Data at rest is KMS-encrypted (RDS, S3) and in transit is TLS; these are set in
  `infra/` and asserted by configuration, not application code.
- No secret value is stored in the database or logs; references point to Secrets
  Manager.
- The worker gets a task role scoped to the artifact bucket and job queue only,
  with no tenant DB access. In this spec the worker has no handlers, but its role
  and config are defined so later specs inherit the boundary.

## Testing strategy

- **Unit:** JWT verification (valid, expired, bad signature, wrong audience),
  role resolution, `require_roles`, repository partner-scoping, immutability and
  append-only guards.
- **Migration:** upgrade/downgrade round trip on a disposable database.
- **Isolation:** the two-partner suite above, table-driven across endpoints.
- **Lint-guard:** a CI check proving tenant data access outside the repository
  layer fails the build.
- **Web:** a smoke test that an unauthenticated visit redirects to hosted login
  and an authenticated shell renders.

## Open questions

1. CI system: GitHub Actions is assumed. Confirm, or name an alternative.
2. Postgres in CI: testcontainers vs a CI service container. Default:
   testcontainers for parity with local runs.
3. Whether to seed a first `platform_operator` via migration or a separate
   bootstrap task. Default: a separate, documented bootstrap task so the
   migration stays data-free.
