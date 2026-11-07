# Implementation Plan: Validation and Packaging

Tasks build in order. Each cites the requirements it satisfies (see
`requirements.md`) and follows `design.md`. Depends on `foundation`,
`startup-template`, `intake-and-versions`, and `generation-pipeline`.

## Design references (Stitch project `18075726235522465175`)

Verified on regeneration: required content present, out-of-scope content absent.

| Screen | Screen ID |
| --- | --- |
| Terraform Stage - Files Tab | `671408f79a624c41a28dc530524dd927` |
| Terraform Stage - Validation Tab | `694fa021e9194b04bd6bebcd28060bac` |
| Terraform Stage - Blocked State | `bd4732a63df146639faceb742dc11210` |
| Handoff Stage - Package Delivery | `fc4882a8d55a48c386760e5803ed1772` |

Copy corrections to apply when building:

- Validation Tab eyebrow "IaC compliance & syntax" → "Validation checks".
  Lusiform makes no compliance claims.
- Validation Tab rail heading "8-Stage Delivery Graph" → the standard stage rail
  used on the other screens.

Sample findings and figures on these screens are illustrative.

Superseded screens (safe to delete in Stitch during cleanup):
`9203e993c6674fc181375f425947a9cc` (old Files Tab),
`5b072e81035648a8bfa91499ee444508` (old Validation Tab),
`747c8234075941eeba1fa2ff43c52f97` (old Blocked State),
`928b733529e74484a93ac3b668c6931f` (old Handoff),
`9128ab5ebe594dfab8b06b16adab5fa6` (Northwind Pay proposal; out of scope).

- [ ] 1. Extend the schema
  - [ ] 1.1 Add job kinds and validation columns
    - `kind` on `generation_jobs` (`generate`, `validate`, `package`);
      `status` and `validation_job_id` on `validation_runs`; new append-only
      `validation_findings` table with the foundation append-only trigger.
    - _Requirements: 1.1, 2.1, 2.2_
  - [ ] 1.2 Write migration tests
    - Round trip; findings reject UPDATE and DELETE.
    - _Requirements: 2.2_

- [ ] 2. Build the validator image
  - [ ] 2.1 Pin and bundle the tools
    - Terraform, the AWS provider in a filesystem mirror with CLI config, tflint
      with the AWS ruleset plugin preinstalled, and Checkov, all at the versions in
      the template's `template.json`.
    - _Requirements: 1.3, NFR 3_
  - [ ] 2.2 Write the severity map
    - `checkov-severity.json` for the pinned Checkov version; HIGH for encryption,
      public exposure, and wildcard IAM; LOW or MEDIUM for logging and retention.
      Confirm the severity behaviour of open-source Checkov against the pinned
      version and record the result.
    - _Requirements: 3.2_
  - [ ] 2.3 Add the severity coverage test
    - List every Terraform check in the pinned Checkov version and fail if any is
      unmapped.
    - _Requirements: 3.2, 3.3_

- [ ] 3. Build the validator worker
  - [ ] 3.1 Task definition and network
    - Separate ECS task with no internet or NAT route, egress only to the S3 and
      SQS VPC endpoints, and a role limited to the version's prefix and the queues.
    - _Requirements: 1.3_
  - [ ] 3.2 Run the four validators
    - Verify file hashes against the manifest; run fmt, init plus validate, tflint
      with local modules, and Checkov with `--skip-download`; concurrent where
      safe; per-tool timeouts; record `errored` on timeout or crash.
    - _Requirements: 1.2, 1.5_
  - [ ] 3.3 Normalize findings and write the report
    - One finding format; apply the severity map (unmapped failing checks become
      HIGH); write `validation-report.json`; publish the result.
    - _Requirements: 2.1, 2.2, 2.5, 3.2, 3.3_
  - [ ] 3.4 Write worker tests
    - Known-good fixture passes; insecure fixture fails Checkov HIGH; tampered file
      fails the manifest check; timeouts record `errored`; outbound network fetch
      fails inside the task.
    - _Requirements: 1.2, 1.3, 1.5, 3.3_

- [ ] 4. Wire validation into the pipeline
  - [ ] 4.1 Implement `on_generation_succeeded`
    - Insert a `validate` job through the outbox.
    - _Requirements: 1.1_
  - [ ] 4.2 Record results and compute the gate
    - The result consumer stores `validation_runs` and `validation_findings`,
      computes the Terraform gate, writes audit rows, and inserts a `package` job
      when the gate and diagram parity both pass.
    - _Requirements: 2.1, 2.2, 3.1, 7.3_
  - [ ] 4.3 Extend the status module
    - `validated` only when the Terraform gate passes and parity passes; parity
      reads as pending until the diagram spec supplies it.
    - _Requirements: 7.1_
  - [ ] 4.4 Write gate tests
    - Truth table over the four results, including errored validators; no
      override path in the API.
    - _Requirements: 3.1, 3.4, 3.6_

- [ ] 5. Build the files and validation API
  - [ ] 5.1 Files endpoints
    - Tree from the manifest; file content only for exact manifest paths; no write
      endpoints.
    - _Requirements: 4.1, 4.3, 4.4_
  - [ ] 5.2 Validation endpoint
    - Per-tool results, severity totals, findings, and the report download.
    - _Requirements: 2.3, 2.5_
  - [ ] 5.3 Write API tests
    - Traversal attempts return 404; results match stored runs.
    - _Requirements: 4.3, 2.3_

- [ ] 6. Build packaging and download
  - [ ] 6.1 Base package job
    - Deterministic zip (sorted entries, fixed timestamps and permissions, fixed
      compression); name from project id and version number; record the SHA-256.
    - _Requirements: 5.1, 5.2_
  - [ ] 6.2 Full package
    - Base package plus diagram files and the selected estimate's CSV, named with
      the estimate number; cached by version, estimate, and diagram artifact.
    - _Requirements: 5.3_
  - [ ] 6.3 Download endpoint
    - Check partner and export gate, then issue a presigned URL valid for 5
      minutes; refuse when the gate fails or parity is pending; audit every issued
      URL.
    - _Requirements: 5.4, 5.5, 5.6_
  - [ ] 6.4 Write packaging tests
    - Byte-identical base zip across builds; full package names its estimate; no
      user text in file names; refusal when blocked; URL expiry; audit row.
    - _Requirements: 5.2, 5.3, 5.4, 5.5, 5.6_

- [ ] 7. Extend the isolation suite
  - [ ] 7.1 Register every new endpoint
    - Files, validation, and download; cross-partner access returns 404.
    - _Requirements: 7.2_

- [ ] 8. Build the Terraform stage
  - [ ] 8.1 Files view
    - Build from screen `671408f7...`: file tree, read-only viewer with line
      numbers, versions and manifest hash, download when the gate passes.
    - _Requirements: 4.1, 4.2, 4.4_
  - [ ] 8.2 Validation view
    - Build from screen `694fa021...`: validator cards, totals, filterable
      findings, file and line links into the Files view, report download, and the
      copy corrections above.
    - _Requirements: 2.3, 2.4, 3.6_
  - [ ] 8.3 Blocked state
    - Build from screen `bd4732a6...`: blocking banner, reason and next step
      (parameter change or template fix), disabled continue and download, and no
      bypass, ignore, or quick-fix actions.
    - _Requirements: 3.4, 3.5_

- [ ] 9. Build the Handoff stage
  - [ ] 9.1 Handoff screen
    - Build from screen `fc4882a8...`: package contents with individual downloads,
      summary of gate, parity, sandbox, and estimate, and "Download full package".
      Show "not available yet" for any summary input a later spec has not supplied.
      No sharing, portals, or signing.
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

- [ ] 10. Web tests
  - [ ] 10.1 Write web tests
    - Finding links open the right file and line; blocked state disables actions;
      download refused when blocked; Handoff shows unavailable inputs honestly.
    - _Requirements: 2.4, 3.5, 5.5, 6.4_

- [ ] 11. Final verification
  - [ ] 11.1 Run the full suite and the timing check
    - All tests pass; validation of a standard project under 40 seconds; the pilot
      template shows zero HIGH Checkov findings.
    - _Requirements: all, NFR 1, NFR 2_
  - [ ] 11.2 Confirm the acceptance criteria
    - Walk requirements 1 to 7 and note which test or artifact proves each.
    - _Requirements: all_
