# Requirements: Sandbox Deployment

## Introduction

This spec is the last step of the MVP flow: deploying a validated version to the
partner's own sandbox AWS account after a named consultant approves the exact
plan, and tearing those resources down later under a separate approval. It covers
sandbox onboarding, plan, named approval, apply, apply outputs, state-drift
handling, and teardown, each audited. It maps to the Weeks 11–12 milestone and PRD
user stories 9, 10, 11, and 12.

This is the highest-risk spec. An over-broad role, or an apply against a changed
plan, could alter a real AWS account. Every control here is a hard constraint, not
a preference. It builds on `foundation`, `startup-template` (the cross-account
policy and resource inventory), `generation-pipeline`, and
`validation-and-packaging` (the export gate).

Source of truth: the PRD and Technical Design in `docs/`, and `security.md`.
Deployment to customer accounts is out of scope; the MVP deploys only to the
partner sandbox.

## Glossary

- **Sandbox account**: the partner's own non-production AWS account, onboarded
  with a cross-account role Lusiform assumes.
- **Plan**: a saved `terraform plan` for a version against the sandbox, with a
  hash and the state serial it was planned against.
- **Approval**: a named consultant's recorded sign-off on a specific plan hash.
- **Apply**: `terraform apply` of a saved, approved plan, refused if the state
  serial changed.
- **Teardown**: `terraform destroy`, with its own plan and approval.
- **State serial**: the serial number of the Terraform state, used to detect drift
  since planning.

## Requirements

### Requirement 1: Sandbox onboarding

**User Story:** As a partner admin, I want to connect our sandbox AWS account with
a least-privilege cross-account role, so that Lusiform can deploy only what the
template needs.

#### Acceptance Criteria

1. THE admin SHALL onboard one sandbox account per partner by supplying the AWS
   account id and the role name, and the system SHALL generate a per-partner
   external id stored in Secrets Manager.
2. THE system SHALL provide the exact cross-account trust policy and permissions
   policy for the partner to create, derived from the template's resource
   inventory, trusting only the Lusiform worker role, with the external id
   condition.
3. THE system SHALL verify the trust by assuming the role before marking the
   account verified, and SHALL show the account id, role ARN, and trust status.
4. THE system SHALL store a reference to the external id, never its value, and
   SHALL never display the external id or any sandbox credential.
5. THE permissions policy SHALL be limited to the resource types the startup
   template creates; a change to those types SHALL require a new template version.

### Requirement 2: Plan

**User Story:** As a consultant, I want to generate a sandbox plan for a validated
version, so that I can review exactly what will be created before anything runs.

#### Acceptance Criteria

1. THE system SHALL allow a plan only for a version that passed the export gate
   (Terraform gate and diagram parity).
2. WHEN a plan is requested THEN a worker SHALL run `terraform plan` against the
   version's own state in the sandbox, using the cross-account role, and SHALL save
   the full plan output and the saved plan file.
3. THE system SHALL compute a plan hash over the rendered files, the variables, the
   provider lock file, and the state serial, and SHALL store the plan with its
   hash, state serial, and the add/change/destroy counts.
4. THE plan SHALL be immutable once created; any change to the version SHALL
   invalidate it.
5. THE plan output shown to the consultant SHALL contain no secret values.
6. THE agent SHALL be able to request a plan and explain it, and SHALL NOT be able
   to approve, apply, or destroy.

### Requirement 3: Named approval

**User Story:** As a consultant, I want to approve the exact plan by its hash, so
that only a reviewed, unchanged plan can be applied.

#### Acceptance Criteria

1. WHEN a consultant approves a plan THEN the system SHALL record the plan id, the
   approver, the time, and the plan hash as an append-only approval.
2. THE system SHALL present approval and apply as two separate steps; approving
   SHALL NOT apply.
3. THERE SHALL be no action to revoke or edit an approval; a superseded plan is
   simply never applied.
4. WHO may approve SHALL follow the configured approval policy (see Requirement 8).

### Requirement 4: Apply

**User Story:** As a consultant, I want to apply an approved plan to the sandbox
and see the result, so that the architecture is really provisioned.

#### Acceptance Criteria

1. THE system SHALL run apply only from a saved plan file whose hash matches a
   recorded approval.
2. WHEN the state serial has changed since the plan was made THEN the system SHALL
   refuse the apply and require a new plan; there SHALL be no override.
3. THE apply SHALL run in a separate worker task with a separate role from the
   plan, so a plan cannot write state an apply later trusts without the serial
   check.
4. THE apply SHALL only ever target the partner's sandbox account, never a customer
   account.
5. WHILE apply runs THE system SHALL stream status, and on completion SHALL show
   the resource result and the non-secret outputs; it SHALL never display or log a
   secret output.
6. THE agent SHALL have no path to apply.

### Requirement 5: State drift

**User Story:** As a consultant, I want to be stopped when the sandbox changed
outside Lusiform, so that an apply never clobbers or trusts stale state.

#### Acceptance Criteria

1. WHEN a plan's state serial no longer matches the sandbox state THEN the system
   SHALL mark the plan stale and show the drift.
2. THE system SHALL refuse to apply a stale plan and SHALL require a fresh plan;
   there SHALL be no acknowledgement that bypasses this.
3. THE system SHALL show what changed out of band where the state diff reveals it.

### Requirement 6: Teardown

**User Story:** As a consultant, I want to tear down the sandbox resources under
its own approval, so that nothing is left running by accident and nothing is
destroyed without review.

#### Acceptance Criteria

1. THE teardown SHALL require its own destroy plan, its own named approval, and the
   same state-serial check as apply.
2. THE system SHALL show the destroy plan (what will be destroyed) before approval.
3. THE system SHALL NOT schedule or perform any automatic teardown; teardown is
   always an explicit, approved action.
4. WHEN teardown completes THEN the system SHALL show the result and record it.
5. THE agent SHALL have no path to destroy.

### Requirement 7: Audit and isolation

**User Story:** As a platform operator, I want every deployment action audited and
partner-scoped, so that there is a complete, trustworthy trail.

#### Acceptance Criteria

1. THE system SHALL append an `audit_events` row for onboarding, plan, approval,
   apply, drift refusal, and teardown, with actor, partner, plan hash, and result.
2. EVERY endpoint SHALL go through the repository layer and SHALL be in the
   isolation suite; a partner SHALL never reach another partner's plans, approvals,
   deployments, or sandbox account.
3. THE worker roles for plan and apply SHALL read only what the job needs and SHALL
   have no access to tenant databases.
4. A daily report SHALL list live sandbox resources per partner, so nothing is
   silently left running.

### Requirement 8: Approval policy

**User Story:** As a partner admin, I want to decide who can approve applies and
destroys, so that approval authority matches our governance.

#### Acceptance Criteria

1. THE system SHALL support an approval policy of either "any consultant" or
   "partner admin only" for applies and destroys, set per partner.
2. WHEN a user without approval authority attempts to approve THEN the system SHALL
   refuse with 403.
3. THE default policy SHALL be "any consultant", matching PRD user stories 9, 10,
   and 11, and a partner admin SHALL be able to restrict it to "partner admin
   only". (The PRD lists who may approve as an open question; this default follows
   the stories as written.)
4. WHEN the policy changes THEN the system SHALL append an `audit_events` row, and
   the change SHALL NOT affect plans already approved.

## Non-functional requirements

1. No apply or destroy SHALL run except from a saved plan whose hash matches a
   recorded approval and whose state serial is unchanged.
2. Sandbox credentials SHALL never appear in the UI, logs, API responses, or
   generated files.
3. The cross-account role SHALL grant only the template's resource types, verified
   by a test against the inventory.
4. Plan, apply, and destroy workers SHALL have no outbound internet access beyond
   the AWS endpoints they require.

## Out of scope for this spec

- Deployment to any customer AWS account.
- Drift remediation beyond re-planning.
- Cost controls or budget enforcement at apply time.
- The admin console styling beyond the sandbox accounts screen (agent-and-admin).
