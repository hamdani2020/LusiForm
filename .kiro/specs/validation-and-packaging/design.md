# Design: Validation and Packaging

## Overview

```
generation succeeded ─► on_generation_succeeded ─► validate job ─► SQS jobs
                                                                     │
                     validator worker (no network, pinned tools) ◄───┘
                       fmt ▸ init+validate ▸ tflint ▸ checkov
                       report.json ─► S3 ;  results ─► SQS results ─► API consumer
                                                                         │
                       validation_runs, validation_findings, gate status ◄┘
                                                                         │
                            export gate passes ─► package job ─► base zip ─► S3
```

It realizes `requirements.md` and follows the steering files.

## Jobs

`generation_jobs` gains a `kind` column (`generate`, `validate`, `package`) so all
pipeline work shares one job table, one status model, and `GET /jobs/{id}`.
`on_generation_succeeded(version)` inserts a `validate` job through the outbox
(Requirement 1.1). When validation records a passing Terraform gate, and diagram
parity has passed, the consumer inserts a `package` job.

## Validator worker

A separate ECS task definition, not the generation worker, so validator binaries
stay out of the generation path and get their own role.

### Image

- Pinned Terraform, AWS provider, tflint with the AWS ruleset plugin, and Checkov,
  all at the versions recorded in the template's `template.json`.
- The AWS provider is in a filesystem mirror inside the image, and the CLI config
  points `terraform init` at it, so init needs no network. This answers the
  Technical Design open question about provider downloads in workers.
- The tflint plugin is installed in the image (`TFLINT_PLUGIN_DIR`); tflint does
  not download at run time.
- Checkov runs with `--skip-download` and no API key, so it never contacts an
  external service.

### Network and role

- The task runs in subnets with no internet or NAT route and a security group with
  no egress except the VPC endpoints for S3 and SQS (Requirement 1.3).
- The task role can read the version's `terraform/` prefix, write the report under
  the version prefix, and use the job and results queues. Nothing else.

### Run

1. Download the rendered project to a temporary directory; check each file's hash
   against the manifest and fail if any differs.
2. Run the four validators. `fmt -check` and Checkov run on the files directly;
   `init -backend=false` then `validate` runs in the project; tflint runs with
   `--call-module-type=local`. They run concurrently where they don't share state
   (fmt, Checkov, and tflint in parallel with init plus validate), but results are
   always reported in the fixed order.
3. Each validator has a timeout (fmt 10s, validate 30s, tflint 20s, Checkov 30s).
   A timeout or crash records that validator as `errored` (Requirement 1.5).
4. Parse output into one finding format: `tool, rule_id, severity, message, file,
   line`. Paths are relative to the project root.
5. Apply the severity map to Checkov findings.
6. Write `validation-report.json` (tool versions, per-tool results, findings) and
   publish a result message with the summary.

## Severity

- `checkov-severity.json` lives with the validator service, keyed by the pinned
  Checkov version: `{ "checkov": "<version>", "checks": { "CKV_AWS_...": "HIGH" } }`.
- As far as I know, open-source Checkov leaves severity empty without a platform
  API key, so Lusiform owns this map (carried from the template spec's open
  question). Verify against the pinned version when building.
- A failing check missing from the map is treated as `HIGH` (Requirement 3.3). A CI
  test lists every Terraform check in the pinned Checkov version and fails if any
  is unmapped, so fail-closed rarely triggers in practice.
- Mapping rules: encryption, public exposure, and wildcard IAM checks are `HIGH`;
  logging and retention checks are `LOW` or `MEDIUM`. The first version is reviewed
  with the template by the AWS expert.

tflint: findings at `error` level block; `warning` and `notice` do not.

## Terraform gate

A pure function of the four results:

```
gate = fmt.exit == 0
   and validate.exit == 0
   and tflint.errors == 0
   and checkov.high == 0
   and no validator errored
```

It's stored on the version's latest validation result and read by the status
module. The status module reports `validated` only when this gate passes and the
diagram spec reports parity passed (Requirement 7.1). Until the diagram spec
exists, parity reads as pending, so no version is `validated` or downloadable yet,
which is the safe default.

There is no endpoint, flag, or role that overrides a failing gate (Requirement
3.4). Findings cannot be ignored or suppressed in the platform. Because the
consultant cannot edit generated code, a blocking finding means either a parameter
choice caused it (change the parameter and regenerate) or the template has a
defect (a platform operator fixes it in a new template version). The blocked view
says which, based on whether the failing file is in a module that the changed
parameters touch.

## Data

- `validation_runs` (from foundation): one row per tool per version, with
  `tool_version`, `exit_code`, `severity_counts_json`, `summary`, plus a
  `status` column (`passed`, `failed`, `errored`) and a `validation_job_id`.
- `validation_findings` (new, append-only): `partner_id, version_id, run_id, tool,
  rule_id, severity, message, file, line`.
- A version's results are those of its latest validation job; earlier jobs stay
  as history.

## Files view API

- `GET /api/projects/{id}/versions/{vid}/files` returns the tree from the manifest.
- `GET /api/projects/{id}/versions/{vid}/files/{path}` returns one file. The path
  must exactly match a manifest entry; anything else returns 404, so there is no
  path traversal (Requirement 4.3).
- Both are read-only. There is no write endpoint for files (Requirement 4.4).

## Packaging

### Base package

- Built by the `package` job in the generation worker (it already has read access
  to the version prefix).
- Contents: `terraform/` (the rendered project), `manifest.json`,
  `validation-report.json`.
- Deterministic zip: entries sorted by path, every entry's timestamp fixed to
  1980-01-01, fixed permissions, deflate at a fixed level, no extra fields.
  Recorded in `artifacts` with kind `package_base` and its SHA-256 (Requirement
  5.2).
- Name: `<project-slug>-v<number>.zip`, where the slug is derived from the project
  id and number only, not from typed names, so no user text reaches a file name.

### Full package

- Built on request by the API from the base package plus `architecture-v<n>.drawio`,
  `architecture-v<n>.svg`, and `estimate-v<n>-e<estimate_number>.csv` for the
  estimate the consultant is viewing (Requirement 5.3).
- Cached as an artifact keyed by version, estimate id, and diagram artifact id, so
  repeat downloads reuse it.

### Download

- `GET /api/projects/{id}/versions/{vid}/download?package=base|full&estimate=<id>`
  checks the partner (repository layer) and the export gate, then returns a
  presigned S3 URL valid for 5 minutes (Requirement 5.4, 5.5).
- Every issued URL writes an audit row with the package kind and hash
  (Requirement 5.6).

## Web

Screens regenerated for this spec (IDs in tasks):

- **Terraform Stage - Files Tab:** file tree, read-only code viewer with line
  numbers, versions and manifest hash, "Download project (.zip)" when the export
  gate passes.
- **Terraform Stage - Validation Tab:** four validator cards, totals, filterable
  findings table with file and line links, report download.
- **Terraform Stage - Blocked State:** blocking banner, the failing check, the
  reason, what to do, and disabled continue and download actions. No bypass,
  ignore, or quick-fix actions.
- **Handoff Stage:** package contents, summary of gate, parity, sandbox, and
  estimate, and "Download full package (.zip)".

## Testing

- Severity: mapped and unmapped checks; the CI coverage test over every check in
  the pinned Checkov version.
- Gate: truth table over the four results, including errored validators.
- Worker: known-good fixture passes; insecure fixture fails Checkov high; a
  tampered file fails the manifest check; timeouts record `errored`; the task has
  no network (a test that a fetch fails).
- Files API: manifest paths only; traversal attempts return 404.
- Packaging: byte-identical base zip across builds; full package names its
  estimate; no user text in file names.
- Download: refused when the gate fails or parity is pending; URL expiry; audit
  row written; cross-partner access returns 404.
- Isolation: all new endpoints registered.

## Open questions

1. **Initial severity map.** Owner and review of the first map, done with the
   template review.
2. **Gate before the diagram spec ships.** With parity pending, nothing is
   downloadable. If you want downloads earlier for internal testing, a dev-only
   setting could treat parity as passed. Default: no such setting.
