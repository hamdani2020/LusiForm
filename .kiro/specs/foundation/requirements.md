# Requirements: Foundation

## Introduction

The foundation spec establishes the base that every later Lusiform feature builds
on: the monorepo scaffolding, authentication through Amazon Cognito, the
PostgreSQL data model with Alembic migrations, and the repository layer that
enforces per-partner tenant isolation. It maps to the Weeks 1–2 milestone in the
Technical Design, minus the startup template (which gets its own spec and an
AWS-experienced review).

This spec delivers no consultant-facing feature screens. It delivers a running
API skeleton, a web app shell that can authenticate, a complete schema, and a
tested isolation guarantee, so the intake, generation, diagram, and deployment
specs have somewhere to land.

Source of truth: the PRD and Technical Design in `docs/`, and the steering files
in `.kiro/steering/`.

## Glossary

- **Partner**: an AWS Partner consultancy; the tenant boundary. Every
  tenant-scoped row carries `partner_id`.
- **Repository layer**: the only code path allowed to read or write tenant data;
  it applies `partner_id` from the authenticated user's context.
- **Immutable version**: a `project_versions` or `template_versions` row that is
  never updated after creation; edits create new rows.

## Requirements

### Requirement 1: Monorepo scaffolding

**User Story:** As an engineer, I want the monorepo laid out with runnable
skeletons for each service, so that later specs add code in a consistent place
with working build and test commands.

#### Acceptance Criteria

1. THE repository SHALL contain the directories `api/`, `worker/`, `web/`,
   `templates/`, and `infra/` as described in `structure.md`.
2. WHEN an engineer runs the documented build command in `api/` THEN the FastAPI
   service SHALL start and serve a health endpoint under `/api`.
3. WHEN an engineer runs the documented build command in `web/` THEN the Vite
   app SHALL build and serve the authenticated shell.
4. THE `worker/` package SHALL provide a runnable skeleton that can start, read
   its configuration, and poll its job queue, with no job handlers required yet.
5. WHERE a package has tests, THE repository SHALL provide a single-run test
   command for it, and those commands SHALL be recorded in `tech.md`.
6. THE CI configuration SHALL run lint, type checks, and unit tests for each
   package that defines them.

### Requirement 2: Authentication with Cognito

**User Story:** As a consultant, I want to sign in through the hosted login with
my invited email, so that I reach my partner's workspace securely without SSO.

#### Acceptance Criteria

1. THE system SHALL authenticate users through a Cognito user pool with the
   hosted login, using email and password, with no federated SSO.
2. WHEN a request arrives at any `/api` route other than health and the public
   auth callback THEN the API SHALL verify the request's JWT and reject it with
   401 if the token is missing, expired, or invalid.
3. WHEN a valid JWT is presented THEN a FastAPI dependency SHALL resolve the
   user's identity, their `partner_id`, and their roles from the token and
   database, and make that context available to handlers.
4. THE system SHALL issue short-lived access tokens with refresh tokens, and
   SHALL NOT use long-lived API keys.
5. IF a user has no active record for the resolved partner THEN the API SHALL
   reject the request with 403.
6. THE web app SHALL redirect an unauthenticated user to the hosted login and
   SHALL store no long-lived secret in the browser.

### Requirement 3: Data model and migrations

**User Story:** As an engineer, I want the full schema created through
migrations, so that every later feature has its tables, keys, and immutability
guarantees in place.

#### Acceptance Criteria

1. THE schema SHALL define all tables from the Technical Design data model:
   `partners`, `users`, `user_roles`, `projects`, `project_versions`,
   `intake_drafts`, `template_versions`, `assumption_sets`, `estimates`,
   `generation_jobs`, `artifacts`, `validation_runs`, `audit_events`,
   `sandbox_accounts`, `architecture_graphs`, `diagram_artifacts`,
   `deployment_plans`, `plan_approvals`, and `deployments`.
2. THE schema SHALL use UUID primary keys, and every tenant-scoped table SHALL
   carry a `partner_id` column with a foreign key to `partners`.
3. THE `users` table SHALL enforce that email is unique per partner.
4. THE `user_roles` table SHALL constrain role to exactly `partner_admin`,
   `consultant`, or `platform_operator`.
5. WHEN a migration runs forward and then back THEN it SHALL leave the database
   in a consistent state, and migrations SHALL run as a one-off task via Alembic.
6. THE `project_versions` and `template_versions` tables SHALL be treated as
   immutable after creation; the data layer SHALL offer no update path for them,
   and edits SHALL create new rows.
7. THE `audit_events`, `plan_approvals`, and other append-only tables SHALL be
   written only by insert; the data layer SHALL offer no update or delete path
   for them.
8. THE schema SHALL store no secret values; references such as
   `external_id_ref` SHALL point to Secrets Manager, not hold the secret.

### Requirement 4: Repository layer and tenant isolation

**User Story:** As a platform owner, I want every data access to be scoped to the
caller's partner through one layer, so that a bug or a crafted request cannot
read or write another partner's data.

#### Acceptance Criteria

1. THE system SHALL provide a repository layer that is the only sanctioned path
   for reading or writing tenant-scoped tables.
2. WHEN the repository layer executes any query against a tenant-scoped table
   THEN it SHALL apply the `partner_id` from the authenticated context.
3. WHEN a consultant or partner_admin requests a record that belongs to another
   partner THEN the system SHALL respond as if the record does not exist (404),
   and SHALL NOT disclose its existence.
4. WHERE a platform_operator uses a dedicated admin route THE system MAY return
   cross-partner data, AND THE system SHALL record the access in `audit_events`.
5. THE codebase SHALL enforce, through a lint rule or equivalent automated check,
   that tenant data access outside the repository layer fails the build.
6. THE system SHALL include an isolation test suite that creates two partners and
   asserts that every tenant-scoped read and write endpoint refuses cross-partner
   access; this suite SHALL run in CI and SHALL pass.

### Requirement 5: Authorization by role

**User Story:** As a partner admin, I want routes gated by role, so that
consultants cannot reach admin actions and only platform operators act across
partners.

#### Acceptance Criteria

1. WHEN a request reaches an admin route THEN the API SHALL require the caller to
   hold `partner_admin` or `platform_operator`, and SHALL reject others with 403.
2. WHEN a request reaches a cross-partner operator route THEN the API SHALL
   require `platform_operator`, and SHALL reject others with 403.
3. THE authorization decision SHALL derive from the roles resolved in Requirement
   2, not from any client-supplied role value.

### Requirement 6: Audit and observability baseline

**User Story:** As a platform operator, I want admin writes audited and requests
logged without leaking sensitive data, so that actions are traceable and logs are
safe.

#### Acceptance Criteria

1. WHEN an admin write or a generation/deployment action occurs THEN the system
   SHALL append a row to `audit_events` with actor, partner, action, target, and
   before/after state.
2. THE system SHALL emit structured logs carrying request id, partner id, user
   id, and project id where applicable.
3. THE system SHALL NOT write intake free text, secrets, or sandbox credentials
   to logs.

## Non-functional requirements

1. All customer data SHALL be stored encrypted at rest (KMS) and separated per
   partner through `partner_id`.
2. The API SHALL verify JWTs on every protected request with no unauthenticated
   bypass other than health and the auth callback.
3. Tenant isolation SHALL be proven by the passing isolation test suite, with
   zero cross-partner reads or writes.
4. Dependencies SHALL be pinned; new ones vetted per `tech.md`.

## Out of scope for this spec

- The startup Terraform template and its parameter schema (separate spec).
- Intake UI, generation, diagram, estimate, validation, sandbox, and handoff
  features (later specs). This spec only creates their tables and the shell.
- The agent runtime and tools (later spec).
