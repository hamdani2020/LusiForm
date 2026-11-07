# Design: Sandbox Deployment

## Overview

```
Admin: onboard sandbox ─► trust policy + external id (Secrets Manager) ─► verify AssumeRole

Consultant:  request plan ─► plan job ─► PLAN worker (plan role) ─► assume partner role
                                           terraform plan -out ─► plan file + output ─► S3
                                           hash + state serial ─► result ─► deployment_plans
             review ─► approve (hash) ─► plan_approvals (append-only)
             apply  ─► check approval + hash + serial ─► apply job ─► APPLY worker (apply role)
                                           terraform apply <planfile> ─► deployments + outputs
             teardown: destroy plan ─► approve ─► apply job (destroy)
```

It realizes `requirements.md` and `security.md`, and the Technical Design's
sandbox section. Nothing here has an autonomous path: every plan, apply, and
destroy begins with a human request, and every apply and destroy needs a matching
human approval.

## Trust boundaries

| Actor | Can | Cannot |
| --- | --- | --- |
| Agent | Request a plan, read plan and status, explain | Approve, apply, destroy |
| Consultant | Request plan, approve (per policy), apply, request teardown | Skip approval, override drift |
| Partner admin | Onboard sandbox, set approval policy, plus consultant actions | Skip approval, override drift |
| Plan worker | Read the version's files, assume the partner role, write state lock and plan | Apply or destroy |
| Apply worker | Run the saved plan file | Plan, run any file that is not an approved plan |
| API | Record plans, approvals, deployments; issue jobs | Run Terraform |

The agent has no tool for approve, apply, or destroy, and the API refuses those
routes for any agent-originated request (the agent calls internal service
functions, which do not include them).

## Onboarding

### Flow

1. A partner admin opens the Sandbox Accounts screen and enters the 12-digit
   account id, a name, and the region.
2. The API creates a random external id (32 bytes, base64url), stores it in
   Secrets Manager under `lusiform/<partner_id>/sandbox-external-id`, and keeps only
   the secret ARN in `sandbox_accounts.external_id_ref`.
3. The screen shows the **trust policy** and **permissions policy** to create in the
   sandbox account, with a "Copy" button and a CloudFormation/Terraform snippet
   alternative. The external id is part of the trust policy and is shown only in
   that one-time setup view, which the admin can re-open with a fresh step-up
   authentication; it is never in logs or other responses. (The partner needs it
   once to create the role; this is the unavoidable exposure, and it is limited to
   the admin who owns the account.)
4. The admin presses "Verify". The API asks a small verification job to
   `sts:AssumeRole` with the external id and call `sts:GetCallerIdentity`. On
   success the status becomes `verified`; otherwise `failed` with a safe reason
   (role missing, external id mismatch, wrong account).

### Trust policy

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "LusiformWorker",
    "Effect": "Allow",
    "Principal": { "AWS": "arn:aws:iam::<LUSIFORM_ACCOUNT>:role/LusiformWorker" },
    "Action": "sts:AssumeRole",
    "Condition": { "StringEquals": { "sts:ExternalId": "<per-partner external id>" } }
  }]
}
```

The principal is the worker role, not the account root. Plan and apply use two
distinct source roles (`LusiformPlanWorker`, `LusiformApplyWorker`); the trust
policy lists both, and the permissions policy is attached to one partner role that
both assume, with session names `lusiform-plan-<job>` and `lusiform-apply-<job>`
so CloudTrail separates them. Condition keys on the role session name keep an
apply session from being used for planning and the reverse.

### Permissions policy

Taken from the template's `sandbox-policy.json`, generated from `inventory.json`:
create, read, update, and delete actions for exactly the template's resource types,
scoped by ARN pattern, with a `lusiform-managed` tag condition where the service
supports it. A test compares the policy to the inventory (Requirement NFR 3). The
template version records which policy a project needs; if a project's template
version needs a newer policy than the partner's role has, plan is refused with a
clear message and the updated policy is shown.

### Data

`sandbox_accounts` (foundation): `aws_account_id`, `role_arn`, `external_id_ref`,
`status` (`pending`, `verified`, `failed`). Added: `region`, `verified_at`,
`policy_template_version`. One row per partner, enforced by a unique constraint on
`partner_id`.

## Plan

### Request

`POST /api/projects/{id}/versions/{vid}/plans` requires: the version passed the
export gate (Requirement 2.1); the sandbox is `verified`; the partner's policy
version covers the template version. It inserts a `deployment_plans` row with status
`queued` and a `plan` job through the outbox. A second request while one is queued
or running returns the existing plan.

### Plan worker

A dedicated ECS task and role, separate from the generation and validator workers:

1. Assume the partner role with the external id (read from Secrets Manager via the
   worker role; the API never passes it in a message).
2. Download the version's rendered project and verify every file hash against the
   manifest.
3. `terraform init` with `-backend-config` for the state bucket, key, and region,
   plus the filesystem provider mirror. The backend uses `use_lockfile = true`.
   The state lives in the **partner's** sandbox account bucket, created by the
   onboarding policy's companion step, keyed by `lusiform/<project_id>/<version>`
   so versions do not share state. (Open question below.)
4. Read the current state serial.
5. `terraform plan -input=false -lock-timeout=60s -out=tfplan`.
6. Compute the **plan hash** (below), render `terraform show -json tfplan` and the
   human-readable text, scrub sensitive values using the plan JSON's
   `sensitive_values`, and upload `tfplan`, `plan.json`, and `plan.txt` under the
   version prefix.
7. Publish the result with hash, serial, counts, and artifact keys.

### Plan hash

SHA-256 over a canonical concatenation of: the manifest hash of the rendered files,
the canonical variable values, the provider lock file hash, the state serial, the
sandbox account id, the region, and the Terraform version. Each part is labeled and
length-prefixed so parts cannot be shifted into one another. Any change to the
version, the account, or the state serial produces a different hash (Requirement
2.3, 2.4).

### Data

`deployment_plans` (foundation, immutable once created): `plan_hash`,
`plan_output_s3_key`, `state_serial`, `status`. Added: `kind` (`apply` or
`destroy`), `plan_file_s3_key`, `counts_json`, `sandbox_account_id`,
`terraform_version`, `created_by`. Status moves only `queued → ready | failed`, via
the result consumer; hash and serial fields never change.

## Approval

`POST /api/plans/{id}/approvals` with the displayed hash in the body:

1. Check the plan is `ready` and not stale (the current state serial still equals
   the plan's, read by a lightweight serial check job, or the API reads the
   `terraform.tfstate` serial from S3 with the plan role's read access).
2. Check the body hash equals the stored hash.
3. Check the caller may approve under the partner policy (Requirement 8); the
   approver is the authenticated user, never taken from the body.
4. Insert into `plan_approvals` (append-only; unique on `plan_id`, so one approval
   per plan) and an audit row.

There is no revoke, edit, or delete route (Requirement 3.3). A plan no one wants to
apply is left unapplied; its approval remains as history.

## Apply

`POST /api/plans/{id}/apply`:

1. The plan must be `kind = apply`, `ready`, and have an approval whose hash
   matches.
2. The API checks the current state serial against the plan's. If it differs,
   respond 409 `STATE_CHANGED` and mark the plan `stale`; write an audit row. There
   is no flag to skip this (Requirement 4.2).
3. Insert a `deployments` row (`action = apply`, `queued`) and an apply job.
4. The **apply worker** (separate task and role) re-checks everything it relies on:
   it downloads `tfplan`, recomputes the plan hash from the stored inputs, compares
   it to the approval hash passed in the job, re-reads the state serial, and only
   then runs `terraform apply -input=false tfplan`. A mismatch at the worker aborts
   with `PLAN_MISMATCH` or `STATE_CHANGED`. This second check means a compromised or
   buggy API cannot make the worker apply an unapproved plan.
5. Progress lines are scrubbed of sensitive values and published as status events.
   On completion the worker reads `terraform output -json`, drops every output marked
   `sensitive`, and publishes the rest.
6. The consumer updates `deployments` (`running → succeeded | failed`), stores
   `outputs_json` (non-secret only), and writes audit rows.

Plan and apply run in different tasks with different roles so a plan cannot produce
a state the apply later trusts without the serial check (Technical Design).

### Why `terraform apply tfplan` is safe here

Applying a saved plan file executes exactly what was planned and fails if the state
has changed since (Terraform checks the state lineage and serial inside the plan
file). This is the second line of defense behind the explicit serial check.

## State drift

- Before approval and before apply, the API compares the stored plan serial with the
  state serial in the sandbox.
- If different: the plan becomes `stale`, apply and approve return 409
  `STATE_CHANGED`, and the Drift view shows the serial change and, where the plan
  JSON or a refresh-only plan reveals it, which resource changed out of band.
- The only way forward is "Re-run plan", which creates a new plan with a new hash
  and requires a new approval. There is no acknowledgement checkbox that overrides
  this (Requirement 5.2).
- A scheduled refresh-only plan is out of scope; drift is detected at approve/apply
  time and when the consultant opens the stage.

## Teardown

- "Request teardown" creates a `deployment_plans` row with `kind = destroy` and runs
  `terraform plan -destroy -out=tfplan` through the same plan worker.
- The Teardown screen shows the destroy plan (what will be destroyed) and requires a
  separate approval with the destroy plan's own hash.
- Destroy executes through the same apply worker path, with the same hash,
  approval, and serial checks. A `deployments` row with `action = destroy` records
  the result.
- No lease, TTL, or scheduled destroy exists. The only thing the platform does on a
  schedule is report (below).

## Daily live-resources report

A scheduled job (EventBridge) lists, per partner with a verified sandbox, the
projects whose latest successful deployment is an apply with no later successful
destroy, with the resource counts from the last apply. It stores a report row and
shows it on the Sandbox Accounts screen and the project list. It does not change
anything in AWS.

## Approval policy

`partner_settings.approval_policy` (`any_consultant` default, or `partner_admin`).
Changes are made by a partner admin through
`PUT /api/admin/approval-policy`, audited, and apply to future approvals only. The
approve and destroy-approve routes check it.

## API

| Method and path | Purpose |
| --- | --- |
| `POST /admin/sandbox-accounts` | Create the sandbox record and external id |
| `GET /admin/sandbox-accounts` | Account id, role ARN, trust status, report |
| `POST /admin/sandbox-accounts/verify` | Verify the trust |
| `GET /admin/sandbox-accounts/setup` | One-time policies view (step-up auth) |
| `PUT /admin/approval-policy` | Set who may approve |
| `POST /projects/{id}/versions/{vid}/plans` | Request a plan (apply kind) |
| `POST /projects/{id}/versions/{vid}/plans/teardown` | Request a destroy plan |
| `GET /plans/{id}` | Plan output, hash, counts, status, approval |
| `POST /plans/{id}/approvals` | Named approval of the hash |
| `POST /plans/{id}/apply` | Apply an approved apply plan |
| `POST /plans/{id}/destroy` | Run an approved destroy plan |
| `GET /plans/{id}/deployment` | Apply or destroy status, resources, outputs |

All writes accept `Idempotency-Key`. All are partner-scoped and in the isolation
suite.

## Web

Screens for this spec (IDs in tasks):

- **Sandbox Stage - Plan Review:** target account card, plan hash and serial, counts,
  plan output, approval checkbox and "Approve plan", "Discard plan" and "Re-run plan".
- **Sandbox Stage - Apply Confirmation:** approved record, "Apply to sandbox", and
  the confirm dialog stating the account, region, hash, and that apply is refused if
  the state changes.
- **Sandbox Stage - Apply Progress & Outputs:** lifecycle chips, log stream,
  resource counts, non-secret outputs.
- **Sandbox Stage - State Drift Error:** serial change, drift detail, refused apply,
  "Re-run plan".
- **Sandbox Stage - Teardown Plan Review:** destroy plan, separate approval.
- **Admin - Sandbox Accounts:** the single account, trust status, policies, report.

## Testing

- Plan hash: every part changes the hash; length-prefixing blocks shifting; same
  inputs, same hash.
- Approval: hash mismatch rejected; approver is the caller; one approval per plan;
  no mutation route exists; policy enforced; 403 for non-approvers.
- Apply: refused without approval, with a mismatched hash, and with a changed state
  serial; the worker's own re-checks abort even when the API is bypassed in a test.
- Apply never targets a non-sandbox account (account id matches the onboarded one).
- Drift: stale marking, 409, only "Re-run plan" proceeds.
- Teardown: needs its own plan and approval; no automatic path; apply approval does
  not authorize destroy.
- Agent: no tool or route reachable by the agent can approve, apply, or destroy.
- Secrets: external id and outputs marked sensitive never appear in logs, responses,
  or plan text; scrubber tests with injected secrets.
- Trust and policy: the policy equals the inventory; the principal is the worker
  role, not root; a wrong external id fails verification.
- Isolation: all endpoints; partner A cannot read or approve partner B's plans.
- Integration (against a throwaway sandbox account): plan, approve, apply, drift,
  and destroy end to end.

## Open questions

1. **State location.** Whether Terraform state for sandbox deployments lives in the
   partner's account (my default, so Lusiform holds no customer-resource state) or
   in a Lusiform-owned bucket. The Technical Design says "S3 with S3 locking" for the
   project's own state without naming the account. The partner-account option needs
   a state bucket created during onboarding, which widens the permissions policy;
   decide before building.
2. **Approval policy.** Default is "any consultant" per the stories. Confirm.
3. **External id exposure.** Showing it once to the admin during setup is required
   for the partner to create the role. Confirm the step-up re-display behaviour is
   acceptable.
4. **Role session separation.** Using one partner role with session-name conditions
   is simpler than two roles per partner; confirm it meets the plan/apply isolation
   intent in the Technical Design.
