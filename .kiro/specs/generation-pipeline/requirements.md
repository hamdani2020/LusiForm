# Requirements: Generation Pipeline

## Introduction

This spec turns a project version into its core artifacts: the architecture
graph, the rendered Terraform project, and the cost estimate. It covers the
generation job and worker handler, the deterministic renderer, the architecture
graph that is the single source for both Terraform and the diagram, and the
estimate service backed by the AWS Pricing API with editable assumptions and CSV
export. It also delivers the Architecture-stage parameter form and the Estimate
stage screen. It maps to the Weeks 5–6 milestone and PRD user stories 2, 3, and 4.

It builds on `foundation`, `startup-template` (modules, schema, inventory), and
`intake-and-versions` (versions and the parameter API). Validators, packaging,
the draw.io diagram, the sandbox, and the agent are later specs; this spec leaves
clear hook points for them.

Source of truth: the PRD and Technical Design in `docs/`, and the steering files.

## Glossary

- **Generation job**: a queued unit of work that builds the architecture graph
  and renders the Terraform project for one version (`generation_jobs`).
- **Architecture graph**: typed nodes, edges, and groups describing the
  version's architecture; the single source for Terraform and the diagram.
- **Manifest**: a file recording the template version, parameter values, and the
  hash of every rendered file.
- **Assumption set**: the usage assumptions behind an estimate (requests, storage,
  data transfer, runtime hours), stored per version (`assumption_sets`).
- **Price snapshot**: the prices used for an estimate and when they were fetched.

## Requirements

### Requirement 1: Generation jobs

**User Story:** As a consultant, I want generation to run automatically when I
create or change a version, so that the Terraform and graph are always current
without extra steps.

#### Acceptance Criteria

1. WHEN a project version is created THEN the system SHALL enqueue a generation
   job for it.
2. WHEN a consultant requests generation for a version THEN the system SHALL
   return the existing job if one is queued, running, or succeeded for that
   version, and SHALL NOT start a duplicate.
3. THE system SHALL expose job status (queued, running, succeeded, failed) and,
   on failure, an error message safe to show the consultant.
4. THE job payload SHALL contain only identifiers, the template version, the
   region, and parameter values; it SHALL NOT contain intake free-text notes or
   any secret.
5. WHEN a job fails on a transient error THEN the worker SHALL retry it a bounded
   number of times, then mark it failed and move the message to a dead-letter
   queue.
6. THE worker SHALL report results without direct access to the tenant database.

### Requirement 2: Architecture graph

**User Story:** As a consultant, I want one model of the architecture behind both
the code and the diagram, so that they can never disagree by construction.

#### Acceptance Criteria

1. THE generation job SHALL build an architecture graph from the template
   version's inventory and the version's parameters before rendering anything.
2. THE graph SHALL contain typed nodes for AWS resources, edges for connections,
   and groups for region, VPC, Availability Zones, subnets, and layers (edge,
   compute, data, monitoring).
3. EVERY node SHALL map to exactly one Terraform resource address in the rendered
   project, and the graph SHALL contain no node for a resource the project does
   not create.
4. THE graph SHALL be serialized canonically, so the same inputs produce a
   byte-identical graph, and its SHA-256 SHALL be stored with the version.
5. A stored graph SHALL be immutable; consultants SHALL NOT edit it directly.

### Requirement 3: Terraform rendering

**User Story:** As a consultant, I want a readable Terraform project rendered for
my version, so that I can review it and later hand it to the customer.

#### Acceptance Criteria

1. THE renderer SHALL render the Terraform project from the architecture graph
   and the template version's modules and root templates.
2. THE rendered project SHALL include the modules, root configuration,
   `variables.tf`, `terraform.tfvars.example`, a generated `README.md`, and a
   manifest with the template version, parameters, and the hash of every file.
3. WHEN the same version inputs are rendered again THEN the output SHALL be
   byte-identical; rendered files SHALL contain no timestamps or run-specific
   values.
4. THE rendered output SHALL contain no credentials or AWS account IDs and SHALL
   NOT include intake free-text notes.
5. THE renderer's output for the template fixtures SHALL match the golden output
   stored by the `startup-template` spec.
6. WHEN rendering succeeds THEN the system SHALL store the files and manifest in
   the artifact bucket under the partner and version prefix, and record them in
   `artifacts`.
7. WHEN rendering succeeds THEN the system SHALL trigger validation through a hook
   that the validation spec implements.

### Requirement 4: Architecture stage

**User Story:** As a consultant, I want to review and adjust the architecture's
parameters and see when outputs need regenerating, so that I stay in control of
what gets generated.

#### Acceptance Criteria

1. THE Architecture stage SHALL show the version's parameters in a form whose
   options and bounds come from the template schema.
2. WHEN the consultant changes a parameter THEN the form SHALL show the change as
   unapplied, mark the diagram and Terraform as stale, and offer "Regenerate" and
   "Revert".
3. WHEN the consultant chooses "Regenerate" THEN the system SHALL create a new
   version through the parameter API, which enqueues generation, and the stage
   SHALL show progress until the job finishes.
4. IF a parameter is invalid THEN the form SHALL show the bound inline and SHALL
   NOT allow "Regenerate".
5. THE stage SHALL leave a slot for the diagram canvas, which the diagram spec
   fills.

### Requirement 5: Cost estimate

**User Story:** As a consultant, I want a cost estimate from real AWS prices with
assumptions I can inspect and change, so that the customer can trust the numbers.

#### Acceptance Criteria

1. THE estimate SHALL be computed by the estimate service from the version's
   architecture graph, its assumption set, and prices from the AWS Pricing API
   for the project's region.
2. EACH line item SHALL show the AWS service, the Terraform resource, the billing
   unit, the unit price, the quantity, and the monthly cost.
3. THE estimate SHALL show the monthly total, the annual total (12 times the
   monthly total), the price snapshot time, and the region.
4. THE estimate SHALL compare the monthly total with the intake budget ceiling
   and show the percentage used.
5. WHEN the consultant changes an assumption THEN the system SHALL save a new
   assumption set and a new estimate for the same version, and SHALL NOT change
   the version's Terraform output.
6. THE estimate SHALL state its basis: on-demand prices, excluding free tier,
   taxes, support plans, and credits.
7. A new version's first assumption set SHALL come from the partner's default
   assumptions, or the platform defaults when the partner has none.
8. EVERY figure shown SHALL come from the estimate service; no figure SHALL come
   from model-generated text.

### Requirement 6: Price cache

**User Story:** As a consultant, I want estimate edits to respond quickly, so that
I can explore assumptions during a customer conversation.

#### Acceptance Criteria

1. THE system SHALL cache prices per region and service code with a time-to-live.
2. WHEN a price is in the cache and not expired THEN the estimate service SHALL
   use it without calling the Pricing API.
3. WHEN the Pricing API is unavailable and a cached price exists THEN the service
   SHALL use the cached price and show its age; WHEN no cached price exists THEN
   the service SHALL return an error naming the missing price rather than a
   partial total.
4. THE consultant SHALL be able to refresh prices, which fetches new prices and
   creates a new estimate.

### Requirement 7: CSV export

**User Story:** As a consultant, I want to export the estimate as CSV, so that I
can share it with the customer.

#### Acceptance Criteria

1. THE CSV SHALL contain line items, unit prices, quantities, monthly costs, the
   monthly total, and the annual total.
2. THE CSV SHALL include the region, the price snapshot time, the version number,
   and the assumption values used.
3. THE CSV SHALL neutralize spreadsheet formula injection in every text cell.

### Requirement 8: Isolation, audit, and observability

**User Story:** As a platform owner, I want generation and estimates to keep the
foundation guarantees, so that new paths don't weaken isolation.

#### Acceptance Criteria

1. EVERY new endpoint SHALL go through the repository layer and SHALL be added to
   the isolation suite.
2. Artifact keys SHALL include the partner id, and the API SHALL read artifacts
   only for the caller's partner.
3. WHEN a generation job starts or finishes THEN the system SHALL append an
   `audit_events` row.
4. THE system SHALL record metrics for job duration and failure rate, Pricing API
   call count, and cache hit rate.

## Non-functional requirements

1. Graph build and render SHALL take under 5 seconds for a standard project, so
   that generation including validation fits the 60-second target.
2. An assumption edit SHALL return a new estimate in under 3 seconds with a warm
   price cache.
3. On the pilot scenarios, estimates SHALL fall within ±15% of the consultant's
   manual estimate on at least 3 of 4 (PRD success metric).

## Out of scope for this spec

- Validators and their results, and the zip package (validation-and-packaging).
- The draw.io renderer, diagram validation, and parity check (diagram).
- Sandbox plan and apply (sandbox-deployment).
- The agent and the admin screen for default assumptions (agent-and-admin). This
  spec creates the default assumptions table and reads it.
