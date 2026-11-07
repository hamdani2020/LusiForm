# Implementation Plan: Diagram

Tasks build in order. Each cites the requirements it satisfies (see
`requirements.md`) and follows `design.md`. Depends on `generation-pipeline` and
`validation-and-packaging`.

## Design references (Stitch project `18075726235522465175`)

Verified on regeneration or download: required content present, out-of-scope
content absent.

| Screen | Screen ID |
| --- | --- |
| Diagram Stage - Full Screen Architecture Canvas | `ed7da0bdba8a457294ee493720857e4e` |
| Architecture Stage - Parity Mismatch | `a324f5107bde4eafb599678f90265474` |
| Architecture Stage - Rendering | `c4e13203e5fd40d3843dfff4ab246042` |
| Architecture Canvas (Dark Mode) | `c97b466959cd4c73bd0c2f64832b3dc4` (only if dark mode stays in scope) |

Copy corrections to apply when building:

- Diagram screen footer "Status: AST in sync" → remove; the status chips already
  say "Diagram valid" and "Parity passed".
- Diagram screen band label "Monitoring & Security Governance" → "Monitoring".

Superseded screens (safe to delete in Stitch during cleanup):
`df531f5000c64888b3f1aa84850430cb` (old Diagram Full Screen),
`527f4cb78daf4637b9a7fdcf02669e24` (old Parity Mismatch).

- [ ] 1. Extend the schema
  - [ ] 1.1 Add diagram columns
    - `diagram` job kind; `mismatches_json`, `diagram_job_id`, and file hashes on
      `diagram_artifacts`.
    - _Requirements: 1.1, 3.4, 4.4_

- [ ] 2. Build the layout engine
  - [ ] 2.1 Implement the fixed layout
    - Region, edge band, VPC with one column per AZ and three subnet rows,
      monitoring band; fixed type order within subnets; sizes from a fixed table;
      integer coordinates on a 10-pixel grid; orthogonal edges with fixed
      waypoints.
    - _Requirements: 2.1, 2.3_
  - [ ] 2.2 Write layout tests
    - Golden layout per template fixture; both `az_count` values; every node inside
      its group.
    - _Requirements: 2.1, 2.3_

- [ ] 3. Build the writers
  - [ ] 3.1 Approved icon set
    - `icons.json` mapping node types and group kinds to draw.io AWS shapes and
      bundled SVG icons. Confirm the exact shape names against the bundled draw.io
      library and confirm the icon licence terms.
    - _Requirements: 2.4_
  - [ ] 3.2 draw.io writer
    - Uncompressed `mxfile`; ids derived from graph ids; `lusiform_node_id`,
      `tf_address`, `layer` attributes; fixed attribute order; no timestamps or host
      strings.
    - _Requirements: 1.3, 2.2, 2.5_
  - [ ] 3.3 SVG writer
    - Same layout, bundled icons, `data-node-id` and `data-layer` on each node, no
      scripts or external references.
    - _Requirements: 1.3, 2.2, NFR 2_
  - [ ] 3.4 Write writer tests
    - Byte-identical output across runs; no timestamps, account IDs, or notes; SVG
      has no scripts or external references.
    - _Requirements: 2.2, 2.5_

- [ ] 4. Build diagram validation
  - [ ] 4.1 Implement the checks
    - `defusedxml` parse, model structure, edges reference existing vertices,
      styles in the approved set.
    - _Requirements: 3.1, 3.2, 3.3_
  - [ ] 4.2 Write validation tests
    - Malformed XML, dangling edge, unapproved shape, and entity expansion all fail;
      the template fixtures pass.
    - _Requirements: 3.1, 3.2, 3.3_

- [ ] 5. Build the parity check
  - [ ] 5.1 Parse the rendered Terraform
    - `python-hcl2` per module; module-qualified block addresses; references
      resolved through the root module wiring.
    - _Requirements: 4.1, 4.3_
  - [ ] 5.2 Expected instance counts
    - Add count expressions for counted blocks to the template inventory and
      evaluate them against the version's parameters.
    - _Requirements: 4.2_
  - [ ] 5.3 Implement the five mismatch types
    - Missing in diagram, extra in diagram, count mismatch, edge without reference,
      dangling edge; pass only with zero mismatches.
    - _Requirements: 4.1, 4.2, 4.3, 4.4_
  - [ ] 5.4 Write parity tests
    - A crafted fixture for each mismatch type; all template fixtures pass with
      zero mismatches.
    - _Requirements: 4.1 to 4.4, NFR 3_

- [ ] 6. Wire the diagram job
  - [ ] 6.1 Enqueue and request
    - `on_generation_succeeded` enqueues a diagram job; `POST .../diagram` returns
      an existing job unless the last failed.
    - _Requirements: 1.1, 1.2_
  - [ ] 6.2 Worker handler
    - Load the graph and rendered files, lay out, write both files, validate, check
      parity, upload, and publish the result.
    - _Requirements: 1.3, 1.4, 3.4, 4.4_
  - [ ] 6.3 Result consumer
    - Store `diagram_artifacts`, report parity to the status module, re-evaluate
      the export gate, and insert the package job when the Terraform gate has also
      passed; write audit rows.
    - _Requirements: 4.5, 4.6, 7.3_
  - [ ] 6.4 Write job tests
    - Diagram and validate results in either order trigger exactly one package job;
      failed parity blocks packaging.
    - _Requirements: 4.5, 4.6_

- [ ] 7. Build the diagram API and agent functions
  - [ ] 7.1 Endpoints
    - Status and results, and presigned `.drawio` and SVG downloads that require
      validation and parity to pass.
    - _Requirements: 5.4, 7.2_
  - [ ] 7.2 Agent functions
    - `build_architecture_model`, `render_drawio`, `get_diagram_validation` with
      Pydantic inputs, request context, and call logging; no XML or layout input.
    - _Requirements: 6.1, 6.2, 6.3_
  - [ ] 7.3 Extend the isolation suite
    - Register every new endpoint and function.
    - _Requirements: 7.1_

- [ ] 8. Build the Diagram stage
  - [ ] 8.1 Canvas and inspector
    - Build from screen `ed7da0bd...`: sanitized inline SVG, zoom and fit, layer
      filter, inspector with Terraform address, attributes, connections, and a link
      to the Files view, status chips, downloads, and the copy corrections above.
    - _Requirements: 5.1, 5.2, 5.3, 5.4_
  - [ ] 8.2 Parity mismatch state
    - Build from screen `a324f510...`: banner, mismatch table, highlighted missing
      node, disabled downloads, "Regenerate" only.
    - _Requirements: 4.7, 5.3_
  - [ ] 8.3 Rendering state and Architecture canvas
    - Progress overlay from screen `c4e13203...` while a job runs; fill the
      Architecture stage canvas slot with the same preview.
    - _Requirements: 5.5, 5.6_
  - [ ] 8.4 Web tests
    - Layer filter, inspector content, mismatch view shows only "Regenerate",
      downloads disabled when blocked.
    - _Requirements: 4.7, 5.1 to 5.4_

- [ ] 9. Final verification
  - [ ] 9.1 Run the full suite and the timing check
    - All tests pass; a diagram job finishes in under 10 seconds; parity passes on
      every template fixture.
    - _Requirements: all, NFR 1, NFR 3_
  - [ ] 9.2 Confirm the acceptance criteria
    - Walk requirements 1 to 7 and note which test or artifact proves each.
    - _Requirements: all_
