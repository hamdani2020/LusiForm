# Implementation Plan: Generation Pipeline

Tasks build in order. Each cites the requirements it satisfies (see
`requirements.md`) and follows `design.md`. Depends on `foundation`,
`startup-template`, and `intake-and-versions`.

## Design references (Stitch project `18075726235522465175`)

Verified on regeneration: required content present, out-of-scope content absent.

| Screen | Screen ID |
| --- | --- |
| Architecture Stage - Default | `a626b2e6f3194136b4f3475f74f0e61e` |
| Architecture Stage - Stale State | `cc300bf685c949fabcb063054ef44a8d` |
| Estimate Stage - Cost Estimation | `a2ad67bf180849b18bde1673662c7e6f` |

Copy correction to apply when building: the Stale State footer reads "2 parameter
mutations uncommitted"; build it as "2 unapplied changes". Lusiform uses no git
terms.

Sample estimate figures on the Estimate screen are illustrative; real figures come
from the estimate service.

Superseded screens (safe to delete in Stitch during cleanup):
`9797dd39d54249acabd45465fb055204` (old Architecture Default),
`00ae7677973e4f178a183bbe3f21b80f` (old Stale State),
`358795662daf4a87b83b012caec8063d` (old Estimate).

- [ ] 1. Extend the schema
  - [ ] 1.1 Add the new tables
    - `outbox` (job publication), `assumption_defaults` (nullable `partner_id`,
      seeded with one platform default), and `price_cache` (platform-global).
    - _Requirements: 1.1, 5.7, 6.1_
  - [ ] 1.2 Write migration tests
    - Round trip; the platform default row exists; `price_cache` has no
      `partner_id`.
    - _Requirements: 5.7, 6.1_

- [ ] 2. Build the architecture graph
  - [ ] 2.1 Define the graph model and canonical serializer
    - Groups, nodes, edges, hidden resources, and module inputs as in
      `design.md`; sorted keys and arrays, no timestamps, SHA-256 of the bytes.
    - _Requirements: 2.2, 2.4_
  - [ ] 2.2 Implement the graph builder
    - A pure function of the template inventory and parameters; `az_count`
      controls NAT and standby nodes; one node per Terraform resource address;
      supporting resources listed in `hidden`.
    - _Requirements: 2.1, 2.3_
  - [ ] 2.3 Write graph tests
    - Output per template fixture; one node per address with no extras; both
      `az_count` variants; identical bytes across runs.
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

- [ ] 3. Build the renderer
  - [ ] 3.1 Implement `render(graph, template_dir)`
    - Jinja2 with strict undefined, no time, environment, or randomness; module
      inputs read from the graph; variables and tfvars example written; README
      with escaped project and customer names and no notes.
    - _Requirements: 3.1, 3.2, 3.4_
  - [ ] 3.2 Write the manifest
    - Template version, parameters, graph hash, and sorted file hashes.
    - _Requirements: 3.2, 3.3_
  - [ ] 3.3 Write renderer tests
    - Byte-equality with the `startup-template` golden fixtures (replacing its
      test-only helper); no timestamps; no notes; credential and account-ID scan.
    - _Requirements: 3.3, 3.4, 3.5_

- [ ] 4. Build generation jobs
  - [ ] 4.1 Enqueue with a transactional outbox
    - Version creation inserts a `queued` job and an outbox row in one
      transaction; an outbox publisher sends to SQS after commit.
    - _Requirements: 1.1_
  - [ ] 4.2 Generation request endpoint
    - `POST .../generate` returns an existing queued, running, or succeeded job,
      and creates a new one only after a failure. `GET /jobs/{id}` returns status
      and a safe error.
    - _Requirements: 1.2, 1.3_
  - [ ] 4.3 Worker handler
    - Load the bundled template version, build the graph, render, upload to the
      partner and version prefix, and publish started, succeeded, or failed
      results. Payload carries no notes or secrets.
    - _Requirements: 1.4, 1.6, 3.6_
  - [ ] 4.4 Retries and dead-letter queue
    - Three attempts with backoff for transient errors; then dead-letter and a
      failed result. Deterministic errors fail at once.
    - _Requirements: 1.5_
  - [ ] 4.5 Result consumer in the API
    - Idempotent by job id; updates the job, inserts `architecture_graphs` and
      `artifacts`, writes audit rows, and calls `on_generation_succeeded` (the
      validation hook, a no-op until that spec).
    - _Requirements: 1.6, 3.6, 3.7, 8.3_
  - [ ] 4.6 Write job tests
    - Outbox delivery after a simulated crash; duplicate request; retry then
      dead-letter; redelivered result is harmless; payload contains no notes.
    - _Requirements: 1.1, 1.2, 1.4, 1.5_

- [ ] 5. Build the estimate service
  - [ ] 5.1 Write `pricing-map.json` and the quantity formulas
    - One entry per pricing hint with Pricing API filters and a quantity
      function; Multi-AZ SKUs when `az_count = 2`.
    - _Requirements: 5.1, 5.2_
  - [ ] 5.2 Implement the price cache and Pricing API client
    - 24-hour TTL per region, service code, and filter; stale fallback with age
      shown; error naming a never-cached price; task role limited to
      `pricing:GetProducts`.
    - _Requirements: 6.1, 6.2, 6.3_
  - [ ] 5.3 Compute and store estimates
    - Line items, decimal totals, annual = 12 × monthly, budget percentage,
      snapshot time, and the basis statement.
    - _Requirements: 5.2, 5.3, 5.4, 5.6_
  - [ ] 5.4 Assumptions and defaults
    - First set copies the partner default, else the platform default; each edit
      inserts a new set and estimate and never touches artifacts.
    - _Requirements: 5.5, 5.7_
  - [ ] 5.5 Write estimate tests
    - Formulas, Multi-AZ SKUs, decimal math, budget percentage, defaults
      precedence, Terraform unchanged after an assumption edit, cache hit, miss,
      expiry, and Pricing API failure with and without a cached price.
    - _Requirements: 5.1 to 5.7, 6.1 to 6.3_

- [ ] 6. Build the estimate and graph API
  - [ ] 6.1 Endpoints
    - `GET .../graph`, `GET .../estimate`, `PUT .../assumptions`, `POST
      .../estimate/refresh`, `GET .../estimate.csv`, all partner-scoped with
      idempotent writes.
    - _Requirements: 5.1, 5.5, 6.4, 7.1, 8.1, 8.2_
  - [ ] 6.2 CSV export
    - Columns, header rows (version, region, snapshot, assumptions), footer
      totals, and formula-injection neutralization.
    - _Requirements: 7.1, 7.2, 7.3_
  - [ ] 6.3 Extend the isolation suite
    - Register every new endpoint; assert artifacts and estimates are unreadable
      across partners.
    - _Requirements: 8.1, 8.2_

- [ ] 7. Build the Architecture stage
  - [ ] 7.1 Parameter form
    - Build from screen `a626b2e6...`: options and bounds from the schema
      endpoint, inline bound errors, "Regenerate" disabled while invalid, diagram
      canvas slot for the diagram spec.
    - _Requirements: 4.1, 4.4, 4.5_
  - [ ] 7.2 Stale state and regenerate flow
    - Build from screen `cc300bf6...`: changed fields with old and new values,
      per-field undo, "Revert changes", "Regenerate" calling the parameter API,
      and job progress by polling `GET /jobs/{id}`.
    - _Requirements: 4.2, 4.3_

- [ ] 8. Build the Estimate stage
  - [ ] 8.1 Estimate screen
    - Build from screen `a2ad67bf...`: summary cards with budget use, snapshot
      card with "Refresh prices", line-item table, basis note, assumptions panel
      with "Save assumptions", and "Export CSV".
    - _Requirements: 5.2, 5.3, 5.4, 5.5, 5.6, 6.4, 7.1_
  - [ ] 8.2 Web tests
    - Regenerate flow, stale marking, assumption save creates a new estimate,
      refresh, CSV download, and errors for a missing price.
    - _Requirements: 4.2, 4.3, 5.5, 6.3, 6.4_

- [ ] 9. Observability
  - [ ] 9.1 Metrics
    - Job duration and failure rate, Pricing API calls, and cache hit rate.
    - _Requirements: 8.4_

- [ ] 10. Final verification
  - [ ] 10.1 Run the full suite and the performance checks
    - All tests pass; graph build and render under 5 seconds; warm-cache
      assumption edit under 3 seconds.
    - _Requirements: all, NFR 1, NFR 2_
  - [ ] 10.2 Prepare the estimate accuracy check
    - A harness that runs the pilot scenarios and compares totals with the
      consultants' manual estimates once baselines exist (±15% on 3 of 4).
    - _Requirements: NFR 3_
  - [ ] 10.3 Confirm the acceptance criteria
    - Walk requirements 1 to 8 and note which test or artifact proves each.
    - _Requirements: all_
