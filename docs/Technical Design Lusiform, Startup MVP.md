# Technical Design: Lusiform, Startup MVP

**Version:** 0.1 (draft) **Owner:** \[Name\] **Related:** Startup MVP PRD v0.1 **Status:** For engineering review

## 1. Purpose and Scope

This document describes how the startup-tier MVP will be built. It covers architecture, the agent and generation pipeline, the architecture diagram, sandbox deployment with named approval, the data model, the admin surface, security, and delivery. It follows the updated PRD scope for the startup pattern: intake through cost estimate, validated Terraform, a draw.io architecture diagram, and an approved deployment to a partner sandbox account. Deployment to customer accounts remains out of scope.

## 2. Architecture Overview

The platform has four runtime components behind one domain:

- **Web app:** React (Vite), shadcn/ui, Tailwind. Serves consultant and admin screens, including the diagram viewer and deployment approval.
- **API service:** FastAPI on ECS Fargate. Handles auth, projects, intake, estimates, admin endpoints, approvals, and streaming agent responses.
- **Agent runtime:** Strands Agents (Python) on Nova models through Bedrock, running inside the API service. It calls typed tools for intake, parameters, diagrams, and plan requests. It never writes Terraform or draw.io XML, and it cannot approve, apply, or destroy.
- **Worker service:** ECS Fargate tasks on a queue. Renders Terraform and draw.io files, runs validators, runs sandbox `terraform plan` and `apply`, and packages zips.

Supporting services: PostgreSQL (RDS), S3 (artifacts and zips), SQS (jobs), Cognito (auth), Secrets Manager, Bedrock (Nova models), AWS Pricing API.

### Request flow

1. Consultant completes intake in the web app. The API validates it and saves a project version.
2. Consultant requests generation. The API enqueues a generate job.
3. The worker renders the Terraform project and the architecture graph, writes them to S3, and runs the validators.
4. The worker renders the draw.io diagram from the graph, validates it, and checks parity with the Terraform. Results are stored with the version.
5. The consultant reviews the estimate, then requests a sandbox plan once validation passes.
6. The worker runs terraform plan in the partner's sandbox account and stores the plan hash. The consultant reviews the full plan and approves it.
7. The worker runs terraform apply from the approved plan. Status streams to the UI and every step is audited.
8. The consultant downloads the zip, or runs an approved teardown of the sandbox resources.

## 3. Key Design Decisions

| Decision | Choice | Rationale |
| --- | --- | --- |
| Terraform generation | Template rendering, not LLM-written code | Satisfies the PRD requirement for deterministic output |
| Architecture diagram | Agent calls a typed tool; a deterministic renderer writes draw.io XML | The model never writes XML; output is validated and repeatable |
| Single source of truth | One architecture graph drives Terraform and the diagram | Keeps code and diagram in sync; enables the parity check |
| Agent role | Intake help, parameter suggestions, diagram and plan requests, explanations | Keeps the model out of the artifact path and out of approvals |
| Backend | Single FastAPI service plus one worker type | One language, one deployment model for the MVP |
| Validation | Runs in isolated worker containers | Terraform and scanner binaries stay away from the web process |
| Deployment | Sandbox only, after validation and named approval of a plan hash | Nothing applies without a reviewed, unchanged plan |
| Versioning | Immutable project versions | Reproducibility, and the basis for audit and version history |
| Multi-tenancy | Shared database, partner\_id on every tenant row, enforced in the data access layer | Simple for MVP; isolation tested explicitly |

## 4. Agent Design

### Model configuration

An orchestration model is set explicitly on the Strands agent: Amazon Nova Pro by default, Nova Lite for lower-cost calls, and Nova Premier only if evaluation shows Pro is insufficient. Each model is tested for tool-calling reliability and streaming support before it is enabled.

### Tools exposed to the agent

| Tool | Purpose | Side effects |
| --- | --- | --- |
| get\_intake | Read current intake for a project | None |
| update\_intake\_field | Set one validated intake field | Writes a draft intake change |
| suggest\_parameters | Propose template parameters from intake | None (returns suggestions) |
| set\_parameters | Apply validated template parameters | Writes a draft version |
| get\_price\_estimate | Compute estimate for current parameters and assumptions | None |
| build\_architecture\_model | Return the architecture graph for a version | None |
| render\_drawio | Render the draw.io diagram from the graph | Creates a diagram job |
| get\_diagram\_validation | Read diagram validation and parity results | None |
| request\_generation | Enqueue generation for the current version | Creates a job |
| get\_validation\_results | Read Terraform validator output for a version | None |
| request\_sandbox\_plan | Queue terraform plan for a passed version | Creates a plan job; cannot apply |
| get\_plan | Read plan output, hash, and approval status | None |

All write tools validate input against the same schemas the UI uses. The agent cannot write outside the current partner's project, and every tool call is logged with the project id, user id, and parameters.

### Guardrails

- Tool inputs are schema-checked before execution.
- Agent output that claims a cost or compliance result must cite a tool result. The UI displays numbers from the estimate service, not from model text.
- Bedrock guardrails are configured for prompt and output filtering on free-text notes.

## 5. Template and Generation Pipeline

### Startup template

The startup reference architecture is a set of Terraform modules: networking (single region, one VPC, two AZs where the parameter requires it), a serverless or small container compute module, a managed database module, logging and basic monitoring, and an IAM module with least-privilege roles.

Each module has a parameter schema with types, allowed values, and ranges. Templates are stored as files in the repository with a version number. Changes to templates create a new template version (see section 7).

### Architecture graph and diagram

Rendering first produces an architecture graph: typed nodes for AWS resources, edges for connections, and groups for VPC, subnets, AZs, and layers (edge, compute, data, monitoring). The graph is the single source for both the Terraform modules and the diagram. Consultants never edit it directly. Changes come from the parameter form or the agent, which update the graph and re-render.

A draw.io renderer turns the graph into a `.drawio` file using draw.io's AWS icon shapes. It uses one fixed layout algorithm, so the same graph always produces the same file. The worker then validates the diagram: the XML parses, every edge references existing nodes, every icon comes from the approved set, and a parity check confirms that each Terraform resource appears in the diagram and each diagram edge maps to a Terraform connection. The SVG preview is rendered server-side, so no customer data goes to a third-party editor. Parity mismatches block the version in the MVP, pending the decision listed under Open questions.

### Rendering

1. Load the intake and the selected template version.
2. Validate parameters against the template schema.
3. Render the module files and the root configuration, plus `variables.tf`, `terraform.tfvars.example`, and a generated `README.md`.
4. Write a manifest with the template version, parameter values, and file hashes.

Rendering is pure: the same inputs and template version produce byte-identical output. This is covered by a regression test that compares hashes against stored fixtures.

### Validation

The worker runs these checks in order:

1. `terraform fmt -check`
2. `terraform init -backend=false` and `terraform validate`
3. `tflint` with the AWS ruleset
4. `checkov` on the rendered directory

Each result is stored with the version: tool name, version, exit code, summarized findings, and severity counts. Results are shown in the UI. High-severity Checkov findings are flagged as blocking for export in the MVP pilot.

### Packaging

The zip contains the rendered project, the manifest, and the validation report. It's written to S3 under the partner and version prefix, and downloaded through short-lived presigned URLs.

## 6. Cost Estimation

The estimate service maps each line item in the rendered architecture to AWS Pricing API queries for the selected region. Usage assumptions (requests per month, storage GB, data transfer GB, compute hours) come from a table stored with the project version.

- Prices are cached per region and service code with a time-to-live, so interactive edits don't hit the Pricing API each time.
- Each estimate stores the price snapshot timestamp and the assumptions used.
- The CSV export contains line items, unit prices, quantities, monthly totals, and annual totals.
- Changing an assumption creates a new estimate for the same version, without changing the version's Terraform output.

## Sandbox deployment and approval

Deployment is the last step of the MVP flow. It runs only against the partner's sandbox AWS account, and only after validation passes and a named consultant approves the exact plan.

- **Preconditions:** the version passed the Terraform gate (fmt, validate, tflint, Checkov), and the diagram passed validation and parity.
- **Sandbox onboarding:** the partner creates a cross-account role that trusts the platform worker role, with an external ID per partner and a fixed policy limited to the resource types in the startup template. Admins see the account ID, role ARN, and trust status.
- **Plan:** the worker runs terraform plan against the project's own state, stored in S3 with S3 state locking. It saves the full plan output and computes a plan hash from the rendered files, variables, provider lock file, and state serial.
- **Approval:** a named consultant reviews the plan and approves its hash. The approval records user, time, and hash. Any change to the version invalidates it.
- **Apply:** the worker runs terraform apply on the saved plan file whose hash matches the approval. If the state serial has changed since planning, the apply is refused and the plan must be re-run.
- **Outputs:** apply outputs that are not secret and the resource list are shown in the UI. Secrets are never displayed or logged.
- **Teardown:** a separate approved action runs terraform destroy on the sandbox state, with its own plan review and audit entry.
- **Agent boundary:** the agent can request a plan and explain it. It cannot approve, apply, or destroy.

## 7. Data Model

All tenant-scoped tables include `partner_id`. Primary keys are UUIDs.

| Table | Key fields | Notes |
| --- | --- | --- |
| `partners` | id, name, status | Tenant root |
| `users` | id, partner\_id, email, status | Email unique per partner |
| `user_roles` | user\_id, role | Roles: `partner_admin`, `consultant`, `platform_operator` |
| `projects` | id, partner\_id, name, created\_by, created\_at | Container for versions |
| `project_versions` | id, project\_id, number, template\_version\_id, intake\_json, parameters\_json, created\_by | Immutable after creation |
| `intake_drafts` | id, project\_id, intake\_json, updated\_at | Mutable draft before a version is cut |
| `template_versions` | id, template\_id, version, schema\_json, status, created\_at | Immutable; status `draft`, `published`, `retired` |
| `assumption_sets` | id, project\_version\_id, values\_json, created\_by | Editable copies per version |
| `estimates` | id, project\_version\_id, assumption\_set\_id, price\_snapshot\_at, monthly\_total, annual\_total, line\_items\_json | Immutable results |
| `generation_jobs` | id, project\_version\_id, status, started\_at, finished\_at, error | Status: queued, running, succeeded, failed |
| `artifacts` | id, project\_version\_id, kind, s3\_key, sha256 | Zip, manifest, validation report |
| `validation_runs` | id, project\_version\_id, tool, tool\_version, exit\_code, severity\_counts\_json, summary | One row per tool per version |
| `audit_events` | id, actor\_user\_id, partner\_id, action, target\_type, target\_id, before\_json, after\_json, created\_at | Append-only |

Project versions and template versions are immutable. Edits create new rows. This keeps pilot projects reproducible and makes version history a simple query.

Tables added for diagrams and sandbox deployment. All carry partner\_id and are append-only where noted.

| Table | Key fields | Notes |
| --- | --- | --- |
| `sandbox_accounts` | id, partner\_id, aws\_account\_id, role\_arn, external\_id\_ref, status | One row per partner sandbox; status tracks trust verification |
| `architecture_graphs` | id, project\_version\_id, graph\_json\_s3\_key, sha256 | Immutable; the source for Terraform and diagram |
| `diagram_artifacts` | id, project\_version\_id, drawio\_s3\_key, svg\_s3\_key, validation\_status, parity\_status | One per rendered diagram |
| `deployment_plans` | id, project\_version\_id, sandbox\_account\_id, plan\_hash, plan\_output\_s3\_key, state\_serial, status | Immutable once created |
| `plan_approvals` | id, plan\_id, approved\_by, approved\_at, plan\_hash | Append-only; one approval per plan |
| `deployments` | id, plan\_id, action (apply or destroy), status, started\_at, finished\_at, outputs\_json | Status: queued, running, succeeded, failed |

## 8. API Outline

All routes are under `/api`. Consultant routes are scoped to the caller's partner. Admin routes require `partner_admin` or `platform_operator`.

**Projects and intake**

- `POST /projects`, `GET /projects`, `GET /projects/{id}`
- `GET /projects/{id}/intake`, `PUT /projects/{id}/intake`
- `POST /projects/{id}/versions` (cut a version from the draft)
- `GET /projects/{id}/versions`, `GET /projects/{id}/versions/{vid}`

**Architecture and estimates**

- `PUT /projects/{id}/versions/{vid}/parameters`
- `GET /projects/{id}/versions/{vid}/estimate`, `PUT .../assumptions`, `GET .../estimate.csv`

**Generation and artifacts**

- `POST /projects/{id}/versions/{vid}/generate` (returns job id)
- `GET /jobs/{id}`
- `GET /projects/{id}/versions/{vid}/validation`
- `GET /projects/{id}/versions/{vid}/download` (presigned URL)

**Diagram, plans, and approvals**

- `POST /projects/{id}/versions/{vid}/diagram` (queues graph build, draw.io render, and validation; returns job id)
- `GET /projects/{id}/versions/{vid}/diagram` (SVG preview and validation and parity results)
- `GET /projects/{id}/versions/{vid}/diagram.drawio` (presigned download)
- `POST /projects/{id}/versions/{vid}/plans` (queues sandbox terraform plan; requires a passed version)
- `GET /plans/{id}` (plan output, hash, approval status)
- `POST /plans/{id}/approvals` (named approval of the plan hash)
- `POST /plans/{id}/apply` (requires an approval whose hash matches; refused if state serial changed)
- `POST /plans/{id}/destroy` (teardown; requires its own approved plan)
- `/admin/sandbox-accounts` (onboarding, role trust status)

**Agent**

- `POST /projects/{id}/agent/messages` (streams response via server-sent events)

**Admin**

- `/admin/partners`, `/admin/users`, `/admin/users/{id}/roles`
- `/admin/templates`, `/admin/templates/{id}/versions`
- `/admin/assumption-defaults`
- `/admin/projects` (read-only list)
- `/admin/audit-events` (filterable)

All write endpoints accept an `Idempotency-Key` header so retries from the browser don't duplicate versions or jobs.

## 9. Authentication and Authorization

- **Authentication:** Cognito user pools with the hosted login. The API verifies JWTs on every request.
- **Authorization:** a FastAPI dependency resolves the user's partner and roles from the token and database. Every query goes through a repository layer that applies `partner_id`. Direct queries outside the repository are disallowed by code review and a lint rule.
- **Platform operators** see cross-partner data through separate admin routes and their actions are audited.
- **Session:** short-lived access tokens with refresh tokens. No long-lived API keys in the MVP.

## 10. Security

- **Data at rest:** RDS and S3 encryption with KMS keys. Backups enabled.
- **Data in transit:** TLS everywhere, including ALB to service.
- **Secrets:** Secrets Manager; no secrets in images or environment files committed to the repository.
- **Worker isolation:** worker tasks run with a dedicated task role that can read and write only the artifact bucket and job queue. They have no access to tenant databases beyond the job payload and no outbound internet access except the Pricing API endpoint, if required by the design.
- **Generated code:** must contain no credentials or account IDs. A test asserts this on every template change.
- **Prompt and input safety:** free-text notes are treated as data. They are not concatenated into Terraform, and they are excluded from file names.
- **Dependency and image scanning:** container images scanned in CI; pinned Terraform, tflint, and Checkov versions in the worker image.

* **Cross-account role:** trusts only the platform worker role, uses an external ID per partner, and grants a policy limited to the startup template's resource types. Policy changes require a new template version.
* **Apply boundary:** only the worker can run apply or destroy, and only on a saved plan whose hash matches a recorded approval. The agent has no path to either.
* **Plan and apply isolation:** plan and apply run in separate worker tasks with separate roles, so a plan cannot write state that an apply later trusts without a serial check.

## 11. Non-Functional Requirements

| Requirement | Target | How it's met |
| --- | --- | --- |
| Generation time | Under 60 seconds for a standard startup project | Rendering is local; validators run in parallel where safe; `terraform init` uses a provider cache |
| Estimate response | Under 3 seconds for an edit | Price cache per region and service |
| Availability | 99.5% for the MVP pilot | Two tasks per service across AZs |
| Tenant isolation | Zero cross-partner reads in tests | Repository-level filtering plus isolation test suite |
| Reproducibility | Byte-identical output for same inputs | Pure rendering; hash-based regression tests |

## 12. Observability

- **Logs:** structured JSON to CloudWatch with request id, partner id, user id, and project id. No intake free text in logs.
- **Metrics:** request latency, job duration and failure rate by stage, Pricing API call count and cache hit rate, Bedrock latency and token usage.
- **Tracing:** OpenTelemetry through the API and worker, if time allows in the pilot; otherwise request-level logs are sufficient.
- **Alerts:** job failure rate above threshold, API 5xx rate, queue depth, and Bedrock throttling.
- **Audit:** `audit_events` table for all admin writes and generation actions.

## 13. Testing Strategy

- **Unit tests:** intake validation, parameter schemas, estimate math, and rendering functions.
- **Golden tests:** rendered Terraform compared to stored fixtures for each supported parameter set.
- **Validator tests:** a known-good template passes all four checks; a deliberately insecure fixture fails Checkov as expected.
- **Isolation tests:** a test suite that creates two partners and asserts that every read and write endpoint refuses cross-partner access.
- **Agent tests:** scripted conversations that verify tool calls, schema rejection, and that no estimate figure appears without a tool result.
- **End-to-end:** one pilot startup scenario from intake to zip download, run in CI nightly.
- **Performance:** a benchmark for generation time on the startup template.

## 14. Delivery

- **Repository:** monorepo with `api/`, `worker/`, `web/`, `templates/`, and `infra/` directories.
- **CI:** lint, type checks, unit and golden tests, isolation tests, image build and scan.
- **Infrastructure:** Terraform for the platform itself, reviewed like any other code. Separate `dev`, `pilot`, and `prod` environments.
- **Deployments:** ECS rolling deployments. Database migrations via Alembic run as a one-off task before the service rolls.
- **Feature flags:** a simple config flag for the agent, so it can be disabled without a deploy.

## 15. Milestones

These map to the PRD's build plan:

1. **Weeks 1–2:** repository, infrastructure baseline, auth, data model and migrations, startup template v1 reviewed by an AWS engineer.
2. **Weeks 3–4:** intake API and UI, project and version storage, parameter editing.
3. **Weeks 5–6:** rendering pipeline, architecture graph, pricing service and estimate UI, CSV export.
4. **Weeks 7–8:** worker, four Terraform validators, validation results UI, zip download.
5. **Weeks 9–10:** draw.io renderer, diagram validation and parity check, diagram viewer, agent diagram tools.
6. **Weeks 11–12:** sandbox onboarding, plan and approval flow, apply and teardown, deployment audit.
7. **Week 13:** agent integration with Nova, admin pages, pilot onboarding and pilot deployments.

## 16. Risks and Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Template defects | Wrong or insecure infrastructure reaches consultants | Expert review before pilot; golden and Checkov tests; validation gates |
| Nova tool-calling quality | Poor intake experience | Evaluate models in the spike; keep the intake form usable without the agent |
| Pricing API limits or drift | Inaccurate estimates | Price cache, snapshot timestamps, visible assumptions |
| Tenant data leak | Serious trust and legal impact | Repository-level filtering, isolation tests, code review rule |
| Validator version drift | Inconsistent results | Pinned tool versions in the worker image |

Deployment and diagram risks:

- **Over-broad cross-account role:** limit the policy to the template's resource types, review it per template version, and show the plan before any apply.
- **Plan drift before apply:** bind approval to the plan hash and refuse apply when the state serial has changed.
- **Diagram and Terraform disagree:** the parity check blocks the version until they match.
- **Sandbox resources left running:** a teardown action, plus a daily report of live sandbox resources per partner.

## 17. Open Questions

- Final region list for launch, which determines Pricing API coverage and template testing scope.
- Whether the pilot needs data residency guarantees beyond the chosen region.
- Whether terraform init provider downloads are allowed in workers, or providers are pre-cached in the image.
- Sandbox onboarding: whether partners create the cross-account role themselves or with a platform-guided template, and the exact policy contents.
- Plan hash scope: confirm the inputs (rendered files, variables, provider lock file, state serial).
- Approval rights: whether any consultant can approve a plan, or only partner admins can approve applies and destroys.
- Parity strictness: whether any mismatch blocks the version, or only certain mismatch types do.
- Pilot pricing model: free or flat fee per project. Affects whether billing data needs modeling now.
