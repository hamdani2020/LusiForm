# Project structure

Lusiform is a monorepo. Keep code in the directory that matches its role.

```
lusiform/
  api/         FastAPI service: auth, projects, intake, estimates, admin,
               approvals, agent streaming. One service.
  worker/      ECS Fargate worker: renders Terraform and draw.io, runs
               validators, runs sandbox plan/apply/destroy, packages zips.
  web/         React (Vite) + shadcn/ui + Tailwind consultant and admin UI.
  templates/   The startup reference architecture: Terraform modules with
               parameter schemas, versioned.
  infra/       Terraform for the Lusiform platform itself (dev, pilot, prod).
  docs/        PRD and Technical Design (source of truth).
  .kiro/       Steering, specs, hooks, settings.
```

## Where things go

- A new API route, repository, or service → `api/`.
- Rendering, validation, or Terraform execution logic → `worker/`.
- A screen, component, or client state → `web/`.
- A Terraform module or its parameter schema → `templates/`.
- Platform infrastructure (the ECS, RDS, S3, Cognito that run Lusiform) →
  `infra/`. This is separate from `templates/`, which is the product's output.

## Conventions

- Primary keys are UUIDs. Every tenant-scoped table carries `partner_id`.
- All API routes are under `/api`. Write endpoints accept an `Idempotency-Key`
  header.
- Database access goes through a repository layer that applies `partner_id`.
  Queries outside the repository layer are not allowed (see security.md).
- Project versions and template versions are immutable. Edits create new rows,
  never mutate existing ones.
- Prefer the existing stack and patterns over introducing new libraries. If a
  new dependency is needed, pin it (see tech.md).

## Naming

- Pipeline stages use the eight names in product.md, numbered 1 to 8.
- Project versions are integers rendered as `v1`, `v2`, ... Template versions are
  semver, for example `1.0.4`. Keep the two distinct; never show a project
  version as semver or a template version as `vN`.
