# Implementation Plan: Agent and Admin

Tasks build in order. Each cites the requirements it satisfies (see
`requirements.md`) and follows `design.md`. Depends on all earlier specs. Tasks that
touch the agent boundary, approvals, auth, or the repository layer must state in the
change what was verified and what was not (`security.md`). Resolve the open
questions in `design.md` before tasks 6, 9, and 10.

## Design references (Stitch project `18075726235522465175`)

Scanned after generation: required content present; SSO, SAML, SOC 2/SOX, FedRAMP,
GovCloud, SLA figures, bypass or override events, "cryptographic" wording, OpenTofu,
Claude, Aurora, EKS, and billing absent, apart from the copy fixes below.

| Screen | Screen ID |
| --- | --- |
| Sign In | `5e604a130e1b48d5aa941a4e5e2ae5b5` |
| Architecture Stage - Assistant Open | `6f83fe3d3e4c407c8cec865e4146ec3e` |
| Sandbox Stage - Assistant Plan Request | `3675201a3bba4001999e088848c05033` |
| Intake Stage - Assistant Unavailable | `e0a3657a4e8d44acb3480102a8a1c18b` |
| Admin - Users & Roles | `0d4d85dcd64a43489ef321dbe48f77b5` |
| Admin - Partners (Platform operator) | `42f5322a2ec048cebed160fd2474efcd` |
| Admin - Template Versions | `b0efb6bd7bd2488fafd1f053553fc05b` |
| Admin - Default Assumptions | `f0e1e3eb121c4dc0b303beba48f275a9` |
| Admin - Audit Log (Platform Operator) | `f34ff6d678ab43c2abdfc67c9d8a533d` |

Copy corrections to apply when building:

- Sign In: footer year "2025" → current year (or none).
- Assistant Open: remove "Workspace synced to commit … Revert"; keep "Amazon Nova Pro"
  from the model in use, not hard-coded.
- Assistant Plan Request:
  - "cryptographically reviews" and "cryptographic consultant sign-off" → "a named
    consultant approves this exact plan hash".
  - Remove "synthesized AST".
  - NAT gateway count must follow `az_count` (one per active AZ), not "1 NAT Gateway
    (Single AZ)" with two AZs.
  - Role label "LusiformDeployerRole" → the Lusiform worker role; provider constraint
    `~> 5.30.0` → the template's pinned `~> 5.47`.
  - Remove "Export plan (.json)".
  - Footer "Read-only assistant" → "The assistant can't approve, apply, or destroy."
  - The "0 to destroy" answer must say this is a first plan with nothing yet in state,
    not that the pipeline "preserves unrelated tenant state".
- Assistant Unavailable: use only for the panel state. Remove "HTTP 503" text,
  "Manual Parity Available" box, "Multi-Region Disaster Recovery Ready", "TLS 1.3" and
  KMS key claims, and the "~$428 / mo" tier box (no figures on Intake). The intake
  form itself follows `c43ed81557294245a77bb05e54201590` from `intake-and-versions`.
- Users & Roles: remove "Enterprise Cloud Hub", "v2.14.0-aws", "Synchronized", and the
  "Cognito Auth Delivery" label. Partner-admin nav is Users & Roles, Sandbox Accounts,
  Default Assumptions only (no Template Versions, no Audit Log).
- Template Versions: remove "Edit schema JSON", "Record expert review as …", and
  "Export catalog". Rename "New draft version" to "Register draft version". The review
  is recorded in `template.json` through a pull request, so the drawer shows it and
  does not edit it.
- Audit Log: remove "New Deployment" and "System Status" and "Documentation" from the
  sidebar; "Terraform Engine 1.6" → "Terraform 1.10 or later"; replace the "Active
  Operators" tile with something real (events by action). Keep the "Append-only"
  wording; do not add signing language.
- Partners: remove "Directory Sync"; keep per-partner trust status as read-only.
- Default Assumptions: add the fifth field (average log size per request); remove
  "Route 53" from the requests row; partner-admin nav as above for the partner view;
  show the platform-default view for operators with no "Exit to Workspaces".

Superseded screens (safe to delete in Stitch during cleanup):
`0d7a85ac5bc24545b70220176d431d02` (Select Workspace; the picker is dropped),
`943332fd1b0e4af0862eeb9c6aef5f34` (old Users & Roles),
`ff71ddb51d5c49a3972ab426f5c8ab24` (old Template Versions),
`ab17c80dcdac49d5b546650149bd96d3` (old Audit Log),
`48316c7804004a2db945a98540880b2d` (old Assistant Panel Detail),
`f3e36638d9aa46f9bd50a6240f0957fe` (old Architecture Stage - Agent Open).

- [ ] 1. Extend the schema
  - [ ] 1.1 Alembic migration
    - Add `agent_conversations`, `agent_messages`, `agent_tool_calls`,
      `agent_proposals`, `feature_flags` (seed `agent`), and
      `template_version_status_events` with the view `template_version_current`.
    - Add check constraints for `users.status` (`invited`, `active`, `deactivated`)
      and `partners.status` (`active`, `suspended`) if not already present.
    - Append-only triggers on `agent_messages`, `agent_tool_calls`, and
      `template_version_status_events`; `agent_proposals` allows only forward status
      change and sets decision fields once.
    - _Requirements: 4.5, 8.1, 12.4_
  - [ ] 1.2 Repositories
    - Partner-scoped repositories for the agent tables; platform-global repositories
      for flags and template status events; insert-only where required.
    - _Requirements: 15.3_
  - [ ] 1.3 Update version selection
    - Change `intake-and-versions` template selection to read
      `template_version_current` instead of the row's `status`.
    - _Requirements: 12.5_
  - [ ] 1.4 Write migration tests
    - Round trip; triggers block updates; the view returns the latest status; the
      `agent` flag row exists.
    - _Requirements: 8.1, 12.4_

- [ ] 2. Agent tools and boundary
  - [ ] 2.1 Pydantic input models and service wrappers
    - One module per tool, each validating with the schema the UI uses, binding the
      request context with `origin = "agent"`, calling the existing service function,
      and returning a model summary plus a typed card.
    - _Requirements: 2.1, 2.2, 2.3_
  - [ ] 2.2 Estimate preview
    - Add `preview_estimate(parameters, assumptions)` to the estimate service, using
      the same quantity functions and price cache, returning `preview: true` and not
      persisting.
    - _Requirements: 2.6, 4.1_
  - [ ] 2.3 Untrusted wrappers
    - `get_intake` wraps notes and free text as untrusted; no tool passes free text to
      names or commands.
    - _Requirements: 6.1_
  - [ ] 2.4 Tool registry allowlist
    - Fixed constant of twelve names; the registry is compared at boot and the
      process fails on any difference.
    - _Requirements: 3.1, 3.3_
  - [ ] 2.5 Origin guard
    - Approve, apply, destroy, and proposal-accept service functions raise when
      `origin == "agent"`; routes reject agent-originated requests.
    - _Requirements: 3.2, 4.6_
  - [ ] 2.6 Tool-call recording
    - Record each call with redacted params, status, and duration.
    - _Requirements: 8.1, 8.2_
  - [ ] 2.7 Write tool tests
    - Each tool rejects invalid input and is project- and partner-scoped;
      `update_intake_field` and `set_parameters` never create a version;
      `request_sandbox_plan` honors the export gate and verified sandbox; registry
      equals the allowlist; no approve, apply, or destroy path exists.
    - _Requirements: 2.2 to 2.8, 3.1 to 3.5_

- [ ] 3. Proposals
  - [ ] 3.1 Create proposals from `set_parameters`
    - Validate against the template version schema, build the preview, store a
      pending proposal.
    - _Requirements: 4.1_
  - [ ] 3.2 Accept and dismiss endpoints
    - Accept runs as the user, checks status and base version, creates the version
      with the same function as the parameter form, records `resulting_version_id`,
      audits; stale base returns 409 `PROPOSAL_STALE`. Dismiss audits.
    - _Requirements: 4.3, 4.4, 4.5, 8.4_
  - [ ] 3.3 Write proposal tests
    - One version per accept; stale returns 409; one-shot decisions; the agent cannot
      accept; cross-partner access returns 404.
    - _Requirements: 4.1 to 4.6, 15.3_

- [ ] 4. Agent runtime and streaming
  - [ ] 4.1 Build the Strands agent factory
    - Per-request agent with Nova model ids from config, streaming, the Bedrock
      guardrail, a sliding conversation window, and the versioned system prompt.
    - _Requirements: 1.2, 1.3, 6.2, 6.3_
  - [ ] 4.2 SSE endpoint
    - `POST .../agent/messages` emitting `token`, `tool`, `card`, `proposal`,
      `message_complete`, and `error` events; idempotency key; limits for iterations,
      length, timeout, and per-user rate.
    - _Requirements: 1.1, 1.5, 1.6_
  - [ ] 4.3 Conversation storage and history
    - Persist messages and cards; `GET .../conversation` returns the caller's own
      history.
    - _Requirements: 1.4_
  - [ ] 4.4 Output check
    - Currency amounts must appear in the turn's tool results; deny-listed compliance
      and uptime claims; replace with a fallback and log without message text. Draft
      tokens are replaced by `message_complete`.
    - _Requirements: 5.1 to 5.4_
  - [ ] 4.5 Guardrail handling
    - A guardrail intervention yields a safe user message and a log event without the
      blocked text.
    - _Requirements: 6.4_
  - [ ] 4.6 Feature flag and degraded mode
    - Read the flag with a 30 second cache; return 503 `AGENT_UNAVAILABLE` when off or
      on Bedrock failure; expose `features.agent` on `GET /api/me`.
    - _Requirements: 7.1, 7.2_
  - [ ] 4.7 Write runtime tests
    - Scripted fake-model conversations: an invented figure is replaced, a real figure
      is kept, compliance claims are replaced; rate and iteration limits; idempotent
      retry; flag off returns 503 and other routes work.
    - _Requirements: 1.5, 1.6, 5.1 to 5.4, 7.1, 7.2, NFR 3_

- [ ] 5. Model evaluation
  - [ ] 5.1 Evaluation harness
    - A fixed script of conversations with expected tool calls, bad inputs, injection
      attempts in notes, and requests to approve, apply, or destroy.
    - _Requirements: 7.3, NFR 4_
  - [ ] 5.2 Run against Nova Pro and Nova Lite
    - Record tool-selection accuracy, schema-valid call rate, refusal rate, and
      streaming behavior; enable a model only after it passes. Consider Premier only
      if Pro fails.
    - _Requirements: 7.3, 7.4_

- [ ] 6. Sign-in and account state
  - [ ] 6.1 Request-context checks
    - Refuse deactivated users and suspended partners with `ACCOUNT_DISABLED` and
      `PARTNER_SUSPENDED`; set `invited → active` on first sign-in.
    - _Requirements: 9.3, 10.2_
  - [ ] 6.2 Sign-in page and error pages
    - Build from screen `5e604a13...` with the copy fixes: landing that sends the user
      to the themed hosted login, "Forgot password?", the invitation line, and
      account-disabled and partner-suspended pages.
    - _Requirements: 9.1, 9.2, 9.4_
  - [ ] 6.3 Write auth tests
    - Disabled and suspended tokens refused; no workspace picker route exists; no
      self-sign-up route.
    - _Requirements: 9.1, 9.3, 9.5_

- [ ] 7. Users and roles
  - [ ] 7.1 Cognito client wrapper
    - `AdminCreateUser`, `AdminDisableUser`, `AdminEnableUser`,
      `AdminUserGlobalSignOut`, resend; least-privilege IAM for the API task role.
    - _Requirements: 10.2, 10.5_
  - [ ] 7.2 Endpoints
    - List, invite, change role, deactivate, reactivate, resend; guards for the last
      active admin, self-deactivation, and platform-operator role; compensation when
      the database insert fails after Cognito create; audit rows with before/after.
    - _Requirements: 10.1 to 10.6_
  - [ ] 7.3 Write tests
    - Guards, compensation, cross-partner 404, role from token not body, deactivated
      user refused immediately.
    - _Requirements: 10.3 to 10.6, 15.1, 15.2_
  - [ ] 7.4 Users & Roles page
    - Build from screen `0d4d85dc...` with the copy fixes: table, role dropdown, status
      chips, invite dialog, lifecycle actions.
    - _Requirements: 10.1_

- [ ] 8. Partners
  - [ ] 8.1 Endpoints
    - List with counts and sandbox trust, create with first-admin invite, suspend,
      reactivate; audit rows; `admin.access` rows for operator reads.
    - _Requirements: 11.1 to 11.4_
  - [ ] 8.2 Write tests
    - Suspended partner refused; no external id in any response; non-operators get
      403.
    - _Requirements: 11.2, 11.4, 15.4_
  - [ ] 8.3 Partners page
    - Build from screen `42f5322a...` with the copy fix.
    - _Requirements: 11.1_

- [ ] 9. Template versions
  - [ ] 9.1 Register, publish, retire
    - Register from the publish helper output after checking the shipped manifest;
      publish requires a review record and a matching manifest; retire; each adds a
      status event and an audit row.
    - _Requirements: 12.2 to 12.6_
  - [ ] 9.2 List and schema view endpoints
    - Semver, current status, Terraform version, review record, project counts, and
      the read-only `schema.json`.
    - _Requirements: 12.1_
  - [ ] 9.3 Write tests
    - Publish blocked without review or with a manifest mismatch; status events append
      only; retired versions skipped by selection; non-operators get 403.
    - _Requirements: 12.3 to 12.5, 15.4_
  - [ ] 9.4 Template Versions page
    - Build from screen `b0efb6bd...` with the copy fixes.
    - _Requirements: 12.1_

- [ ] 10. Default assumptions
  - [ ] 10.1 Endpoints
    - Get, put, and delete (reset) by scope; bounds validation; audit with before/after;
      no effect on existing estimates.
    - _Requirements: 13.1 to 13.4_
  - [ ] 10.2 Write tests
    - Partner admin cannot write the platform row; operator cannot write a partner row
      without the partner id; existing estimates unchanged; new assumption sets use
      the partner default, else platform.
    - _Requirements: 13.1, 13.3_
  - [ ] 10.3 Default Assumptions page
    - Build from screen `f0e1e3eb...` with the copy fixes, in partner and platform
      variants.
    - _Requirements: 13.1, 13.2_

- [ ] 11. Audit log
  - [ ] 11.1 List, detail, and export
    - Keyset pagination; filters; redaction of denied keys; CSV with formula
      neutralization and a row cap; `admin.access` rows.
    - _Requirements: 14.1 to 14.5_
  - [ ] 11.2 Action catalog
    - A shared constant of action names; a test that every action written anywhere in
      the codebase is in the catalog.
    - _Requirements: 14.1_
  - [ ] 11.3 Write tests
    - Filters; redaction; CSV injection; no partner-admin access; no signing or
      attestation language in responses.
    - _Requirements: 14.2 to 14.6, 15.4_
  - [ ] 11.4 Audit Log page
    - Build from screen `f34ff6d6...` with the copy fixes: filters, event table,
      inspector with before/after diff.
    - _Requirements: 14.1, 14.3_

- [ ] 12. Build the assistant UI
  - [ ] 12.1 Panel and stream client
    - A `fetch` stream reader for the SSE events, draft-to-final replacement, tool
      chips, cards, and the model label from the response.
    - _Requirements: 1.1, 1.3, 5.4_
  - [ ] 12.2 Architecture stage panel
    - Build from screen `6f83fe3d...`: proposal card with Accept and Dismiss, estimate
      card, suggestion chips.
    - _Requirements: 4.2, 4.3_
  - [ ] 12.3 Sandbox stage panel
    - Build from screen `3675201a...` with the copy fixes: plan card linking to the
      human review; no approve, apply, or destroy control in the panel.
    - _Requirements: 3.1, 2.7_
  - [ ] 12.4 Unavailable state
    - Build from screen `e0a3657a...` with the copy fixes; the panel collapses and the
      form stays fully usable; `features.agent` false hides the panel.
    - _Requirements: 7.2_
  - [ ] 12.5 Feature flag control
    - Operator toggle with audit.
    - _Requirements: 7.1, 8.4_
  - [ ] 12.6 Write web tests
    - No approve, apply, or destroy control in the panel; figures come from cards;
      unavailable state keeps the form working; consultants see no admin navigation.
    - _Requirements: 3.1, 5.4, 7.2_

- [ ] 13. Isolation and logging
  - [ ] 13.1 Extend the isolation suite
    - Register every new endpoint; partner A cannot read partner B's conversations,
      proposals, tool calls, or users.
    - _Requirements: 15.2, 15.3_
  - [ ] 13.2 Logging tests
    - Logs carry request id, partner, user, and project ids and no message or intake
      text; tool-call params are redacted.
    - _Requirements: 8.2, 8.3, NFR 2_

- [ ] 14. Final verification
  - [ ] 14.1 Run the full suite and the evaluation set
    - All tests pass across `api/` and `web/`; the evaluation set passes for the model
      you intend to enable; first-token time measured against the 3 second target.
    - _Requirements: all, NFR 1, NFR 4_
  - [ ] 14.2 Confirm the acceptance criteria
    - Walk requirements 1 to 15 and note which test or artifact proves each. State what
      was verified and what was not for the agent boundary, auth, and the repository
      layer.
    - _Requirements: all_
