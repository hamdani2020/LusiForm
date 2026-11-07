# Product: Lusiform (Startup MVP)

## What it is

Lusiform helps AWS Partner consultancies take a startup customer from a
requirements conversation to a reviewable architecture diagram, a cost estimate,
and a validated Terraform project in under two hours, then deploy it to the
partner's own sandbox AWS account after a named consultant approves the exact
plan.

## Who it's for

Solutions architects and DevOps consultants at AWS Partner consultancies running
startup-tier engagements: roughly 1 to 3 service tiers, a single region, a small
team, and limited compliance needs.

## The eight-stage flow

Every project moves through these stages, in this order and with these names:

1. **Intake** — structured questions about the workload.
2. **Architecture** — review and adjust template parameters.
3. **Diagram** — a draw.io diagram rendered from the architecture graph.
4. **Estimate** — cost from the AWS Pricing API with editable assumptions.
5. **Terraform** — a readable, downloadable project.
6. **Validation** — terraform fmt, terraform validate, tflint, Checkov.
7. **Sandbox** — plan, named approval, apply, and teardown.
8. **Handoff** — download the package (zip).

## In scope

- Structured intake for a startup workload.
- One fixed startup reference architecture (see tech.md).
- Parameter adjustment within the template's schema.
- A draw.io diagram and the Terraform, both rendered from one architecture graph,
  with a parity check that blocks export on mismatch.
- Cost estimate from the AWS Pricing API, editable assumptions, CSV export.
- Terraform project generation, plain files, zip download.
- Automatic validation on every generation and edit.
- Sandbox deployment to the partner's sandbox account, only after validation
  passes and a named consultant approves the exact plan hash.
- Teardown of sandbox resources, with its own approval and audit.
- Save, version, and reopen projects.
- Admin: partners, users and roles, template versions, default assumptions,
  audit log.

## Out of scope (do not build, do not drift toward)

- SMB and enterprise architecture patterns.
- Deployment to customer AWS accounts. MVP deploys only to the partner sandbox.
- A free-form architecture designer. The diagram is generated from the template
  graph, never drawn or edited freehand.
- Multi-cloud, non-AWS services, or CDK output.
- Drift detection, ongoing operations, migration assessment.
- Billing, marketplace, white-labeling, partner-authored modules.
- Any agent ability to approve, apply, or destroy infrastructure.
- SSO, or RBAC beyond the three roles below.

## Roles

Exactly three, defined in the data model:

- `partner_admin` — manages users and roles within one partner, views sandbox
  account trust, sets default assumptions. Scoped to that partner.
- `consultant` — creates projects, edits intake and parameters, runs generation
  and validation, requests sandbox plans, downloads packages.
- `platform_operator` — Lusiform staff; manages partners, template versions, and
  default assumptions across partners, and reviews the audit log.

## Claims we must not make

The product does not certify compliance. Never put SOC 2, PCI-DSS, HIPAA, ISO
27001, FedRAMP, or uptime-SLA guarantees into the UI, generated output, or
documents as if Lusiform provides them. Intake may record a customer's own data
sensitivity, but the platform makes no certification claim.

## Source of truth

The PRD (`docs/PRD Lusiform, Startup MVP.md`) and the Technical Design
(`docs/Technical Design Lusiform, Startup MVP.md`) are authoritative. When UI
designs, sample content, or any other artifact conflict with these two
documents, the documents win.
