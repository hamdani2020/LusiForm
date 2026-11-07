# Design: Intake and Versions

## Overview

This design adds projects, intake drafts, immutable versions, parameter editing,
and version history on top of the foundation repository layer, plus the three
screens that use them: Projects, Projects (Empty State), and Intake. It realizes
`requirements.md` and follows the steering files.

```
web/  Projects ──► Intake form ──"Create version"──► (Architecture stage, later spec)
        │               │ autosave
        ▼               ▼
api/  /api/projects   /api/projects/{id}/intake   /api/projects/{id}/versions
                         │                           │
                    intake_drafts (mutable)     project_versions (immutable)
                                                     ▲
                    template schema (startup-template) validates parameters
```

## Data

Tables come from `foundation`. This spec uses them as follows.

- `projects`: `id, partner_id, name, customer_name, region, created_by,
  created_at, updated_at`. The Technical Design lists `name, created_by,
  created_at`; this spec adds `customer_name`, `region`, and `updated_at` through
  a migration. Region lives on the project because every version of a project
  targets one region.
- `intake_drafts`: one row per project. `intake_json`, `updated_at`,
  `updated_by`.
- `project_versions`: `id, partner_id, project_id, number, template_version_id,
  intake_json, parameters_json, source_version_id, created_by, created_at`. This
  spec adds `source_version_id` (nullable; set when a version is made by editing
  parameters) and a `unique(project_id, number)` constraint.
- `idempotency_keys` (new): `partner_id, key, route, request_hash, response_json,
  created_at`, unique on `(partner_id, key, route)`, with a TTL cleanup. Writes
  look up the key first; a matching key with a different request hash returns 422.

### Version numbering under concurrency

Version creation runs in a transaction that locks the project row
(`SELECT ... FOR UPDATE`), reads `max(number)`, and inserts `max + 1`. The unique
constraint is a second guard: a conflict retries once (Requirement 4.5).

## Intake schema

One schema definition, written as a Pydantic model in `api/` and exported as JSON
Schema. The web app generates its form validation from that export, so the API
and the UI validate identically (Requirement 2.4).

| Field | Type | Rule | Required |
| --- | --- | --- | --- |
| `workload_type` | enum | `saas_web_app_api`, `customer_portal_spa_backend`, `internal_tool`, `mobile_app_backend` | yes |
| `region` | enum | supported launch regions (see below) | yes |
| `expected_users` | integer | 1 – 1,000,000 | yes |
| `requests_per_day` | integer | 0 – 1,000,000,000 | yes |
| `peak_multiplier` | number | 1.0 – 20.0 | yes |
| `availability_target` | enum | `99.5`, `99.9` | yes |
| `data_sensitivity` | enum | `public`, `internal`, `confidential` | yes |
| `budget_ceiling_usd` | number | 1 – 1,000,000 per month | yes |
| `notes` | string | max 4,000 chars, plain text | no |

Eight required fields; the form shows "N of 8 required fields complete".

**Supported launch regions.** The PRD leaves the launch region list open. This
design uses `us-east-1`, `us-west-2`, and `eu-west-1`, matching the corrected
Projects screen. The list is a single config value, so changing it is a one-line
change. It must be confirmed before pilot (see open questions).

The intake region is copied from the project's region and is read-only in the
form. Changing the region means a new project, because the estimate, the
template's AZ names, and the sandbox target all depend on it.

**Notes handling.** Notes are stored in `intake_json`, excluded from logs by the
foundation redaction filter (the field name `notes` is on the deny list), never
passed to the renderer as anything but an opaque string, and never used in names
(Requirement 2.7). Bedrock guardrails apply when the agent reads them (later spec).

## Parameter suggestions

A pure function `suggest_parameters(intake, template_version) -> parameters`
starts from the schema defaults and applies rules in a fixed order:

1. `availability_target == 99.9` → `network.az_count = 2`; `99.5` → `1`.
2. `data_sensitivity == confidential` → no parameter change (encryption is always
   on in the template); recorded for the README only.
3. Traffic: from `requests_per_day × peak_multiplier`, pick `compute.min_tasks`
   and `compute.max_tasks` from a fixed table, clamped to schema bounds.

The function has no I/O and no randomness, so the same intake always yields the
same parameters (Requirement 3.3). The intake form shows suggestion 1 inline
(the AZ suggestion with Accept and Dismiss); a dismissed suggestion is stored in
the draft as `dismissed_suggestions` and the version keeps the consultant's
choice (Requirement 3.4).

## Parameter validation and editing

- The parameter validator from `startup-template` is loaded per template version,
  so a version is always checked against the schema it was created with.
- `PUT /api/projects/{id}/versions/{vid}/parameters` takes the full parameter set,
  validates all of it, and on success creates a new version with
  `source_version_id = vid`. It returns the new version and a `changed` list of
  `{parameter, from, to}`. It never edits `vid` (Requirement 5.3).
- Unknown parameters are rejected (Requirement 5.5).
- The Architecture-stage UI (later spec) batches edits and calls this once per
  "Apply changes", so a version is not created per keystroke.

## Template version selection

When a version is cut, the API picks the newest `template_versions` row for
`startup` whose status is allowed in the current environment: `published` in
pilot and prod, `published` or `draft` in dev. This lets development proceed
before the expert review publishes `1.0.0`, without letting a draft template reach
a pilot customer (Requirement 4.3). A parameter edit keeps the source version's
template version.

## Status derivation

One module, `version_status`, computes status from stored facts:

- `draft`: no validation run passed for the version.
- `validated`: all four validators passed and diagram parity passed (facts from
  later specs; until those exist, versions read as `draft`).
- `sandbox_applied`: a succeeded apply deployment exists for the version.

Project status is the latest version's status, or `needs_regeneration` when the
latest version is newer than the latest validated version and differs from it in
parameters. Later specs add facts to this module; callers never compute status
themselves (Requirement 7.3).

## API

All under `/api`, partner-scoped through the repository layer, all writes accept
`Idempotency-Key`.

| Method and path | Purpose |
| --- | --- |
| `POST /projects` | Create a project (name, customer name, region) |
| `GET /projects?status=&owner=` | List projects with derived status |
| `GET /projects/{id}` | Project detail and latest version summary |
| `GET /projects/{id}/intake` | Read the intake draft |
| `PUT /projects/{id}/intake` | Save the draft (partial allowed; validates provided fields) |
| `POST /projects/{id}/versions` | Cut a version from a complete, valid draft |
| `GET /projects/{id}/versions` | Version history, newest first |
| `GET /projects/{id}/versions/{vid}` | One version as stored |
| `GET /projects/{id}/versions/compare?a=&b=` | Field-level diff of two versions |
| `PUT /projects/{id}/versions/{vid}/parameters` | Create a new version with edited parameters |
| `GET /templates/startup/current/schema` | The parameter schema the UI should use |

Saving the draft accepts partial input so autosave works mid-form; cutting a
version requires the full intake to validate.

Audit rows are written for project creation and every version creation
(Requirement 8.2).

## Web

Screens, regenerated in Stitch for this spec (IDs recorded in tasks):

- **Projects:** count cards, status and owner filters, table of projects. Sidebar
  has Projects and Settings only; stage navigation appears inside a project.
- **Projects (Empty State):** one "New project" action, the eight-stage explainer,
  and the New project dialog (name, customer, region, read-only template).
- **Intake:** stage 1 of 8, six section cards (Workload, Traffic, Availability,
  Data & security, Budget, Notes), required-field progress, autosave indicator,
  inline AZ suggestion, "Save draft" and "Create version and continue". The
  assistant panel is shown but can be collapsed or hidden when the agent is
  disabled.
- **Version history and compare:** already generated as a new screen; this spec
  wires it to the history and compare APIs.

Client state uses TanStack Query for server data; form state uses React Hook Form
with a resolver generated from the intake JSON Schema. Autosave debounces at 1.5
seconds and on blur.

## Testing

- Intake schema: each field's bounds and enum values; API and web share the
  exported schema (a test fails if they diverge).
- Suggestions: table of intakes to expected parameters; determinism on repeat.
- Versions: numbering, immutability (the foundation triggers), idempotent retry,
  concurrent creation yields unique sequential numbers.
- Parameters: valid change creates a new version and leaves the source untouched;
  out-of-bounds and unknown parameters rejected with named messages.
- Compare: diffs of intake and parameters.
- Status derivation: draft, needs regeneration, and the hooks later specs extend.
- Isolation: every new endpoint added to the table-driven suite.
- Web: required-field gating, autosave, suggestion accept/dismiss, empty state,
  filters, and accessibility checks on the form.

## Open questions

1. **Launch regions.** Confirm `us-east-1`, `us-west-2`, `eu-west-1` (PRD open
   question).
2. **Traffic-to-task table.** The thresholds that map requests to min/max tasks
   need an owner; the defaults here are placeholders for the AWS reviewer.
3. **Customer name.** Adding `customer_name` to `projects` extends the Technical
   Design data model. Confirm.
