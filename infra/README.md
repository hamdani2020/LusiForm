# infra

Terraform for the Lusiform platform itself (dev, pilot, prod): the ECS, RDS, S3,
SQS, and Cognito resources that run Lusiform.

This is separate from `templates/`, which is the product's output. Terraform runs
directly on the host here (1.10 or later, S3 state with `use_lockfile = true`).
