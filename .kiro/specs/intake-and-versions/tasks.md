# Implementation Plan: Intake and Versions

Tasks build in order. Each cites the requirements it satisfies (see
`requirements.md`) and follows `design.md`. Depends on `foundation` (auth,
repository layer, tables, isolation suite) and `startup-template` (the parameter
schema and validator).

## Design references (Stitch project `18075726235522465175`)

Verified on regeneration: required content present, out-of-scope content absent.

| Screen | Screen ID |
| --- | --- |
| Projects | `df3d775d3d1f4a4da734d93f3029783a` |
| Projects (Empty State) with New project dialog | `fb84e75b82d242fd8ab028c8f0c08700` |
| Project Workspace - Intake Stage | `c43ed81557294245a77bb05e54201590` |
| Project - Version History & Compare | `a5464dc6c24a4df99828ef5aec5f539b` |

Build from these IDs only. Older screens with the same titles are superseded.

Superseded screens (safe to delete in Stitch during cleanup):
`361046e0cc9842e4b30ecf5341029ad4` (old Projects),
`03e0795b375c47c0b4cad0e0cae2964c` (old Projects Empty State),
`784c57fb829943469c4cbc6d60881de3` (old Intake),
`08d92c7c100443698941eb3a41dedab9` (old Project Workspace; already deleted).

- [ ] 1. Extend the schema
  - [ ] 1.1 Add the project and version columns
    - Migration adding `customer_name`, `region`, `updated_at` to `projects`, and
      `source_version_id` plus `unique(project_id, number)` to
      `project_versions`. Keep the foundation immutability triggers.
    - _Requirements: 1.1, 4.1, 4.5, 5.3_
  - [ ] 1.2 Add the idempotency store
    - `idempotency_keys` table unique on `(partner_id, key, route)` with request
      hash, stored response, and TTL cleanup.
    - _Requirements: 4.4, 8.3_
  - [ ] 1.3 Write migration tests
    - Round trip upgrade and downgrade; constraint tests for version uniqueness.
    - _Requirements: 4.5_

- [ ] 2. Build the intake schema
  - [ ] 2.1 Define the intake model
    - Pydantic model with the nine fields, enums, and bounds from `design.md`; no
      failover region, compliance baseline, or cost guardrail fields.
    - Supported regions as one config value.
    - _Requirements: 2.1, 2.2, 2.3, 1.2_
  - [ ] 2.2 Export the JSON Schema for the web app
    - Generate the schema file at build time; add a test that fails if the web
      app's copy differs from the API's.
    - _Requirements: 2.4_
  - [ ] 2.3 Protect free-text notes
    - Enforce the 4,000-character limit, add `notes` to the log redaction deny
      list, and add a test that notes never appear in log output.
    - _Requirements: 2.7_
  - [ ] 2.4 Write intake schema tests
    - Each field's bounds and enums; invalid values return messages naming the
      field.
    - _Requirements: 2.2, 2.4_

- [ ] 3. Implement parameter suggestions
  - [ ] 3.1 Write `suggest_parameters`
    - Pure function: schema defaults, then the AZ rule, then the traffic-to-task
      table, clamped to schema bounds.
    - _Requirements: 3.1, 3.2_
  - [ ] 3.2 Write suggestion tests
    - Table of intakes to expected parameters; repeat calls return identical
      output.
    - _Requirements: 3.3_

- [ ] 4. Implement the project and intake API
  - [ ] 4.1 Projects endpoints
    - `POST /projects`, `GET /projects` with status and owner filters, `GET
      /projects/{id}`, all through the repository layer, with audit on create.
    - _Requirements: 1.1, 1.3, 1.4, 8.1, 8.2_
  - [ ] 4.2 Intake draft endpoints
    - `GET` and `PUT /projects/{id}/intake`; partial saves validate the fields
      provided; store dismissed suggestions; record last-saved time and user.
    - _Requirements: 2.4, 2.6, 3.4_
  - [ ] 4.3 Idempotency middleware for writes
    - Same key and same request returns the stored response; same key with a
      different request returns 422.
    - _Requirements: 4.4, 8.3_
  - [ ] 4.4 Write endpoint tests
    - Create, list, filter, draft save, and idempotent retry.
    - _Requirements: 1.1, 1.3, 1.4, 2.6, 4.4_

- [ ] 5. Implement versions
  - [ ] 5.1 Cut a version
    - `POST /projects/{id}/versions`: require a complete, valid intake; derive
      parameters; select the template version allowed in this environment; lock
      the project row and assign the next number; audit the creation.
    - _Requirements: 4.1, 4.3, 4.5, 8.2_
  - [ ] 5.2 Read versions
    - `GET /projects/{id}/versions` newest first and `GET
      /projects/{id}/versions/{vid}` returning intake and parameters exactly as
      stored.
    - _Requirements: 6.1, 6.2_
  - [ ] 5.3 Compare versions
    - `GET /projects/{id}/versions/compare?a=&b=` returning differing intake and
      parameter fields with old and new values.
    - _Requirements: 6.3_
  - [ ] 5.4 Write version tests
    - Numbering, immutability, idempotent retry, concurrent creation yields unique
      sequential numbers, environment-based template selection, compare output.
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 6.3_

- [ ] 6. Implement parameter editing
  - [ ] 6.1 Parameter endpoint
    - `PUT /projects/{id}/versions/{vid}/parameters`: validate the full set
      against the version's template schema; reject unknown or out-of-bound
      parameters with named messages; on success create a new version with
      `source_version_id` and return it with the `changed` list.
    - Expose `GET /templates/startup/current/schema` for the UI.
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_
  - [ ] 6.2 Write parameter tests
    - Valid change creates a new version and leaves the source unchanged; invalid
      and unknown parameters create no version.
    - _Requirements: 5.2, 5.3, 5.5_

- [ ] 7. Implement status derivation
  - [ ] 7.1 Write the `version_status` module
    - Draft, validated, sandbox applied, and project-level needs regeneration,
      computed from stored facts, with extension points for later specs.
    - _Requirements: 7.1, 7.2, 7.3_
  - [ ] 7.2 Write status tests
    - Each status from fixture facts; callers never compute status themselves.
    - _Requirements: 7.1, 7.2, 7.3_

- [ ] 8. Extend the isolation suite
  - [ ] 8.1 Register every new endpoint
    - Add all endpoints from tasks 4 to 6 to the table-driven isolation suite and
      confirm the coverage guard passes.
    - _Requirements: 8.1_

- [ ] 9. Build the Projects screens
  - [ ] 9.1 Projects list
    - Build from screen `df3d775d...`: count cards, status and owner filters,
      table with derived status badges (icon plus text), pagination.
    - _Requirements: 1.3, 1.4, 7.1_
  - [ ] 9.2 Empty state and New project dialog
    - Build from screen `fb84e75b...`: single "New project" action, eight-stage
      explainer, dialog with name, customer, region, and read-only template.
    - _Requirements: 1.1, 1.2, 1.5, 1.6_

- [ ] 10. Build the Intake screen
  - [ ] 10.1 Intake form
    - Build from screen `c43ed815...`: six section cards, form validation from
      the exported JSON Schema, read-only region, required-field progress, error
      text tied to fields.
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_
  - [ ] 10.2 Autosave and actions
    - Debounced autosave with last-saved indicator, "Save draft", and "Create
      version and continue" disabled until all required fields are valid.
    - _Requirements: 2.5, 2.6, 4.1_
  - [ ] 10.3 Inline AZ suggestion
    - Accept and Dismiss, persisted to the draft.
    - _Requirements: 3.4_
  - [ ] 10.4 Assistant panel placeholder
    - Collapsible panel with "Hide assistant"; the form works fully with the
      agent disabled. The agent itself is built in the agent-and-admin spec.
    - _Requirements: NFR 2_

- [ ] 11. Build the Version History screen
  - [ ] 11.1 History and compare
    - Build from screen `a5464dc6...`: version list with status badges, open a
      version, compare two versions with a diff table, and the immutability note.
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

- [ ] 12. Web tests and accessibility
  - [ ] 12.1 Write web tests
    - Required-field gating, autosave, suggestion accept and dismiss, empty state,
      filters, compare view.
    - _Requirements: 1.5, 2.5, 2.6, 3.4, 6.3_
  - [ ] 12.2 Accessibility checks
    - Labels on every field, errors announced and tied to fields, keyboard-only
      completion of the intake.
    - _Requirements: NFR 3_

- [ ] 13. Final verification
  - [ ] 13.1 Run the full suite
    - API, web, migration, and isolation tests all pass; intake draft save and
      project list meet the 500 ms target at pilot-scale fixtures.
    - _Requirements: all, NFR 1_
  - [ ] 13.2 Confirm the acceptance criteria
    - Walk requirements 1 to 8 and note which test or artifact proves each.
    - _Requirements: all_
