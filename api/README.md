# api

The FastAPI service. It is one service and handles auth, projects, intake,
estimates, admin, approvals, and agent streaming.

- All routes live under `/api`. Write endpoints accept an `Idempotency-Key` header.
- Database access goes through a repository layer that applies `partner_id`.
- Runs on ECS Fargate. Python is managed with `uv`; run everything through Docker
  Compose (see `.kiro/steering/docker.md`).

New routes, repositories, and services belong here.
