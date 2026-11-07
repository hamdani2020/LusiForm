# Requirements: Intake and Versions

## Introduction

This spec delivers the first consultant-facing slice of Lusiform: creating a
project, completing a structured intake for a startup workload, cutting immutable
project versions, editing template parameters, and browsing version history. It
maps to the Weeks 3–4 milestone in the Technical Design (intake API and UI,
project and version storage, parameter editing) and PRD user stories 1, 2
(parameter adjustment, API side), and 7.

It builds on `foundation` (auth, repository layer, tables) and `startup-template`
(the parameter schema). It does not render Terraform, build the architecture
graph, draw the diagram, or estimate cost; those are later specs. The
Architecture-stage screen (diagram plus parameter form) is delivered in the
`generation-pipeline` spec; this spec delivers the parameter API it calls.

Source of truth: the PRD and Technical Design in `docs/`, and the steering files.

## Glossary

- **Intake**: the structured answers describing the customer's workload.
- **Intake draft**: the mutable, in-progress intake for a project
  (`intake_drafts`), saved as the consultant works.
- **Project version**: an immutable snapshot (`project_versions`) holding the
  intake, the parameter values, and the template version used. Numbered v1, v2...
- **Parameters**: the template inputs defined by the startup template schema.

## Requirements

### Requirement 1: Projects

**User Story:** As a consultant, I want to create and find projects for my
customers, so that each engagement has one place for its work.

#### Acceptance Criteria

1. WHEN a consultant submits a new project with a name and a target region THEN
   the system SHALL create the project in the caller's partner and record the
   creator and creation time.
2. THE system SHALL offer only the supported launch regions for the target region.
3. WHEN a consultant lists projects THEN the system SHALL return only the caller's
   partner's projects, with name, customer name, current version, derived status,
   and last updated time.
4. THE projects list SHALL support filtering by status and by owner ("all" or
   "me").
5. WHEN the partner has no projects THEN the web app SHALL show an empty state
   whose single primary action is creating a project; it SHALL NOT offer file or
   spec import.
6. THE project creation dialog SHALL show the template it will use (Startup
   Reference Architecture and its version) as read-only information, and SHALL NOT
   offer a choice of architecture.

### Requirement 2: Intake form and validation

**User Story:** As a consultant, I want to enter intake answers with clear
validation, so that the platform knows the workload shape before generating
anything.

#### Acceptance Criteria

1. THE intake SHALL capture: workload type, primary AWS region, expected users,
   requests per day, peak traffic multiplier, availability target, data
   sensitivity, monthly budget ceiling (USD), and optional free-text notes.
2. THE workload type SHALL be one of the startup workloads the template supports;
   the availability target SHALL be 99.5% or 99.9%; data sensitivity SHALL be
   public, internal, or confidential.
3. THE intake SHALL NOT capture a secondary or failover region, a compliance
   baseline, or a cost guardrail strategy.
4. WHEN a field value is invalid THEN the system SHALL reject it with a message
   naming the field, using the same validation in the API and the web app.
5. THE web app SHALL show how many required fields are complete and SHALL disable
   "Create version and continue" until all required fields are valid.
6. WHEN the consultant edits the intake THEN the system SHALL save it to the
   project's intake draft, and the web app SHALL show when the draft was last
   saved.
7. THE free-text notes SHALL be stored as data only, SHALL have a maximum length,
   SHALL NOT be written to logs, and SHALL NOT be used in any resource or file
   name.

### Requirement 3: Parameter suggestions from intake

**User Story:** As a consultant, I want the platform to propose starting
parameters from my intake answers, so that I begin from a sensible configuration.

#### Acceptance Criteria

1. WHEN a version is cut from an intake THEN the system SHALL derive starting
   parameters from the intake using a deterministic rule set and the template
   schema defaults.
2. THE rule set SHALL at least map a 99.9% availability target to two
   Availability Zones and a 99.5% target to a one-AZ default.
3. THE same intake SHALL always produce the same suggested parameters.
4. WHEN a suggestion is shown in the intake form THEN the consultant SHALL be able
   to accept or dismiss it, and the system SHALL record which they chose.

### Requirement 4: Immutable project versions

**User Story:** As a consultant, I want each saved state of my project frozen as a
version, so that work is reproducible and I can return to any point.

#### Acceptance Criteria

1. WHEN the consultant chooses "Create version and continue" with a valid intake
   THEN the system SHALL create a new project version containing the intake, the
   derived parameters, and the template version, numbered one higher than the
   project's latest version.
2. A project version SHALL NOT be modified after creation; any change SHALL create
   a new version.
3. THE system SHALL record the template version used by each project version, and
   SHALL use only a template version whose status permits use in the current
   environment.
4. WHEN the same write request is retried with the same `Idempotency-Key` THEN the
   system SHALL return the original result and SHALL NOT create a second version.
5. WHEN two version creations race for the same project THEN the system SHALL
   still assign unique, sequential version numbers.

### Requirement 5: Parameter editing

**User Story:** As a consultant, I want to adjust architecture parameters within
the template's bounds, so that the architecture fits the workload.

#### Acceptance Criteria

1. WHEN the consultant submits parameter changes for a version THEN the system
   SHALL validate them against the startup template schema for that version's
   template version.
2. IF any parameter is out of bounds THEN the system SHALL reject the whole change
   with messages naming each invalid parameter and its bound, and SHALL create no
   version.
3. WHEN the changes are valid THEN the system SHALL create a new project version
   with the same intake and the updated parameters; the source version SHALL be
   unchanged.
4. THE system SHALL return the new version and a list of the parameters that
   changed from the source version.
5. THE system SHALL NOT accept any parameter not defined in the template schema.

### Requirement 6: Version history and compare

**User Story:** As a consultant, I want to see a project's version history and
compare versions, so that I can understand what changed and reopen earlier work.

#### Acceptance Criteria

1. THE system SHALL list a project's versions newest first, with number, creator,
   creation time, template version, and derived status.
2. WHEN the consultant opens a version THEN the system SHALL return its intake and
   parameters exactly as stored.
3. WHEN the consultant compares two versions of the same project THEN the system
   SHALL return the intake and parameter fields that differ, with the old and new
   values.
4. THE web app SHALL explain that versions are immutable and that edits create new
   versions.

### Requirement 7: Derived project and version status

**User Story:** As a consultant, I want a clear status for each version and
project, so that I know what needs doing next.

#### Acceptance Criteria

1. THE system SHALL derive version status from stored facts, never from a stored
   free-form status: Draft (no passed validation yet), Validated, and Sandbox
   applied, extended by later specs as their facts become available.
2. THE project status SHALL be the status of its latest version, plus "Needs
   regeneration" WHEN the latest version has parameters newer than the latest
   validated version.
3. THE status derivation SHALL live in one place, so later specs add states
   without changing callers.

### Requirement 8: Isolation, audit, and safety

**User Story:** As a platform owner, I want these new endpoints to keep every
foundation guarantee, so that the first feature does not weaken isolation.

#### Acceptance Criteria

1. EVERY endpoint in this spec SHALL go through the repository layer and SHALL be
   added to the isolation test suite.
2. WHEN a project is created or a version is cut THEN the system SHALL append an
   `audit_events` row.
3. ALL write endpoints SHALL accept an `Idempotency-Key` header.

## Non-functional requirements

1. Saving an intake draft and listing projects SHALL respond within 500 ms at
   pilot scale.
2. The intake form SHALL remain fully usable with the agent disabled.
3. The UI SHALL meet the design system in the Stitch project and follow
   accessible form practices (labels, error text tied to fields, keyboard use).

## Out of scope for this spec

- The Architecture-stage screen and diagram (generation-pipeline and diagram
  specs). This spec provides the parameter API they use.
- Terraform rendering, estimates, validation, sandbox, and handoff.
- Agent-driven suggestions (agent-and-admin spec); this spec's suggestions are
  deterministic rules.
