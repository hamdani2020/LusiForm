# Design: Diagram

## Overview

```
generation succeeded ─► diagram job ─► generation worker
                                         │ graph.json + terraform/ from S3
                                         ▼
                                  layout (fixed algorithm)
                                    ├─► drawio writer ─► architecture-v<n>.drawio
                                    └─► svg writer    ─► architecture-v<n>.svg
                                         │
                              diagram validation + parity check
                                         │
                          results ─► SQS results ─► API consumer
                                         │
                  diagram_artifacts (validation_status, parity_status)
                                         │
                    status module + export gate (validation spec)
```

It realizes `requirements.md` and follows the steering files.

## Jobs

- `generation_jobs.kind` gains `diagram`. `on_generation_succeeded` enqueues both a
  `validate` job (validation spec) and a `diagram` job (this spec) through the
  outbox (Requirement 1.1).
- `POST /api/projects/{id}/versions/{vid}/diagram` returns the existing diagram
  job unless the last one failed (Requirement 1.2). The agent's `render_drawio`
  calls the same function.
- The job runs in the generation worker, which already reads the version prefix.
- When the consumer records a diagram result, it re-evaluates the export gate: if
  the Terraform gate has also passed, it inserts the `package` job. Whichever result
  arrives second triggers packaging, so order does not matter.

## Layout

One deterministic algorithm, no force-directed or auto layout (Requirement 2.1):

- Region container fills the canvas. Inside it, an **edge band** at the top
  (internet gateway, Application Load Balancer), the **VPC** in the middle, and a
  **monitoring band** at the bottom (CloudWatch log group and alarms, KMS keys, IAM
  roles).
- Inside the VPC, one column per Availability Zone, ordered by AZ suffix (a, b).
  Each column holds three rows in fixed order: public, private application, data.
- Within a subnet, nodes are placed left to right in a fixed type order (NAT
  gateway, ECS task, RDS instance), then by node id.
- Sizes come from a fixed table per group and node type. Coordinates are integers
  on a 10-pixel grid.
- Edges are orthogonal with fixed waypoints computed from the source and target
  positions; edge labels show the port where the graph has one.

With `az_count = 1`, the second AZ column still exists (the subnets exist in the
template) but contains only its subnets, with no NAT gateway, task, or standby
node, matching the graph.

## draw.io writer

- Writes an uncompressed `mxfile` / `mxGraphModel` document so it can be diffed
  and validated.
- Cell ids are derived from graph ids (`node:<id>`, `group:<id>`,
  `edge:<from>:<to>:<kind>`), so the same graph yields the same ids.
- Each node cell carries custom attributes: `lusiform_node_id`, `tf_address`,
  `layer`. These drive parity and the inspector.
- Shape styles come from the approved icon set (below). The writer sets fixed
  attribute order and no timestamps, `modified` dates, or host strings in `mxfile`
  (Requirement 2.2).

## SVG writer

- Draws the same layout directly to SVG on the server, using the AWS architecture
  icon SVGs bundled with the worker (one per approved shape). No headless draw.io
  and no third-party service (NFR 2).
- Each node is a `<g>` with `data-node-id` and `data-layer` attributes so the web
  app can wire selection and the layer filter.
- No scripts, external references, or embedded fonts; text uses a generic font
  stack.

## Approved icon set

`icons.json` maps each graph node type to one draw.io AWS shape style and one SVG
icon file:

| Node type | draw.io shape |
| --- | --- |
| `internet_gateway` | `mxgraph.aws4.internet_gateway` |
| `load_balancer` | `mxgraph.aws4.application_load_balancer` |
| `nat_gateway` | `mxgraph.aws4.nat_gateway` |
| `ecs_service` | `mxgraph.aws4.fargate` |
| `rds_instance` | `mxgraph.aws4.rds_postgresql_instance` |
| `log_group` | `mxgraph.aws4.cloudwatch_2` |
| `kms_key` | `mxgraph.aws4.key_management_service` |
| `iam_role` | `mxgraph.aws4.role` |

Group containers use the AWS group shapes (region, VPC, availability zone, public
and private subnet). Exact style names are confirmed against the bundled draw.io
AWS library during implementation.

## Diagram validation

Run in the worker after writing (Requirement 3):

1. Parse the `.drawio` with a hardened XML parser (`defusedxml`: no external
   entities, no DTDs).
2. Check the `mxGraphModel` structure: a root cell, every cell has a unique id and a
   valid parent.
3. Every edge's `source` and `target` exist and are vertices.
4. Every vertex style is in `icons.json` or is an approved group shape.

## Parity check

Compares three sources: the diagram cells, the graph, and the rendered Terraform.

### Terraform side

- Parse the rendered HCL with `python-hcl2`. Collect resource blocks per module and
  qualify them with the module call name from the root, giving block addresses
  such as `module.network.aws_nat_gateway.this`.
- Instance counts are not available from static parsing when a block uses `count`
  or `for_each`. The template inventory therefore declares, for each counted block,
  the parameter expression that sets its count (for example NAT gateways equal
  `az_count`). The checker evaluates that against the version's parameters.
- References: for each resource block, collect the addresses referenced in its
  arguments, and resolve cross-module references through the root module's wiring
  (module output to module variable).

### Checks (Requirement 4)

| Mismatch type | Meaning |
| --- | --- |
| `missing_in_diagram` | A Terraform block is neither drawn nor listed as hidden in the graph |
| `extra_in_diagram` | A diagram node's `tf_address` has no Terraform block |
| `count_mismatch` | Drawn instances differ from the expected count for the block |
| `edge_without_reference` | A diagram edge has no reference between the two blocks |
| `dangling_edge` | Reported by validation, also counted as a parity failure |

Parity passes only with zero mismatches. Every mismatch type blocks in the MVP,
matching the Technical Design's interim rule; the PRD's open question on whether
only some types block stays open (see below).

Because the diagram and the Terraform are both rendered from one graph, a mismatch
means a renderer or template bug, not a consultant error. The UI therefore offers
only "Regenerate"; a mismatch that survives regeneration is a defect for the
platform team.

## Data

`diagram_artifacts` (from foundation): `drawio_s3_key`, `svg_s3_key`,
`validation_status`, `parity_status`, plus `mismatches_json`, `diagram_job_id`, and
`sha256` for each file, added here. Downloads and the status module read the latest
row for the version.

## API

| Method and path | Purpose |
| --- | --- |
| `POST /projects/{id}/versions/{vid}/diagram` | Request a diagram job |
| `GET /projects/{id}/versions/{vid}/diagram` | Status, validation, parity, mismatches, SVG preview URL |
| `GET /projects/{id}/versions/{vid}/diagram.drawio` | Presigned download (5 minutes) |
| `GET /projects/{id}/versions/{vid}/diagram.svg` | Presigned download (5 minutes) |

Downloads require validation and parity to pass (Requirement 5.4). All endpoints
are partner-scoped and registered in the isolation suite.

## Agent functions

Plain service functions with Pydantic input schemas, called by the agent tools in
the agent-and-admin spec:

- `build_architecture_model(project_id, version_id) -> Graph`
- `render_drawio(project_id, version_id) -> Job`
- `get_diagram_validation(project_id, version_id) -> DiagramResult`

They take the request context, so they are partner-scoped like any endpoint, and
each call is logged (Requirement 6.2). None accepts XML or layout input
(Requirement 6.3).

## Web

Screens for this spec (IDs in tasks):

- **Diagram Stage - Full Screen Architecture Canvas:** SVG preview, zoom and fit,
  layer filter, inspector drawer, validation and parity chip, downloads, "Continue
  to Estimate".
- **Architecture Stage - Parity Mismatch:** mismatch banner and list, highlighted
  node, blocked export, "Regenerate" only.
- **Architecture Stage - Rendering:** progress overlay while a generation or
  diagram job runs (already regenerated earlier).
- **Architecture Canvas (Dark Mode):** kept only if dark mode stays in scope.

The SVG is fetched through its presigned URL, sanitized with DOMPurify (SVG
profile), and inlined so `data-node-id` and `data-layer` work for selection and
filtering. The inspector reads node details from `GET .../graph` and links to the
Files view at the block's file and line, using the line index the validation spec
already builds.

## Testing

- Layout: golden layout per template fixture; `az_count` 1 and 2; integer grid.
- Writers: byte-identical `.drawio` and SVG across runs; no timestamps, hosts,
  account IDs, or notes; SVG has no scripts or external references.
- Validation: well-formed fixture passes; malformed XML, a dangling edge, and an
  unapproved shape each fail; XML entity expansion is rejected.
- Parity: each mismatch type from a crafted fixture; the real template fixtures
  pass with zero mismatches.
- Jobs: diagram and validate results in either order trigger exactly one package
  job.
- API: downloads refused on failed validation or parity; presigned expiry;
  isolation.
- Web: layer filter, inspector, mismatch view shows only "Regenerate".

## Open questions

1. **Parity strictness.** PRD open question. Default here: every mismatch type
   blocks. Confirm or name the types that should only warn.
2. **Dark mode.** The Canvas Dark screen exists. Keep dark mode as a theme for the
   whole app, or drop it from the MVP.
3. **Icon licensing.** The AWS architecture icons are published for use in
   architecture diagrams; confirm the bundling and redistribution terms before
   shipping them in the worker image and in customer files.
