# Implementation Plan: Foundation

Tasks build on each other in order. Each task references the requirements it
satisfies (see `requirements.md`) and follows `design.md`. Run builds and the
relevant single-run tests after each task, and record the real build and test
commands in `.kiro/steering/tech.md` as each package lands (Requirement 1.5).

- [x] 1. Scaffold the monorepo and tooling
  - [x] 1.1 Create the package directories and repo-level files
    - Create `api/`, `worker/`, `web/`, `templates/`, `infra/` with a README in
      each describing its role from `structure.md`.
    - Add a root `.gitignore`, `.editorconfig`, and a root README that points to
      `docs/` and `.kiro/steering/`.
    - `templates/` gets only a README noting that modules land in a later spec.
    - _Requirements: 1.1_
  - [x] 1.2 Set up the Python toolchain for `api/` and `worker/`
    - Python 3.12, `uv` with a pinned lockfile, Ruff (lint and format), mypy,
      pytest. Pin all versions. All tooling runs inside containers (see 1.5 and
      `.kiro/steering/docker.md`); nothing is installed on the host.
    - Create a small internal shared package for config and structured logging
      that both `api/` and `worker/` import. It must not touch the database.
    - _Requirements: 1.2, 1.4, 1.5, NFR 4_
  - [x] 1.3 Set up the `web/` toolchain
    - Vite, React, TypeScript, Tailwind, shadcn/ui, ESLint, Vitest, pnpm with a
      lockfile. Pin versions. Port the design tokens from the Stitch project
      (primary `#0f766e`, Inter, JetBrains Mono, 8px/12px radii) into the Tailwind
      theme. Install and run everything through `docker compose` (no host Node
      or pnpm).
    - _Requirements: 1.3, 1.5_
  - [x] 1.5 Set up the Docker Compose development environment
    - Add `compose.yaml` and `.env.example` at the repo root. Services: `web`,
      `api`, `worker`, `db` (PostgreSQL with a healthcheck and named volume),
      `migrate` (Alembic one-off), and `localstack` (S3, SQS, Secrets Manager).
    - Add a multi-stage `Dockerfile` and `.dockerignore` in `api/`, `worker/`,
      and `web/`, each with a `dev` target used by Compose. Pin base image tags.
    - Bind-mount source for hot reload; keep `.venv` and `node_modules` in named
      volumes. `api` waits on `db` healthy and `migrate` completed.
    - Verify that `docker compose up --build` starts all services, that
      `GET /api/health` returns 200, and that the lint, type-check, and test
      commands in `docker.md` run in containers.
    - Terraform is the only tool allowed on the host.
    - _Requirements: 1.2, 1.3, 1.5_
  - [x] 1.6 Add the CI workflow
    - GitHub Actions with a job per package (lint, type-check, unit test) and a
      separate job slot for the isolation suite and the lint-guard (added in
      tasks 7 and 8). Jobs run the same Dockerfile `dev` targets used locally
      where practical.
    - _Requirements: 1.6_

- [x] 2. Build the API skeleton
  - [x] 2.1 Create the FastAPI app with `/api` routing and a health endpoint
    - App factory, `/api` router, `GET /api/health` returning 200 with no auth.
    - Request-id middleware that generates a `request_id` per request.
    - _Requirements: 1.2, 6.2_
  - [x] 2.2 Add configuration and structured JSON logging
    - Typed settings loaded from environment (no secrets in code or committed env
      files). JSON logger writing to stdout.
    - Add a redaction filter that drops known sensitive keys and never logs
      intake free text, secrets, or credentials.
    - Write unit tests for the redaction filter.
    - _Requirements: 6.2, 6.3, NFR 4_
  - [x] 2.3 Write a smoke test for the health endpoint
    - Assert 200 and that the response needs no auth.
    - _Requirements: 1.2_

- [x] 3. Create the database schema and migrations
  - [x] 3.1 Set up SQLAlchemy models and Alembic
    - SQLAlchemy 2.x declarative models for all 19 tables listed in Requirement
      3.1, using UUID primary keys and `timestamptz` timestamps. Alembic config
      wired to the settings.
    - Models live inside the repository/data package only (needed for the
      lint-guard in task 8).
    - _Requirements: 3.1, 3.2_
  - [x] 3.2 Define core tenant tables and constraints
    - `partners`, `users` (unique on `partner_id` + `email`), `user_roles` with
      role constrained to `partner_admin`, `consultant`, `platform_operator`,
      `projects`, `intake_drafts`. Every tenant table has `partner_id` with a
      foreign key to `partners`.
    - _Requirements: 3.2, 3.3, 3.4_
  - [x] 3.3 Define version, estimate, and job tables
    - `template_versions` (platform-global, no `partner_id`, status draft /
      published / retired), `project_versions`, `assumption_sets`, `estimates`,
      `generation_jobs` (status queued / running / succeeded / failed),
      `artifacts`, `validation_runs`.
    - _Requirements: 3.1, 3.2_
  - [x] 3.4 Define diagram and sandbox deployment tables
    - `architecture_graphs`, `diagram_artifacts`, `sandbox_accounts` (store
      `external_id_ref` as a Secrets Manager reference only), `deployment_plans`,
      `plan_approvals`, `deployments` (action apply or destroy; status queued /
      running / succeeded / failed), and `audit_events`.
    - _Requirements: 3.1, 3.8_
  - [x] 3.5 Add immutability and append-only triggers
    - `BEFORE UPDATE OR DELETE` triggers that raise an exception on
      `project_versions`, `template_versions`, `estimates`,
      `architecture_graphs`, and the append-only tables `audit_events`,
      `plan_approvals`, `artifacts`, `validation_runs`. `deployment_plans` blocks
      UPDATE/DELETE of identity and hash fields once created.
    - _Requirements: 3.6, 3.7_
  - [x] 3.6 Generate the initial Alembic migration and test the round trip
    - One initial migration creating schema, enums, constraints, and triggers.
    - Write a migration test: `upgrade head` then `downgrade base` on a
      disposable Postgres (testcontainers), asserting a clean state both ways.
    - Document running migrations as a one-off task.
    - _Requirements: 3.5_
  - [x] 3.7 Write schema constraint tests
    - Assert email uniqueness per partner, the role constraint, that the
      immutability and append-only triggers reject UPDATE and DELETE, and that no
      column holds a secret value.
    - _Requirements: 3.3, 3.4, 3.6, 3.7, 3.8_

- [ ] 4. Implement the repository layer
  - [ ] 4.1 Create the `RequestContext` type and repository base
    - Frozen `RequestContext` (user id, partner id, roles, request id).
    - A `Repository` base that takes a context and a private session and adds
      `WHERE partner_id = ctx.partner_id` to every query on tenant tables. There
      is no code path to pass a different `partner_id`.
    - A separate non-tenant base (no partner filter) for `template_versions`,
      used only by operator routes.
    - Session factory is private to the data package; handlers never receive a
      raw session.
    - _Requirements: 4.1, 4.2_
  - [ ] 4.2 Implement a uniform `NotFound` behavior
    - Not-found and cross-partner lookups raise the same `NotFound`, which the API
      maps to 404 without disclosing existence.
    - _Requirements: 4.3_
  - [ ] 4.3 Implement repositories for the foundation entities
    - `partners` (operator only), `users`, `user_roles`, `projects`,
      `intake_drafts`, and `audit_events` (insert only).
    - Immutable and append-only repositories expose `add` and read methods only;
      no update or delete.
    - Other tables get repositories in the specs that use them; the base and
      guards are in place now.
    - _Requirements: 3.6, 3.7, 4.1_
  - [ ] 4.4 Write unit tests for the repository layer
    - Partner scoping on every read and write, `NotFound` on cross-partner
      access, and that immutable repositories offer no mutation methods.
    - _Requirements: 4.1, 4.2, 4.3, 3.6, 3.7_

- [ ] 5. Implement authentication and request context
  - [ ] 5.1 Implement JWT verification against Cognito
    - Validate signature using the Cognito JWKS (cached, refreshed on key
      rotation), and check `iss`, audience/client id, and `exp`.
    - Return 401 for missing, expired, or invalid tokens.
    - _Requirements: 2.2, 2.4_
  - [ ] 5.2 Implement the `get_request_context` dependency
    - From the verified `sub`, load the `users` row and `user_roles` and build the
      `RequestContext`. Roles come from the database, never from client claims.
    - Return 403 when the user has no active record, or the partner is suspended,
      or the user is deactivated.
    - Apply the dependency to every router except `/api/health` and the auth
      callback.
    - _Requirements: 2.2, 2.3, 2.5, 5.3_
  - [ ] 5.3 Implement `require_roles` and the admin/operator routers
    - `require_roles(*roles)` dependency factory. Admin routers require
      `partner_admin` or `platform_operator`; operator-only routers require
      `platform_operator`. Return 403 otherwise.
    - Add a minimal `GET /api/me` returning the caller's id, partner, and roles
      to prove the chain end to end.
    - _Requirements: 5.1, 5.2, 5.3_
  - [ ] 5.4 Write auth unit and integration tests
    - JWT cases: valid, expired, bad signature, wrong issuer, wrong audience.
    - Context resolution, role gating, and 403 for inactive or suspended users.
    - Verify that a client-supplied role value has no effect.
    - _Requirements: 2.2, 2.3, 2.5, 5.1, 5.2, 5.3_

- [ ] 6. Implement audit and cross-partner access recording
  - [ ] 6.1 Build the audit helper
    - Append an `audit_events` row in the same transaction as the write it
      records, with actor, partner, action, target type and id, and before/after
      JSON.
    - _Requirements: 6.1_
  - [ ] 6.2 Add the operator cross-partner router and its audit
    - A separate router prefix for platform operator cross-partner reads that
      always writes an `audit_events` row for the access.
    - Start with `GET /api/admin/partners` as the first operator route.
    - _Requirements: 4.4, 5.2, 6.1_
  - [ ] 6.3 Write audit tests
    - Assert admin writes append audit rows atomically with the write, that
      operator cross-partner access is audited, and that audit rows cannot be
      updated or deleted.
    - _Requirements: 6.1, 4.4, 3.7_

- [ ] 7. Build the tenant isolation test suite
  - [ ] 7.1 Create the two-partner fixtures
    - Testcontainers Postgres, migrated to head. Seed partners A and B, each with
      users in each role and rows across the tenant tables that exist so far.
    - _Requirements: 4.6_
  - [ ] 7.2 Write the table-driven isolation tests
    - Enumerate tenant-scoped endpoints; for each, assert B requesting A's
      resource gets 404 and that a write by B never touches A's rows. New
      endpoints must be added to the table to be covered.
    - Add a test that fails if a registered tenant-scoped route is missing from the
      table, so coverage cannot silently lapse.
    - _Requirements: 4.3, 4.6, NFR 3_
  - [ ] 7.3 Wire the suite into CI as its own job
    - The job must pass for the pipeline to pass.
    - _Requirements: 4.6, 1.6_

- [ ] 8. Add the tenant-access lint guard
  - [ ] 8.1 Implement the guard
    - An AST-based check, run in CI, that fails the build when SQLAlchemy session
      execution or ORM model imports appear outside the repository package.
      Allowlist the repository package and migrations.
    - _Requirements: 4.5_
  - [ ] 8.2 Prove the guard works
    - Add a test fixture containing a deliberate violation and assert the guard
      flags it; assert the real codebase is clean.
    - Wire the guard into CI.
    - _Requirements: 4.5, 1.6_

- [ ] 9. Build the web authentication shell
  - [ ] 9.1 Implement the Cognito hosted-login flow in `web/`
    - Redirect unauthenticated users to the hosted login, handle the callback
      code exchange, keep tokens in memory with refresh through the Cognito flow,
      and store no long-lived secret in the browser.
    - Attach `Authorization: Bearer` to API calls.
    - _Requirements: 2.1, 2.4, 2.6_
  - [ ] 9.2 Build the authenticated app shell
    - Layout with the "Lusiform" brand, the Projects navigation, and the signed-in
      user's name and role, matching the Sign In and Projects shell designs in the
      Stitch project. There is no workspace picker: a user belongs to one partner
      (see the `agent-and-admin` spec).
    - Show the user from `GET /api/me`. Hide admin navigation unless the user has
      an admin role.
    - _Requirements: 1.3, 2.3_
  - [ ] 9.3 Write web tests
    - An unauthenticated visit redirects to the hosted login; an authenticated
      state renders the shell with the user's name and role; admin navigation is
      hidden for consultants.
    - _Requirements: 2.6, 5.1_

- [ ] 10. Build the worker skeleton
  - [ ] 10.1 Create the queue-polling loop
    - Read config from the shared package, poll SQS, and log structured output.
      No job handlers yet; unknown job types are logged and left for later specs.
    - Document the task role boundary: artifact bucket and job queue only, no
      tenant database access.
    - _Requirements: 1.4, 6.2_
  - [ ] 10.2 Write worker tests
    - Starts, reads config, polls a stubbed queue, and shuts down cleanly. Assert
      the worker package has no dependency on the API's data package.
    - _Requirements: 1.4_

- [ ] 11. Define platform infrastructure stubs
  - [ ] 11.1 Write Terraform for the foundation resources in `infra/`
    - Cognito user pool and app client (hosted login, email and password, no
      federation), RDS PostgreSQL with KMS encryption and backups, S3 artifact
      bucket with KMS, SQS job queue, and ECS service definitions for the API and
      worker with separate task roles.
    - Use Terraform `>= 1.10`, pinned providers, and the S3 backend with
      `use_lockfile = true` (no DynamoDB). Separate `dev`, `pilot`, and `prod`
      environments.
    - Run `terraform fmt` and `terraform validate`. Do not apply.
    - _Requirements: NFR 1, NFR 2_
  - [ ] 11.2 Add the operator bootstrap task
    - A documented, separate task that creates the first `platform_operator`, so
      migrations stay data-free.
    - _Requirements: 5.2_

- [ ] 12. Final verification
  - [ ] 12.1 Run the full suite and the guards
    - Run lint, type checks, unit tests, migration round trip, the isolation
      suite, and the lint-guard across all packages. All must pass.
    - _Requirements: 1.6, 4.5, 4.6, NFR 3_
  - [ ] 12.2 Update steering with real commands
    - Replace the placeholder in `.kiro/steering/tech.md` with the exact build,
      test, lint, and migration commands that now exist.
    - _Requirements: 1.5_
  - [ ] 12.3 Confirm the acceptance criteria
    - Walk requirements 1–6 and the non-functional requirements and note which
      test or artifact proves each. Flag anything not covered.
    - _Requirements: all_
