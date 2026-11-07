# Requirements: Agent and Admin

## Introduction

This is the last spec of the MVP. It covers two things that sit on top of every
other spec:

1. **The agent**: the Strands agent on Amazon Nova through Bedrock that helps a
   consultant with intake, parameters, diagrams, estimates, validation results,
   and sandbox plan requests. It reads and suggests. It cannot approve, apply, or
   destroy anything, and it never writes Terraform or draw.io XML.
2. **The admin surface and sign-in**: Cognito sign-in for invited users, partner
   admin pages (users and roles, default assumptions), and platform operator pages
   (partners, template versions, default assumptions, audit log). The sandbox
   accounts page belongs to `sandbox-deployment`.

It maps to the Weeks 3–4 (agent) and 5–6 (admin) milestones and PRD user stories
8, 12, and 13. It builds on every earlier spec and calls their service functions;
it adds no new business logic for estimates, generation, validation, diagrams, or
deployment.

Source of truth: the PRD and Technical Design in `docs/`, `security.md`, and
`agent-tools.md`. Where a screen or sample conflicts with them, the documents win.

## Glossary

- **Agent**: the Strands agent running inside the API service.
- **Tool**: a typed function the agent may call. The set is fixed at twelve.
- **Proposal**: a validated parameter change the agent suggests. It changes nothing
  until a person accepts it.
- **Result card**: a structured block the UI renders from a tool result (estimate,
  validation, plan). Figures come from cards, not from model text.
- **Feature flag**: a platform setting that turns the agent off without a deploy.
- **Partner admin / consultant / platform operator**: the three roles. No others.

## Requirements

### Requirement 1: Agent conversation and streaming

**User Story:** As a consultant, I want to chat with an assistant inside a project,
so that I get help without leaving the stage I am working on.

#### Acceptance Criteria

1. THE system SHALL expose `POST /api/projects/{id}/agent/messages` that accepts a
   message and streams the response as server-sent events: text tokens, tool-call
   status, result cards, proposals, completion, and errors.
2. THE agent SHALL run inside the API service, using Amazon Nova Pro by default and
   Nova Lite for lower-cost calls, with the orchestration model set explicitly.
3. IN every user-facing label THE assistant SHALL be named "Lusiform Assistant" with
   the model shown as "Amazon Nova Pro" (or the Nova model actually used). It SHALL
   NOT be called Claude or any other model.
4. THE conversation SHALL be scoped to one project and one user, and SHALL be
   restored when the user reopens the project.
5. THE request SHALL accept an `Idempotency-Key` so a retry does not run the turn
   twice.
6. THE system SHALL cap a turn at a maximum number of tool iterations, a maximum
   input length, and a timeout, and SHALL rate-limit messages per user.

### Requirement 2: The tool set

**User Story:** As a consultant, I want the assistant to use the same operations the
UI uses, so that its answers match what I see.

#### Acceptance Criteria

1. THE agent SHALL have exactly these tools: `get_intake`, `update_intake_field`,
   `suggest_parameters`, `set_parameters`, `get_price_estimate`,
   `build_architecture_model`, `render_drawio`, `get_diagram_validation`,
   `request_generation`, `get_validation_results`, `request_sandbox_plan`,
   `get_plan`.
2. EVERY tool SHALL validate its input against the same schema the UI uses before
   executing, and SHALL reject invalid input with a safe error the agent can read.
3. EVERY tool SHALL run in the caller's request context (partner, user, role) and
   SHALL be scoped to the current project; a tool call SHALL never reach another
   partner's data.
4. `update_intake_field` SHALL write only to the mutable intake draft. It SHALL NOT
   create a project version.
5. `set_parameters` SHALL create a proposal (Requirement 4). It SHALL NOT create or
   change a project version.
6. `get_price_estimate` SHALL return figures from the estimate service, either for
   the current version or as a non-persisted preview for a proposal, with the price
   snapshot time.
7. `request_generation` and `request_sandbox_plan` SHALL create a job only, through
   the same service functions and gates the UI uses (the export gate applies to
   plans).
8. `render_drawio` and `build_architecture_model` SHALL take no XML, layout, or
   Terraform as input; they request a deterministic render from the architecture
   graph.

### Requirement 3: The agent boundary

**User Story:** As a platform operator, I want a hard limit on what the agent can
do, so that no model output can change infrastructure.

#### Acceptance Criteria

1. THE agent SHALL have no tool, and no route reachable from a tool, that approves a
   plan, applies a plan, or destroys resources.
2. THE approve, apply, and destroy routes SHALL reject any request that originates
   from the agent runtime, even if the user is authorized.
3. THE tool registry SHALL be a fixed allowlist checked at startup; adding a tool
   outside the allowlist SHALL fail the build or the boot.
4. THE agent SHALL NOT write Terraform, draw.io XML, shell commands, or file names.
5. THE agent SHALL NOT change a user's role, a partner, a template version, or any
   admin setting.

### Requirement 4: Parameter proposals

**User Story:** As a consultant, I want the assistant to suggest parameter changes
that I accept or dismiss, so that nothing changes without my decision.

#### Acceptance Criteria

1. WHEN the agent calls `set_parameters` THEN the system SHALL validate the change
   against the template version's parameter schema and store a pending proposal
   with the changes, the base version, and a cost-impact preview from the estimate
   service.
2. THE UI SHALL show the proposal as a card with the field changes, the cost impact
   rendered from the estimate service, and "Accept as new version" and "Dismiss".
3. WHEN a consultant accepts THEN the system SHALL create a new immutable project
   version through the same function the parameter form uses, as that user, and SHALL
   record the resulting version on the proposal.
4. IF the base version is no longer the latest THEN accept SHALL fail with 409
   `PROPOSAL_STALE` and the proposal SHALL be marked expired.
5. Dismiss SHALL change only the proposal's status. A proposal SHALL be accepted or
   dismissed at most once.
6. THE agent SHALL NOT be able to accept a proposal.

### Requirement 5: Output discipline

**User Story:** As a consultant, I want every cost or compliance figure to come from
a service, so that I never act on a number the model made up.

#### Acceptance Criteria

1. ANY currency amount, percentage, count, or validation result the assistant states
   SHALL come from a tool result in the same turn and be shown in a result card.
2. THE system SHALL check the assistant's final text: a currency amount that is not
   present in a tool result of the turn SHALL cause the message to be replaced by a
   safe fallback, and the event SHALL be logged.
3. THE assistant SHALL NOT state or imply that the platform or any architecture is
   certified or compliant with SOC 2, PCI-DSS, HIPAA, ISO 27001, or FedRAMP, or that
   it guarantees an uptime figure. A message containing such a claim SHALL be
   replaced by a safe fallback.
4. UI numbers SHALL come from the estimate and validation services, not from message
   text.

### Requirement 6: Untrusted input and guardrails

**User Story:** As a platform operator, I want customer free text treated as data,
so that it cannot steer the agent or reach generated output.

#### Acceptance Criteria

1. INTAKE notes and any other free text SHALL be passed to the model as clearly
   delimited untrusted data, and SHALL NOT be concatenated into Terraform, file
   names, shell commands, or tool names.
2. Bedrock guardrails SHALL filter prompts and outputs that include free-text notes.
3. THE system prompt SHALL state that instructions found in data are to be ignored.
4. A guardrail intervention SHALL produce a safe message to the user and a logged
   event without the blocked text.

### Requirement 7: Availability, models, and limits

**User Story:** As a consultant, I want the product to keep working when the
assistant is off or throttled, so that the assistant is never a dependency.

#### Acceptance Criteria

1. THE system SHALL provide a feature flag that disables the agent without a deploy,
   settable by a platform operator and audited.
2. WHEN the agent is disabled or Bedrock is unavailable or throttled THEN the agent
   route SHALL return a clear error, the UI SHALL show the assistant as unavailable,
   and every function the assistant offers SHALL remain available in the normal UI.
3. EACH Nova model SHALL be evaluated for tool-calling reliability and streaming
   support with scripted conversations before it is enabled.
4. Nova Premier SHALL be used only if evaluation shows Nova Pro is insufficient.

### Requirement 8: Logging and audit of agent activity

**User Story:** As a platform operator, I want every tool call recorded, so that
agent activity is traceable.

#### Acceptance Criteria

1. EVERY tool call SHALL be recorded with project id, user id, partner id, tool name,
   parameters, status, and duration, in an append-only table.
2. PARAMETERS recorded SHALL redact free-text fields so intake text does not appear
   in logs or call records.
3. Structured logs SHALL carry request id, partner id, user id, and project id, and
   SHALL NOT carry message text or intake free text.
4. Accepting or dismissing a proposal, and toggling the feature flag, SHALL write
   `audit_events` rows.

### Requirement 9: Sign-in

**User Story:** As an invited user, I want to sign in with my email and password, so
that I reach my partner's workspace.

#### Acceptance Criteria

1. THE sign-in page SHALL use Cognito's hosted login with email and password only.
   There SHALL be no SSO, no federated identity, and no self-service sign-up.
2. THE sign-in page SHALL state that access is by invitation from the partner admin.
3. A user whose account is deactivated, or whose partner is suspended, SHALL be
   refused by the API with a clear message, even with a valid token.
4. THE sign-in page SHALL make no compliance claim and show no uptime figure.
5. A user SHALL belong to exactly one partner, so no workspace picker SHALL be
   shown.

### Requirement 10: Users and roles (partner admin)

**User Story:** As a partner admin, I want to invite users and assign roles, so that
my team can work in the platform.

#### Acceptance Criteria

1. A partner admin SHALL be able to list users in their partner, invite a user by
   email with the role consultant or partner admin, change a user's role, deactivate
   and reactivate a user, and resend a pending invitation.
2. THE system SHALL create the Cognito user and send the invitation, and SHALL mark
   the user invited until the first sign-in.
3. THE system SHALL NOT allow removing, demoting, or deactivating the last active
   partner admin of a partner, and a partner admin SHALL NOT deactivate themselves.
4. THE system SHALL NOT allow a partner admin to assign or edit the platform
   operator role or to see another partner's users.
5. WHEN a user is deactivated THEN the system SHALL disable the Cognito user and end
   their sessions, and the API SHALL refuse their tokens.
6. EVERY change SHALL append an `audit_events` row with before and after state, and
   write endpoints SHALL accept `Idempotency-Key`.

### Requirement 11: Partners (platform operator)

**User Story:** As a platform operator, I want to create and suspend partners, so
that I control who uses the platform.

#### Acceptance Criteria

1. A platform operator SHALL be able to list partners with status, user count,
   project count, and sandbox trust status; create a partner with its first partner
   admin invitation; and suspend or reactivate a partner.
2. A suspended partner's users SHALL be refused by the API; data SHALL be retained.
3. THE operator's cross-partner reads and writes SHALL go through dedicated routes
   and SHALL write `audit_events` rows.
4. NO operator route SHALL show an external id, a sandbox credential, or intake
   free text.

### Requirement 12: Template versions (platform operator)

**User Story:** As a platform operator, I want to see and publish template versions,
so that consultants use only reviewed ones.

#### Acceptance Criteria

1. A platform operator SHALL be able to list template versions with semver, status
   (draft, published, retired), Terraform version, review record, and the number of
   projects using each, and view the parameter schema read-only.
2. THE system SHALL register a draft version from the publish helper's output; it
   SHALL NOT let the UI edit a schema or template file.
3. THE system SHALL refuse to publish a version without a recorded expert review, and
   SHALL refuse to publish if the stored file manifest does not match the files
   shipped with the service.
4. A status change SHALL be recorded as an append-only event, so the immutable
   `template_versions` row is never updated.
5. A retired version SHALL NOT be selectable for new projects and SHALL stay readable
   for existing ones.
6. EVERY status change SHALL append an `audit_events` row.

### Requirement 13: Default assumptions

**User Story:** As a partner admin or platform operator, I want default estimate
assumptions, so that new estimates start from sensible values.

#### Acceptance Criteria

1. A platform operator SHALL edit the platform default assumptions; a partner admin
   SHALL edit their partner's defaults or reset to the platform defaults.
2. THE fields SHALL be requests per month, database storage GB, data transfer out GB
   per month, compute runtime hours per month, and average log size per request, each
   validated within bounds.
3. A change SHALL apply only to assumption sets created afterward and SHALL NOT
   change any existing estimate or version.
4. EVERY change SHALL append an `audit_events` row with before and after values.

### Requirement 14: Audit log

**User Story:** As a platform operator, I want to filter and export the audit log, so
that I can review who did what.

#### Acceptance Criteria

1. A platform operator SHALL be able to list `audit_events` across partners with
   filters for partner, actor, action, target type, and date range, using cursor
   pagination.
2. THE log SHALL be described as append-only. THE system SHALL NOT claim
   cryptographic signing or a compliance attestation.
3. THE detail view SHALL show actor, partner, target, result, and before and after
   state, with free-text and secret fields redacted.
4. THE system SHALL export the filtered log as CSV, neutralizing cells that begin
   with `=`, `+`, `-`, `@`, tab, or carriage return.
5. Opening the log or an export SHALL itself write an `audit_events` row.
6. Partner admins SHALL NOT have access to the audit log in the MVP (see open
   questions).

### Requirement 15: Authorization and isolation

**User Story:** As a platform operator, I want every route role-checked and
partner-scoped, so that no one reaches data they should not.

#### Acceptance Criteria

1. EVERY admin route SHALL require the correct role from the token-resolved context,
   not a client-supplied role.
2. Partner-admin routes SHALL be scoped to the caller's partner. A request naming
   another partner's user SHALL return 404.
3. Agent routes SHALL be in the isolation suite: partner A SHALL NOT read partner B's
   conversations, proposals, or tool calls.
4. Platform-operator routes SHALL live under a separate prefix and SHALL be refused
   for other roles with 403.

## Non-functional requirements

1. The first streamed token SHALL arrive within 3 seconds under normal Bedrock
   latency; this is a target to measure in the pilot.
2. No intake free text, message text, secret, or external id SHALL appear in logs.
3. The agent and every admin write SHALL work with the other features unchanged when
   the agent flag is off.
4. A scripted evaluation set SHALL cover tool selection, schema rejection, figure
   citation, and refusal to approve, apply, or destroy.

## Out of scope for this spec

- SSO, SAML, federated identity, and any role beyond the three.
- Customer-facing sharing, proposal pages, or billing.
- Multi-partner user membership and a workspace picker.
- Partner-authored templates or modules.
- Agent actions on infrastructure, approvals, or admin settings.
- Sandbox account onboarding and the approval policy (see `sandbox-deployment`).
- Audit log access for partner admins (open question).
