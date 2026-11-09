# Lusiform

![Status](https://img.shields.io/badge/status-specs%20complete-0F766E)
![Specs](https://img.shields.io/badge/specs-8-14213D)
![Terraform](https://img.shields.io/badge/Terraform-%E2%89%A5%201.10-844FBA?logo=terraform&logoColor=white)
![AWS](https://img.shields.io/badge/AWS-ECS%20Fargate%20%7C%20RDS%20PostgreSQL-FF9900?logo=amazonwebservices&logoColor=white)
![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/Web-React%20%2B%20Vite-61DAFB?logo=react&logoColor=black)
![Amazon Nova](https://img.shields.io/badge/Agent-Amazon%20Nova%20via%20Bedrock-232F3E?logo=amazonwebservices&logoColor=white)

Lusiform helps AWS Partner consultancies take a startup customer from a
requirements conversation to a reviewable architecture diagram, a cost estimate,
and a validated Terraform project in under two hours. It then deploys to the
partner's own sandbox AWS account after a named consultant approves the exact plan.

> Status: specs complete, implementation not started. This repository currently
> holds the PRD, the Technical Design, steering files, and eight specs.

## The eight-stage flow

1. **Intake**: structured questions about the workload.
2. **Architecture**: review and adjust template parameters.
3. **Diagram**: a draw.io diagram rendered from the architecture graph.
4. **Estimate**: cost from the AWS Pricing API with editable assumptions.
5. **Terraform**: a readable, downloadable project.
6. **Validation**: `terraform fmt`, `terraform validate`, tflint, Checkov.
7. **Sandbox**: plan, named approval, apply, and teardown.
8. **Handoff**: download the package (zip).

## Principles

- One fixed startup reference architecture: ECS Fargate and RDS PostgreSQL, one
  region, CloudWatch, least-privilege IAM.
- Terraform and the diagram are both rendered from one architecture graph. The
  output is deterministic, and a parity check blocks export on mismatch.
- Costs come from the AWS Pricing API. The UI never shows a figure a model made up.
- The agent (Amazon Nova through Bedrock, Strands Agents) reads and suggests. It
  cannot approve, apply, or destroy anything.
- A high-severity Checkov finding blocks export and deployment, with no bypass.
- Apply runs only against a saved plan whose hash matches a recorded approval and
  whose state serial is unchanged.
- Lusiform makes no compliance or uptime claims.

## Repository layout

```
lusiform/
  api/         FastAPI service: auth, projects, intake, estimates, admin,
               approvals, agent streaming
  worker/      ECS Fargate worker: render, validate, plan/apply/destroy, package
  web/         React (Vite) + shadcn/ui + Tailwind consultant and admin UI
  templates/   Startup reference architecture: Terraform modules, versioned
  infra/       Terraform for the Lusiform platform itself
  docs/        PRD and Technical Design (source of truth)
  .kiro/       Steering, specs, hooks
```

Only `docs/` and `.kiro/` exist today. The other directories are created by the
`foundation` spec.

## Stack

| Area | Choice |
| --- | --- |
| Web | React, Vite, TypeScript, shadcn/ui, Tailwind CSS |
| API | FastAPI (Python) on ECS Fargate |
| Worker | Python on ECS Fargate, jobs from SQS |
| Agent | Strands Agents on Amazon Nova Pro (Nova Lite for low-cost calls) |
| Data | PostgreSQL (RDS), S3, SQS, Cognito, Secrets Manager |
| Migrations | Alembic |
| IaC | Terraform 1.10 or later, S3 state with `use_lockfile = true` |

## Documents

- [PRD](docs/PRD%20Lusiform%2C%20Startup%20MVP.md)
- [Technical Design](docs/Technical%20Design%20Lusiform%2C%20Startup%20MVP.md)

The PRD and Technical Design are authoritative. Where any other artifact conflicts
with them, they win.

## Specs

Each spec has `requirements.md`, `design.md`, and `tasks.md` under `.kiro/specs/`.
They are meant to be built in this order:

1. [foundation](.kiro/specs/foundation): monorepo, Cognito auth, schema, tenant isolation
2. [startup-template](.kiro/specs/startup-template): Terraform modules and parameter schema
3. [intake-and-versions](.kiro/specs/intake-and-versions): intake, parameters, immutable versions
4. [generation-pipeline](.kiro/specs/generation-pipeline): graph, Terraform rendering, estimate
5. [validation-and-packaging](.kiro/specs/validation-and-packaging): validators, export gate, zip
6. [diagram](.kiro/specs/diagram): draw.io rendering, validation, parity check
7. [sandbox-deployment](.kiro/specs/sandbox-deployment): plan, approval, apply, teardown
8. [agent-and-admin](.kiro/specs/agent-and-admin): the agent, sign-in, and admin pages

Steering files in `.kiro/steering/` carry the product, tech, structure, and security
rules that apply to all work.

## Roles

Exactly three: `partner_admin`, `consultant`, and `platform_operator`.

## Getting started

Docker is the development environment. Every app, test run, and package install
runs in a container through Docker Compose. Only Terraform runs on the host. You
need Docker Desktop (or Docker Engine with Compose v2) and Terraform 1.10 or later.

There is nothing to run yet. Once the `foundation` spec lands task 1.5:

```
cp .env.example .env
docker compose up --build
```

The full command list is in `.kiro/steering/docker.md`. To begin, start with the
`foundation` tasks.

## Security

Every tenant-scoped row carries `partner_id`, and all data access goes through a
repository layer. See `.kiro/steering/security.md` for the non-negotiable rules.
Do not commit secrets. The workspace MCP config at `.kiro/settings/mcp.json` is
ignored by git because it holds a local access token.
