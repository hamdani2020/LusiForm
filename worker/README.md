# worker

The ECS Fargate worker. It pulls jobs from SQS and does the heavy work: renders
Terraform and draw.io, runs validators, runs sandbox plan/apply/destroy, and
packages zips.

- Bundles the pinned Terraform, tflint, and Checkov.
- Plan and apply run in separate tasks with separate roles.
- Python is managed with `uv`; run everything through Docker Compose.

Rendering, validation, and Terraform execution logic belong here.
