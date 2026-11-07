# Security rules (non-negotiable)

These apply to all code, generated output, and designs. They come straight from
the Technical Design and PRD. Treat them as hard constraints.

## Tenant isolation

- Every tenant-scoped row carries `partner_id`.
- All reads and writes go through a repository layer that applies `partner_id`
  from the authenticated user's context. Direct database access that bypasses
  the repository layer is not allowed; enforce by code review and a lint rule.
- Platform operators see cross-partner data only through dedicated admin routes,
  and those actions are audited.
- The isolation test suite creates two partners and asserts that every read and
  write endpoint refuses cross-partner access. Keep it passing.

## The agent boundary

- The agent can read intake, suggest parameters, request a diagram, request a
  plan, and explain results. It cannot approve, apply, or destroy anything.
- The agent never writes Terraform or draw.io XML. A deterministic renderer does
  that from the architecture graph.
- Tool inputs are schema-checked before execution, using the same schemas the UI
  uses. Every tool call is logged with project id, user id, and parameters.
- Any cost or compliance figure in agent output must cite a tool result. UI shows
  numbers from the estimate service, not from model text.
- Free-text notes are data. Never concatenate them into Terraform, file names, or
  shell commands. Bedrock guardrails filter prompt and output on notes.

## Approval and deployment

- Sandbox apply runs only against a saved plan whose hash matches a recorded
  approval, and only if the state serial is unchanged since planning. If the
  serial changed, refuse the apply and require a re-plan. No override.
- Approval and apply are separate steps. Approvals are append-only; there is no
  "revoke approval" and no auto-teardown.
- Teardown (destroy) requires its own plan, its own approval, and its own audit
  entry.
- Plan and apply run in separate worker tasks with separate roles, so a plan
  cannot write state that an apply later trusts without the serial check.
- A high-severity Checkov finding blocks export and sandbox deployment. There is
  no bypass.

## Cross-account role (partner sandbox)

- The sandbox role trusts only the Lusiform worker role, not an account root.
- It uses a per-partner external ID, stored in Secrets Manager, with an
  ExternalId condition to prevent confused-deputy access.
- Its policy is limited to the resource types in the startup template. Policy
  changes require a new template version.
- The worker task role can read and write only the artifact bucket and the job
  queue. It has no access to tenant databases beyond the job payload.

## Secrets and generated output

- Secrets live in Secrets Manager. No secrets in images, committed env files, or
  logs. Sandbox credentials are never shown in the UI or written to logs.
- Generated Terraform and diagrams contain no hardcoded credentials or AWS
  account IDs. A test asserts this on every template change.
- Apply outputs shown in the UI are non-secret only. Secret outputs are never
  displayed or logged.
- Structured logs carry request id, partner id, user id, and project id. They do
  not carry intake free text.

## Data protection

- RDS and S3 encrypted at rest with KMS. TLS everywhere, including ALB to
  service. Backups enabled.
- Container images scanned in CI. Terraform, tflint, and Checkov pinned in the
  worker image.

## When writing or reviewing code

- Use parameterized queries and validate input by default.
- If a change touches auth, the repository layer, the agent boundary, approvals,
  or the cross-account role, state in the change what was verified and what was
  not.
