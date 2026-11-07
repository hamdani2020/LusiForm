# Requirements: Diagram

## Introduction

This spec renders the architecture diagram in draw.io format from the
architecture graph, validates it, checks parity with the rendered Terraform, and
shows it in the Diagram stage and the Architecture stage canvas. It also provides
the diagram functions the agent calls (build the model, render, read results);
the agent wiring itself is in `agent-and-admin`. It maps to the Weeks 9–10
milestone, PRD user story 8, and the success metric "diagram parity check passes
on every pilot version before export".

It builds on `generation-pipeline` (the graph and rendered project) and
`validation-and-packaging` (the export gate, which waits on this spec's parity
result).

Source of truth: the PRD and Technical Design in `docs/`, and the steering files.

## Glossary

- **Layout**: the positions and sizes of every group, node, and edge, computed by
  one fixed algorithm from the graph.
- **Diagram validation**: structural checks on the draw.io file (parses, edges
  reference existing cells, icons from the approved set).
- **Parity check**: the check that the diagram and the rendered Terraform describe
  the same resources and connections.
- **Approved icon set**: the draw.io AWS shapes Lusiform allows, one per node type.

## Requirements

### Requirement 1: Automatic diagram rendering

**User Story:** As a consultant, I want a diagram for every generated version, so
that the customer sees the same architecture the code describes.

#### Acceptance Criteria

1. WHEN a generation job succeeds THEN the system SHALL enqueue a diagram job for
   that version.
2. WHEN a diagram is requested for a version (by the consultant or the agent) THEN
   the system SHALL return the existing diagram job if one is queued, running, or
   succeeded, and SHALL NOT start a duplicate.
3. THE diagram job SHALL produce a `.drawio` file and an SVG preview, both from the
   version's stored architecture graph.
4. THE system SHALL NOT render a diagram from anything other than the stored graph;
   it SHALL NOT accept diagram XML, layout edits, or drawn elements from users or
   the agent.

### Requirement 2: Deterministic layout and output

**User Story:** As a platform owner, I want the same graph to always produce the
same diagram, so that diagrams are reproducible and reviewable.

#### Acceptance Criteria

1. THE renderer SHALL compute the layout with one fixed algorithm; it SHALL offer no
   auto-layout, rearrangement, or manual positioning.
2. WHEN the same graph is rendered again THEN the `.drawio` and SVG files SHALL be
   byte-identical.
3. THE diagram SHALL show the region, VPC, Availability Zones, and subnet tiers as
   containers, and SHALL place every node inside its group.
4. THE diagram SHALL use only icons from the approved icon set.
5. THE diagram files SHALL contain no credentials, AWS account IDs, or intake notes.

### Requirement 3: Diagram validation

**User Story:** As a consultant, I want the diagram checked before I hand it off,
so that I never send a broken file.

#### Acceptance Criteria

1. THE system SHALL validate that the `.drawio` file parses as a well-formed draw.io
   document.
2. THE system SHALL validate that every edge references existing source and target
   cells.
3. THE system SHALL validate that every shape uses an icon from the approved set.
4. THE system SHALL store the validation result with the diagram artifact.

### Requirement 4: Parity with Terraform

**User Story:** As a consultant, I want proof that the diagram matches the code, so
that I never mislead the customer.

#### Acceptance Criteria

1. THE parity check SHALL confirm that every Terraform resource in the rendered
   project appears in the diagram or in the graph's list of supporting resources
   that are not drawn.
2. THE parity check SHALL confirm that every diagram node maps to a Terraform
   resource in the rendered project, with the expected number of instances.
3. THE parity check SHALL confirm that every diagram edge corresponds to a
   reference between the connected resources in the rendered project.
4. THE parity result SHALL list each mismatch with its type, the resource or edge,
   and where it occurs.
5. WHEN parity fails THEN the system SHALL block export and diagram download for
   that version.
6. THE parity result SHALL be reported to the status module and the export gate.
7. THE consultant SHALL NOT be able to fix a mismatch by editing the diagram; the
   only action SHALL be to regenerate.

### Requirement 5: Diagram stage and canvas

**User Story:** As a consultant, I want to review the diagram in the platform and
inspect any component, so that I can explain the architecture to the customer.

#### Acceptance Criteria

1. THE Diagram stage SHALL show the SVG preview with zoom, fit, and a layer filter
   (edge, compute, data, monitoring).
2. WHEN the consultant selects a component THEN an inspector SHALL show its type,
   Terraform address, key attributes, connections, and a link to the source in the
   Files view.
3. THE Diagram stage SHALL show the validation and parity status, and on parity
   failure SHALL list the mismatches and offer only "Regenerate".
4. THE consultant SHALL be able to download the `.drawio` and SVG files WHEN the
   diagram validation and parity both pass.
5. THE Architecture stage canvas slot SHALL show the same preview.
6. WHILE a diagram job is running THE stage SHALL show progress.

### Requirement 6: Functions for the agent

**User Story:** As a consultant, I want to ask the assistant to draw the
architecture and get the same diagram, so that the agent never invents one.

#### Acceptance Criteria

1. THE system SHALL provide `build_architecture_model` (returns the version's
   graph), `render_drawio` (requests a diagram job), and `get_diagram_validation`
   (returns validation and parity results), with schema-checked inputs.
2. THESE functions SHALL be scoped to the caller's partner and project, and SHALL
   be logged with project id, user id, and parameters.
3. THESE functions SHALL NOT accept or return draw.io XML written by the model.

### Requirement 7: Isolation and audit

#### Acceptance Criteria

1. EVERY new endpoint SHALL go through the repository layer and SHALL be added to
   the isolation suite.
2. Diagram files SHALL be stored under the partner and version prefix and served
   only through short-lived presigned URLs after a partner check.
3. WHEN a diagram job finishes THEN the system SHALL append an `audit_events` row.

## Non-functional requirements

1. A diagram job (render, validate, parity) SHALL finish in under 10 seconds for a
   standard project.
2. The SVG preview SHALL render on the server; no customer data SHALL be sent to a
   third-party diagram service.
3. Parity SHALL pass on every pilot version before export (PRD success metric).

## Out of scope for this spec

- A free-form designer or any diagram editing (out of MVP scope).
- The agent runtime and tool wiring (agent-and-admin spec).
- Diagram themes beyond the default; dark mode is an open question.
