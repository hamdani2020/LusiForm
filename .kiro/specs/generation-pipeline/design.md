# Design: Generation Pipeline

## Overview

```
version created ──► API enqueues job ──► SQS jobs ──► worker: build graph ─► render ─► S3
                                                          │                          │
                                                          └──► SQS results ──► API result consumer
                                                                                │
                                         records architecture_graphs, artifacts, job status
                                         and calls the validation hook (validation spec)

Estimate stage ──► API estimate service ──► graph (S3) + assumption set + price cache
                                                                  │ miss
                                                                  ▼
                                                           AWS Pricing API
```

It realizes `requirements.md` and follows the steering files. The worker keeps
the foundation boundary: it reads the job queue and the artifact bucket and
writes results to a results queue. Only the API writes to the tenant database.

## Generation jobs

### Enqueue

- Creating a version (intake cut or parameter edit) inserts a `generation_jobs`
  row with status `queued` in the same transaction, then publishes the job to SQS
  after commit (transactional outbox: a small `outbox` table polled by the API,
  so a crash between commit and publish never loses a job).
- `POST /api/projects/{id}/versions/{vid}/generate` returns the existing job if
  one is queued, running, or succeeded; it creates a new job only when the last
  one failed (Requirement 1.2).

### Payload

```json
{
  "job_id": "uuid", "partner_id": "uuid", "project_id": "uuid",
  "version_id": "uuid", "version_number": 3,
  "template": "startup", "template_version": "1.0.0",
  "region": "us-east-1",
  "parameters": { "...": "..." }
}
```

No intake notes, no names typed by the consultant, no secrets (Requirement 1.4).
The README needs the project name and customer name; the worker receives them as
display values only, they are escaped for Markdown, and they are never used in
file paths or resource names.

### Worker handler

1. Mark running (publishes a `started` result).
2. Load the template version from the worker image's bundled templates
   (templates ship in the image, pinned by version, so the worker needs no
   network to fetch them).
3. Build the graph, render the project, compute the manifest.
4. Upload to `s3://<artifacts>/<partner_id>/<project_id>/v<number>/` under
   `graph.json`, `terraform/…`, `manifest.json`.
5. Publish a `succeeded` result with keys and hashes, or `failed` with a safe
   error code and message.

Transient errors (S3 throttling) retry with backoff up to three attempts; after
that the message goes to a dead-letter queue and a `failed` result is published
(Requirement 1.5). Deterministic errors (schema mismatch) fail immediately.

### Result consumer

An API-side consumer reads the results queue and, through the repository layer,
updates `generation_jobs`, inserts `architecture_graphs` and `artifacts`, writes
audit rows, and calls `on_generation_succeeded(version)`, the hook the validation
spec implements (Requirement 3.7). Results are idempotent by `job_id` so a
redelivered message is harmless.

## Architecture graph

### Model

```json
{
  "schema": "lusiform.graph/1",
  "template_version": "1.0.0",
  "region": "us-east-1",
  "groups": [
    { "id": "region", "kind": "region", "parent": null },
    { "id": "vpc", "kind": "vpc", "parent": "region" },
    { "id": "az-a", "kind": "az", "parent": "vpc" },
    { "id": "subnet-public-a", "kind": "subnet", "tier": "public", "parent": "az-a" }
  ],
  "nodes": [
    {
      "id": "alb",
      "type": "load_balancer",
      "layer": "edge",
      "group": "vpc",
      "tf_address": "module.compute.aws_lb.this",
      "attributes": { "scheme": "internet-facing" }
    }
  ],
  "edges": [
    { "from": "alb", "to": "ecs-service", "kind": "traffic", "port": 80 }
  ],
  "modules": { "network": { "az_count": 2 }, "compute": { "...": "..." } }
}
```

- Node types and the Terraform resources behind them come from the template's
  `inventory.json`; the graph builder is a function of the inventory and the
  parameters only.
- `modules` carries the module inputs. The renderer reads module inputs from the
  graph, not from the raw parameters, so the graph really is the single source for
  both Terraform and the diagram (Requirement 2.1, 3.1).
- `az_count` drives which nodes exist: with 1, one NAT gateway and no RDS standby
  node; with 2, two NAT gateways and a standby node. Subnet groups always exist in
  two AZs, matching the template decision.
- One node per Terraform resource address (Requirement 2.3). Supporting resources
  that are not drawn (route table associations, KMS aliases) are listed in
  `graph.hidden` with their addresses, so parity in the diagram spec can account
  for every resource.

### Canonical serialization

Keys sorted, arrays sorted by `id`, UTF-8, `\n` line endings, no floats where an
integer fits, and no timestamps. The SHA-256 of this byte string is stored in
`architecture_graphs.sha256` (Requirement 2.4).

## Renderer

- A pure function `render(graph, template_dir) -> {path: bytes}`. Jinja2 with
  `StrictUndefined`, autoescape off for HCL, a fixed set of filters, and no access
  to time, environment, or randomness.
- Writes module source paths relative to the project. Writes parameter values into
  `variables.tf` defaults and `terraform.tfvars.example`.
- The README lists the template version, the parameters, the commands to run, and
  the project and customer names escaped for Markdown. It never contains notes.
- `manifest.json` lists the template version, parameters, graph hash, and the
  SHA-256 of every rendered file, sorted by path. The manifest is itself
  deterministic; job timestamps live in the database, not in files (Requirement
  3.3).
- Golden test: the renderer's output for each `startup-template` fixture must
  equal the stored golden output byte for byte (Requirement 3.5). This replaces
  the template spec's test-only render helper.

## Estimate service

Runs in the API (the Technical Design places estimates in the API service).

### Line items

The template inventory's pricing hints map graph nodes to billable line items. A
`pricing-map.json`, versioned with the estimate service and keyed by hint, holds
the Pricing API filters and the quantity formula for each item:

| Line item | Billing unit | Quantity from |
| --- | --- | --- |
| Fargate vCPU | vCPU-hour | task vCPU × average running tasks × runtime hours |
| Fargate memory | GB-hour | task memory × average running tasks × runtime hours |
| ALB | ALB-hour | runtime hours |
| ALB LCU | LCU-hour | derived from requests per month |
| NAT gateway | gateway-hour | NAT count × runtime hours |
| NAT data processed | GB | data transfer out assumption |
| RDS instance | instance-hour | 730, Multi-AZ SKU when `az_count = 2` |
| RDS storage | GB-month | `storage_gb` (Multi-AZ storage SKU when applicable) |
| CloudWatch logs | GB ingested | from requests and an average log size assumption |
| KMS keys | key-month | key count in the graph |
| Data transfer out | GB | data transfer out assumption |

Average running tasks is `min_tasks` unless the assumptions say otherwise. The
quantity formulas are plain functions with unit tests, so the ±15% target can be
tuned against pilot baselines.

### Assumptions

- `assumption_defaults` (new table): `partner_id` nullable (null is the platform
  default row), the assumption values, `updated_by`, `updated_at`. Seeded with one
  platform default. The admin screen to edit it is in the agent-and-admin spec.
- Fields: requests per month, database storage GB, data transfer out GB per month,
  compute runtime hours per month, average log size per request.
- A version's first `assumption_sets` row copies the partner default, else the
  platform default (Requirement 5.7). Each edit inserts a new `assumption_sets`
  row and a new `estimates` row; the version and its artifacts are untouched
  (Requirement 5.5).

### Prices and cache

- `price_cache` (new, platform-global): `region, service_code, filter_hash,
  unit_price_usd, unit, raw_sku, fetched_at`. TTL 24 hours.
- The Pricing API is called through boto3 `pricing.get_products` in a supported
  Pricing API endpoint region, with the API task role allowed `pricing:GetProducts`
  only.
- On API failure, a stale cached price is used and its age shown; if a needed
  price was never cached, the estimate fails with the missing item named
  (Requirement 6.3). "Refresh prices" bypasses the TTL and creates a new estimate.

### Estimate record

`estimates` stores `line_items_json`, `monthly_total`, `annual_total`,
`price_snapshot_at`, and the `assumption_set_id`. Money is stored as decimal
strings, never floats, and rounded to cents only for display.

## API

| Method and path | Purpose |
| --- | --- |
| `POST /projects/{id}/versions/{vid}/generate` | Request generation (returns job) |
| `GET /jobs/{id}` | Job status and safe error |
| `GET /projects/{id}/versions/{vid}/graph` | The architecture graph |
| `GET /projects/{id}/versions/{vid}/estimate` | Latest estimate for the version |
| `PUT /projects/{id}/versions/{vid}/assumptions` | New assumption set and estimate |
| `POST /projects/{id}/versions/{vid}/estimate/refresh` | Refresh prices, new estimate |
| `GET /projects/{id}/versions/{vid}/estimate.csv` | CSV export |

Writes accept `Idempotency-Key`. All are partner-scoped and added to the
isolation suite.

## CSV

Columns: service, terraform_resource, billing_unit, unit_price_usd, quantity,
monthly_usd. Header rows give version, region, snapshot time, and assumptions;
footer rows give the monthly and annual totals. Any text cell starting with `=`,
`+`, `-`, `@`, tab, or carriage return is prefixed with an apostrophe
(Requirement 7.3).

## Web

Screens regenerated for this spec (IDs in tasks):

- **Architecture Stage - Default:** parameter form (from the schema endpoint),
  diagram canvas slot, manifest hash, stage rail.
- **Architecture Stage - Stale State:** unapplied changes banner listing each
  changed parameter, "Revert" and "Regenerate", diagram and Terraform marked
  stale.
- **Estimate Stage:** totals, budget use, snapshot card with Refresh, line items,
  editable assumptions panel, Export CSV, and the basis statement.

The Rendering screen belongs to the diagram spec; the agent panels belong to the
agent-and-admin spec. Job progress polls `GET /jobs/{id}` every two seconds while
a job is active.

## Testing

- Graph: builder output per fixture; one node per resource address; az_count
  variants; canonical bytes stable across runs.
- Renderer: golden equality with the template fixtures; no timestamps; no notes;
  credential and account-ID scan.
- Jobs: outbox delivery after a simulated crash; duplicate request returns the
  existing job; retry then dead-letter; idempotent result consumer.
- Estimate: quantity formulas; Multi-AZ SKUs; totals as decimals; budget
  percentage; new assumption set leaves Terraform unchanged; defaults precedence.
- Cache: hit, miss, expired, Pricing API down with and without a cached price.
- CSV: columns, header and footer, formula-injection neutralization.
- Isolation: every endpoint registered; artifacts unreadable across partners.

## Open questions

1. **Pricing basis.** On-demand only, with no free tier, savings plans, or
   reserved pricing. Confirm.
2. **Average log size.** The CloudWatch line needs an assumed bytes-per-request;
   default 1 KB. Confirm or replace with the pilot partners' figure.
3. **Average running tasks.** Default to `min_tasks`; a utilization assumption
   could raise it. Decide before pilot tuning.
