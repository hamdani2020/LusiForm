# Requirements: Validation and Packaging

## Introduction

This spec runs the four Terraform validators on every generated version, stores
and shows their results, enforces the export gate, and packages the version for
handoff as a downloadable zip. It also delivers the Terraform stage (Files and
Validation views, including the blocked state) and the Handoff stage. It maps to
the Weeks 7–8 milestone and PRD user stories 5 and 6.

It builds on `foundation`, `startup-template`, `intake-and-versions`, and
`generation-pipeline` (whose `on_generation_succeeded` hook this spec
implements). The diagram files and the diagram parity result come from the
`diagram` spec, and the sandbox summary on the Handoff stage comes from the
`sandbox-deployment` spec; this spec shows them once those specs supply them.

Source of truth: the PRD and Technical Design in `docs/`, and the steering files.

## Glossary

- **Validators**: `terraform fmt -check`, `terraform init -backend=false` with
  `terraform validate`, `tflint` with the AWS ruleset, and `checkov`.
- **Terraform gate**: the pass or fail decision for a version from the four
  validators.
- **Export gate**: the decision that allows download; the Terraform gate plus
  diagram parity.
- **Severity map**: a Lusiform-maintained mapping from Checkov check IDs to
  severities.
- **Base package**: the immutable zip of the rendered project, manifest, and
  validation report for one version.
- **Full package**: the base package plus the diagram files and an estimate CSV,
  built on request.

## Requirements

### Requirement 1: Automatic validation

**User Story:** As a consultant, I want every generated version validated
automatically, so that I never hand off code nobody checked.

#### Acceptance Criteria

1. WHEN a generation job succeeds THEN the system SHALL enqueue a validation job
   for that version.
2. THE validation job SHALL run all four validators against the rendered project
   and SHALL record a result for each, even when an earlier one fails.
3. THE validators SHALL run in an isolated worker task with pinned tool versions,
   with no outbound network access and no access to the tenant database.
4. THE validation job SHALL complete within the time budget that keeps generation
   plus validation under 60 seconds for a standard project.
5. WHEN a validator exceeds its timeout or crashes THEN the system SHALL record
   that validator as errored, and the Terraform gate SHALL fail closed.

### Requirement 2: Validation results

**User Story:** As a consultant, I want clear results for each validator, so that
I can see what passed and what needs attention.

#### Acceptance Criteria

1. THE system SHALL store, per validator and version, the tool name, tool version,
   exit code, severity counts, and a summary.
2. THE system SHALL store each finding with its tool, check or rule ID, severity,
   message, file, and line.
3. THE Validation view SHALL show each validator's status and version, the total
   findings by severity, and a findings table filterable by severity.
4. WHEN the consultant selects a finding's file and line THEN the Files view SHALL
   open that file at that line.
5. THE system SHALL produce a validation report (JSON) for each version and include
   it in the package.

### Requirement 3: Severity and the Terraform gate

**User Story:** As a platform owner, I want high-severity findings to block
export with no way around it, so that insecure infrastructure never reaches a
customer.

#### Acceptance Criteria

1. THE Terraform gate SHALL pass only WHEN fmt and validate exit cleanly, tflint
   reports no errors, and Checkov reports no high-severity findings.
2. THE system SHALL assign Checkov severities from a versioned severity map tied
   to the pinned Checkov version.
3. WHEN a Checkov check that fails is not in the severity map THEN the system
   SHALL treat it as high severity.
4. THE system SHALL provide no bypass, override, ignore, or suppression of a
   blocking finding from the UI or API.
5. WHEN the Terraform gate fails THEN the system SHALL block download and sandbox
   planning for that version, and the UI SHALL explain why and what to do.
6. Low and medium findings, and tflint warnings, SHALL be shown but SHALL NOT block.

### Requirement 4: Files view

**User Story:** As a consultant, I want to read the generated Terraform in the
platform, so that I can review it before hand-off.

#### Acceptance Criteria

1. THE Files view SHALL show the rendered project's file tree and the content of a
   selected file, read-only, with line numbers.
2. THE Files view SHALL show the template version, the manifest hash, and the
   Terraform and AWS provider versions.
3. THE system SHALL serve only files listed in the version's manifest, and SHALL
   reject any other path.
4. THE platform SHALL NOT allow editing generated files; changes come from
   parameters and regeneration.

### Requirement 5: Packaging and download

**User Story:** As a consultant, I want to download a readable, editable Terraform
project, so that the customer can use it without the platform.

#### Acceptance Criteria

1. WHEN a version passes the export gate THEN the system SHALL build the base
   package containing the rendered project, the manifest, and the validation
   report.
2. THE base package SHALL be deterministic: the same version SHALL produce a
   byte-identical zip, and its SHA-256 SHALL be recorded.
3. WHEN the consultant requests the full package THEN the system SHALL build it
   from the base package, the diagram files, and the CSV of the estimate the
   consultant is viewing, and SHALL name the estimate in the package.
4. THE system SHALL serve downloads through presigned URLs that expire within five
   minutes, issued only after the caller's partner and the export gate are
   checked.
5. WHEN the export gate fails THEN the system SHALL refuse to issue a download URL.
6. WHEN a package is downloaded THEN the system SHALL append an `audit_events` row.

### Requirement 6: Handoff stage

**User Story:** As a consultant, I want one place to see what I'm handing off and
download it, so that the engagement ends with a clean package.

#### Acceptance Criteria

1. THE Handoff stage SHALL list the package contents with name, format, and size,
   each downloadable on its own when available.
2. THE Handoff stage SHALL summarize the validation gate, diagram parity, the
   sandbox result if any, and the current monthly and annual estimate.
3. THE Handoff stage SHALL offer download only; it SHALL NOT offer sharing,
   customer portals, signing, or links for people outside the partner.
4. WHEN a summary input is not yet available THEN the Handoff stage SHALL say so
   instead of showing a placeholder value.

### Requirement 7: Status, isolation, and audit

**User Story:** As a platform owner, I want validation to feed version status and
keep every isolation guarantee.

#### Acceptance Criteria

1. THE status module SHALL treat a version as validated only WHEN the Terraform
   gate passes and diagram parity passes.
2. EVERY new endpoint SHALL go through the repository layer and SHALL be added to
   the isolation suite.
3. WHEN a validation job starts or finishes THEN the system SHALL append an
   `audit_events` row.

## Non-functional requirements

1. Validation SHALL finish in under 40 seconds for a standard project, leaving
   room for generation inside the 60-second target.
2. The generated pilot template SHALL show zero high-severity Checkov findings
   (PRD success metric).
3. Tool versions SHALL match the pins in `startup-template` and the worker image.

## Out of scope for this spec

- Generating diagram files and the parity check (diagram spec).
- Sandbox plan, apply, and teardown (sandbox-deployment spec).
- Editing generated Terraform in the platform (not in the MVP).
