# PRD: Lusiform, Startup MVP

**Version:** 0.2 (draft, aligned with Technical Design) **Owner:** \[Name\] **Status:** For pilot planning

## Problem

AWS Partner consultancies spend days on startup engagements that follow nearly the same pattern: gather requirements, design a simple AWS architecture, estimate cost, write Terraform, and hand off. Most of that time goes to repetitive setup work, not to the judgment that differentiates the partner. Startup deals are also small, so every hour of manual work directly cuts into margin.

## Goal

Let a consultant take a startup customer from requirements conversation to a reviewable architecture diagram, cost estimate, and validated Terraform project in under 2 hours, then deploy it to the partner's sandbox AWS account after a named approval of the plan.

## Target User

Solutions architects and DevOps consultants at AWS Partner consultancies who run startup-tier engagements (roughly 1 to 3 services tiers, single region, small team, limited compliance needs).

## Scope

**In:**

- Structured intake for a startup workload: workload type, region, expected users and traffic, availability target, data sensitivity, budget ceiling, free-text notes
- One fixed reference architecture: single region, serverless or small container footprint, managed database, basic monitoring, centralized logs
- Parameter adjustment (task or instance sizes, database tier, retention, AZ count within the single region)
- Architecture diagram in draw.io format, generated from the same architecture graph as the Terraform, requested through the agent, with validation and a parity check against the Terraform
- Cost estimate from the AWS Pricing API, with an editable usage assumptions table and CSV export
- Terraform project generation (modules, variables, README), plain files, zip download
- Automatic validation: terraform fmt, terraform validate, tflint, Checkov, with results saved to the project
- Sandbox deployment to the partner's sandbox AWS account, only after validation passes and a named consultant approves the exact plan
- Teardown of sandbox resources, with approval and audit
- Save, version, and reopen projects
- Admin page for partners, users and roles, template versions, default assumptions, and audit log

**Out:**

- SMB and enterprise patterns (later phases)
- Deployment to customer AWS accounts (MVP deploys only to the partner's sandbox)
- Free-form architecture designer (diagram is generated from the template graph, not drawn freehand)
- Multi-cloud, non-AWS services, CDK output
- Drift detection, ongoing operations, migration assessment
- Billing, marketplace, white-labeling, partner-authored modules
- Agent ability to approve, apply, or destroy infrastructure (human approval only)
- SSO or RBAC beyond partner admin, consultant, and platform operator roles

## User Stories

1. As a consultant, I can enter intake answers for a startup customer so the platform knows the workload shape.
2. As a consultant, I can review the proposed architecture and adjust its parameters.
3. As a consultant, I can edit the usage assumptions behind the cost estimate and see the total update.
4. As a consultant, I can export the cost estimate as CSV to share with the customer.
5. As a consultant, I can download a Terraform project that is readable and editable without the platform.
6. As a consultant, I can see Terraform validation results (fmt, validate, tflint, Checkov) and diagram validation and parity results before I hand off the project.
7. As a consultant, I can save and reopen a project and see its version history.
8. As a consultant, I can ask the agent to draw the architecture and get a draw.io diagram that matches the Terraform.
9. As a consultant, I can review the full sandbox plan and approve its exact hash before anything is applied.
10. As a consultant, I can apply an approved plan to the sandbox account and see its status and non-secret outputs.
11. As a consultant, I can tear down sandbox resources through an approved destroy plan.
12. As a partner admin, I can invite users, assign roles, and see the status of our sandbox account and its role trust.
13. As a platform operator, I can manage partners, template versions, default assumptions, and the audit log.

## Success Metrics

- Intake-to-deliverable time under 2 hours for 80% of pilot projects, measured up to validated Terraform and diagram
- Cost estimates within ±15% of the consultant's manual estimate on at least 3 of 4 pilot scenarios
- Generated Terraform has zero high-severity Checkov findings on the pilot templates
- Diagram parity check passes on every pilot version before export
- Sandbox apply succeeds for every approved plan in pilot, with no apply run against an unapproved or changed plan
- Pilot consultants say they would use it on a real engagement (target: 2 of 2 partners)
- Baseline: manual startup engagement time measured across 2 to 3 engagements before launch

## Requirements

**Functional**

- Intake validates required fields and blocks generation until they are complete
- Architecture is generated only from the single startup template with validated parameters
- The architecture diagram and the Terraform are both rendered from the same architecture graph, and a parity check blocks export on mismatch
- Pricing uses the AWS Pricing API for the selected region; assumptions are stored with each estimate
- Generated Terraform and diagram are deterministic: the same intake produces the same output
- Validation runs automatically on every generation and on every edit
- Sandbox deployment is available only for a version that passed validation
- Each apply runs only against a saved plan whose hash matches a recorded approval; apply is refused if the state has changed since planning

**Non-functional**

- Generation completes in under 60 seconds for a standard startup project
- All customer data is stored encrypted at rest and separated per partner account
- Generated code and diagrams contain no hardcoded credentials or account IDs
- Sandbox credentials are never shown in the UI or written to logs; access is through a cross-account role with a fixed policy

## Dependencies and Assumptions

- AWS Pricing API access and rate limits are sufficient for interactive use
- Pilot partners can provide 2 to 3 past startup engagements for baseline timing and estimate comparison
- Pilot partners can create a sandbox AWS account and a cross-account role with the platform's fixed policy
- An AWS-experienced engineer reviews the startup reference architecture before pilot use

## Risks

- **Template quality:** the single startup template must be right; it is the whole product in MVP
- **Estimate trust:** consultants will reject numbers they cannot inspect, so assumptions must be visible and editable
- **Sandbox safety:** an over-broad cross-account role or an apply against a changed plan could change a customer's environment; mitigated by a fixed policy, plan hash approval, and a state serial check
- **Diagram and Terraform drift:** a diagram that does not match the code misleads the customer; mitigated by the parity check
- **Scope creep toward SMB or customer-account deployment:** hold the line until pilot data justifies it

## Open Questions

- Where does the platform run, and how is customer data stored and isolated?
- Pricing model for the pilot: free, or a flat fee per project?
- Which region set is supported at launch?
- Is the startup template serverless-first, container-first, or a choice the consultant makes at intake?
- Who may approve a plan: any consultant, or only partner admins for applies and destroys?
- Does any diagram-to-Terraform mismatch block the version, or only certain mismatch types?
