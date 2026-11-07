# Implementation Plan: Sandbox Deployment

Tasks build in order. Each cites the requirements it satisfies (see
`requirements.md`) and follows `design.md`. Depends on `foundation`,
`startup-template`, `generation-pipeline`, `validation-and-packaging`, and
`diagram` (the export gate). This is the highest-risk spec: every task that touches
approval, apply, destroy, or the cross-account role must state in its change what
was verified and what was not (`security.md`).

Resolve the open questions in `design.md` before tasks 2, 3, and 5.

## Design references (Stitch project `18075726235522465175`)

Scanned after generation: required content present; lease, TTL, ephemeral,
OpenTofu, auto-approve, DynamoDB, "cryptographic", break-glass, and compliance
claims absent.

| Screen | Screen ID |
| --- | --- |
| Sandbox Stage - Plan Review | `1a38fdffe0f44a488d3fb87d0f416d8b` |
| Sandbox Stage - Apply Confirmation | `0b947ad43897462fbcc49f81df3643a4` |
| Sandbox Stage - State Drift Error | `7ce65094919341dfb3058cca8ee7b2e1` |
| Sandbox Stage - Teardown Plan Review | `7b220e81730c42ea8f8260f466a90a1e` |
| Admin - Sandbox Accounts | `f0f2a9372d214f2d94fb0c36e55702aa` |
| Sandbox Stage - Apply Progress & Outputs | htmlCode file `54df5a90ce7544219f7d6dc84f097af8`; screen ID not captured (the screen list is capped), look it up by that file in Stitch |

Copy corrections to apply when building:

- Apply Confirmation: "Cryptographically signature matched" → "Plan hash matches approval".
- State Drift: remove the "Admin-BreakGlass" actor; "Cryptographic Hash" → "Plan hash".
- Teardown Plan Review: "ephemeral environment" → "sandbox"; "Cryptographic Sign-Off"
  → "Approval".
- Plan Review and others: no teardown timer, lease, or TTL anywhere.

Superseded screens (safe to delete in Stitch during cleanup):
`2b6e503a3f354dc1a23a132b000a1f0b` (old Plan Review),
`a3ff0304d65b4b34b7349356ac8fc730` (old Apply Confirmation),
`f1be17632ecd4c898ad8cf3c6b388860` (old State Drift),
`f1846700e6b74769ae6fd3189a0de9c4` and `b70ecf270c6e46ffa955d4b636723e17`
(old Sandbox Accounts), `7ff6f2035e134aa68794b486354f7a0d` (old Apply Progress,
contains a 48-hour teardown, OpenTofu, and `-auto-approve`).

- [ ] 1. Extend the schema
  - [ ] 1.1 Alembic migration for deployment tables
    - `sandbox_accounts`: add `region`, `verified_at`, `policy_template_version`;
      unique on `partner_id`.
    - `deployment_plans`: add `kind` (`apply`, `destroy`), `plan_file_s3_key`,
      `counts_json`, `sandbox_account_id`, `terraform_version`, `created_by`; add
      `stale` status.
    - `partner_settings.approval_policy` (`any_consultant` default, `partner_admin`).
    - `plan_approvals` unique on `plan_id`; add a database trigger or revoked
      privilege so the application role cannot UPDATE or DELETE `plan_approvals` or
      change plan hash and serial columns.
    - New `plan`, `apply`, and `verify_sandbox` job kinds.
    - _Requirements: 1.1, 2.3, 2.4, 3.1, 3.3, 8.1_
  - [ ] 1.2 Repository methods
    - Partner-scoped access for all new tables; no raw queries elsewhere.
    - _Requirements: 7.2_

- [ ] 2. Sandbox onboarding
  - [ ] 2.1 External id and secret handling
    - Generate a 32-byte base64url external id, store it in Secrets Manager at
      `lusiform/<partner_id>/sandbox-external-id`, keep only the ARN.
    - _Requirements: 1.1, 1.4_
  - [ ] 2.2 Policy generation
    - Trust policy (worker roles as principal, ExternalId condition, session-name
      conditions) and permissions policy from the template's `inventory.json`.
    - _Requirements: 1.2, 1.5_
  - [ ] 2.3 Verification job
    - `sts:AssumeRole` plus `GetCallerIdentity`; confirm the returned account id
      equals the onboarded one; record `verified` or `failed` with a safe reason.
    - _Requirements: 1.3_
  - [ ] 2.4 Onboarding endpoints
    - Create, read, verify, and the one-time setup view with step-up
      re-authentication. Never log or return the external id elsewhere.
    - _Requirements: 1.1 to 1.4, 7.1_
  - [ ] 2.5 Write onboarding tests
    - Policy equals inventory; principal is the worker role, not root; wrong
      external id fails verification; wrong account fails; external id absent from
      logs and other responses.
    - _Requirements: 1.2, 1.4, 1.5, NFR 2, NFR 3_

- [ ] 3. Plan worker
  - [ ] 3.1 Plan hash
    - SHA-256 over labeled, length-prefixed parts: file manifest hash, canonical
      variables, provider lock hash, state serial, account id, region, Terraform
      version.
    - _Requirements: 2.3_
  - [ ] 3.2 Plan task and role
    - Separate ECS task and IAM role; assume the partner role with the external
      id read inside the worker; verify file hashes; `terraform init` with
      `use_lockfile = true` and the provider mirror; read the serial;
      `terraform plan -input=false -lock-timeout=60s -out=tfplan`.
    - _Requirements: 2.2, 4.3, 7.3_
  - [ ] 3.3 Plan output and scrubbing
    - Render `plan.json` and `plan.txt`, scrub values listed in
      `sensitive_values`, upload `tfplan` and both files, publish hash, serial,
      counts, and keys.
    - _Requirements: 2.2, 2.3, 2.5_
  - [ ] 3.4 Plan request and result consumer
    - `POST .../plans` enforces the export gate, a verified sandbox, and a policy
      version covering the template version; returns an existing queued plan;
      the consumer moves `queued → ready | failed` only.
    - _Requirements: 2.1, 2.4_
  - [ ] 3.5 Write plan tests
    - Every hash part changes the hash; length-prefix shifting blocked; same inputs
      give the same hash; sensitive values never in output; unvalidated version
      refused; plan immutable.
    - _Requirements: 2.1, 2.3, 2.4, 2.5_

- [ ] 4. Approval
  - [ ] 4.1 Approval endpoint
    - Verify plan is `ready` and not stale, body hash equals stored hash, caller
      may approve under the policy; approver comes from the session; insert an
      approval and an audit row. No revoke, edit, or delete route.
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 8.2_
  - [ ] 4.2 Approval policy API
    - `PUT /api/admin/approval-policy` for partner admins; audited; affects only
      future approvals.
    - _Requirements: 8.1, 8.3, 8.4_
  - [ ] 4.3 Write approval tests
    - Hash mismatch rejected; approver is the caller; one approval per plan;
      no mutation route exists; policy enforced with 403; approval does not apply.
    - _Requirements: 3.1 to 3.4, 8.1 to 8.4_

- [ ] 5. Apply worker
  - [ ] 5.1 Apply request
    - `POST /plans/{id}/apply`: requires an apply-kind, ready plan with a matching
      approval; checks the state serial; on change returns 409 `STATE_CHANGED`,
      marks the plan stale, audits; no override flag.
    - _Requirements: 4.1, 4.2, 5.2_
  - [ ] 5.2 Apply task and role
    - Separate ECS task and role. Re-check approval hash against recomputed plan
      hash and re-read the serial before `terraform apply -input=false tfplan`.
      Abort with `PLAN_MISMATCH` or `STATE_CHANGED`. Only the onboarded account is
      reachable.
    - _Requirements: 4.1 to 4.4, 7.3_
  - [ ] 5.3 Progress and outputs
    - Scrubbed status events; after completion read `terraform output -json`, drop
      sensitive outputs, store non-secret `outputs_json`.
    - _Requirements: 4.5_
  - [ ] 5.4 Deployment consumer
    - Update `deployments` `running → succeeded | failed`, store results, write
      audit rows.
    - _Requirements: 4.5, 7.1_
  - [ ] 5.5 Write apply tests
    - Refused without approval, with mismatched hash, and with changed serial; the
      worker aborts even when the API is bypassed; secret outputs never stored or
      logged; target account always equals the onboarded account.
    - _Requirements: 4.1 to 4.5, NFR 1, NFR 2_

- [ ] 6. State drift
  - [ ] 6.1 Stale detection
    - Serial check at approve time, apply time, and stage open; mark `stale`.
    - _Requirements: 5.1_
  - [ ] 6.2 Drift detail
    - Show the serial change and, where the plan JSON or a refresh-only plan
      reveals it, the resources changed out of band.
    - _Requirements: 5.3_
  - [ ] 6.3 Write drift tests
    - Stale marking, 409 on approve and apply, only "Re-run plan" proceeds, no
      acknowledgement path exists.
    - _Requirements: 5.1, 5.2_

- [ ] 7. Teardown
  - [ ] 7.1 Destroy plan
    - `POST .../plans/teardown` runs `terraform plan -destroy -out=tfplan` through
      the plan worker with `kind = destroy`.
    - _Requirements: 6.1, 6.2_
  - [ ] 7.2 Destroy approval and run
    - Separate approval on the destroy plan's own hash; `POST /plans/{id}/destroy`
      uses the apply worker path with the same hash, approval, and serial checks;
      a `deployments` row with `action = destroy`.
    - _Requirements: 6.1, 6.4, 7.1_
  - [ ] 7.3 Write teardown tests
    - Needs its own plan and approval; an apply approval does not authorize
      destroy; no scheduled or automatic path exists; serial check applies.
    - _Requirements: 6.1 to 6.3_

- [ ] 8. Daily live-resources report
  - [ ] 8.1 Scheduled job
    - EventBridge-triggered job: per partner with a verified sandbox, list projects
      whose latest successful deployment is an apply with no later successful
      destroy, with last-apply resource counts. Store a report row. Read-only.
    - _Requirements: 7.4_
  - [ ] 8.2 Report endpoint and test
    - Partner-scoped read; confirm the job changes nothing in AWS.
    - _Requirements: 7.2, 7.4_

- [ ] 9. Agent boundary and secrets
  - [ ] 9.1 Agent functions
    - `request_sandbox_plan` and read-only plan status and explanation functions
      only, with Pydantic inputs, request context, and call logging.
    - _Requirements: 2.6, 4.6, 6.5_
  - [ ] 9.2 Boundary test
    - Enumerate every tool and route reachable by the agent; assert none can
      approve, apply, or destroy; the approve, apply, and destroy routes reject
      agent-originated requests.
    - _Requirements: 2.6, 4.6, 6.5_
  - [ ] 9.3 Secrets scrubbing test
    - Inject secrets into plan, apply, and output fixtures; assert none reach logs,
      responses, or stored text.
    - _Requirements: 2.5, 4.5, NFR 2_
  - [ ] 9.4 Network egress check
    - Plan, apply, and destroy task definitions restrict egress to required AWS
      endpoints (platform side, in `infra/`).
    - _Requirements: NFR 4_

- [ ] 10. Isolation and audit
  - [ ] 10.1 Extend the isolation suite
    - Register every new endpoint; partner A cannot read or approve partner B's
      plans, approvals, deployments, or sandbox account.
    - _Requirements: 7.2_
  - [ ] 10.2 Audit coverage test
    - Onboarding, plan, approval, apply, drift refusal, teardown, and policy change
      each write an audit row with actor, partner, plan hash, and result.
    - _Requirements: 7.1, 8.4_

- [ ] 11. Build the Sandbox stage UI
  - [ ] 11.1 Plan Review
    - Build from screen `1a38fdff...`: target account, hash, serial, counts, plan
      output, approval checkbox and "Approve plan", "Discard plan", "Re-run plan".
    - _Requirements: 2.3, 3.1, 3.2_
  - [ ] 11.2 Apply Confirmation
    - Build from screen `0b947ad4...` with the copy corrections; confirm dialog
      states account, region, hash, and that apply is refused if state changes.
    - _Requirements: 3.2, 4.1, 4.2_
  - [ ] 11.3 Apply Progress and Outputs
    - Build from the Apply Progress file noted above: lifecycle chips, scrubbed log
      stream, resource counts, non-secret outputs, "Request teardown" as an
      explicit action only.
    - _Requirements: 4.5, 6.3_
  - [ ] 11.4 State Drift
    - Build from screen `7ce65094...` with the copy corrections: serial change,
      drift detail, refused apply, "Re-run plan" only.
    - _Requirements: 5.1, 5.2, 5.3_
  - [ ] 11.5 Teardown Plan Review
    - Build from screen `7b220e81...` with the copy corrections: destroy list and
      separate approval.
    - _Requirements: 6.1, 6.2, 6.4_
  - [ ] 11.6 Admin - Sandbox Accounts
    - Build from screen `f0f2a937...`: single account, trust status, policies with
      copy buttons, one-time setup view, approval policy control, live-resources
      report.
    - _Requirements: 1.3, 7.4, 8.1_
  - [ ] 11.7 Web tests
    - No override control on drift; approve and apply are separate buttons;
      external id never rendered outside the setup view; no teardown schedule UI.
    - _Requirements: 3.2, 5.2, 6.3, 1.4_

- [ ] 12. Final verification
  - [ ] 12.1 Integration test against a throwaway sandbox account
    - Onboard, plan, approve, apply, induce drift, re-plan, teardown with its own
      approval. Confirm nothing remains afterward.
    - _Requirements: all_
  - [ ] 12.2 Run the full suite and confirm acceptance criteria
    - All tests pass; walk requirements 1 to 8 and note which test or artifact
      proves each. State what was verified and what was not for the approval,
      apply, destroy, and cross-account role changes.
    - _Requirements: all_
