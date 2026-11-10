# worker

The ECS Fargate worker. It pulls jobs from SQS and does the heavy work: renders
Terraform and draw.io, runs validators, runs sandbox plan/apply/destroy, and
packages zips.

- Bundles the pinned Terraform, tflint, and Checkov.
- Plan and apply run in separate tasks with separate roles.
- Python is managed with `uv`; run everything through Docker Compose.

Rendering, validation, and Terraform execution logic belong here.

## The loop (foundation spec)

`python -m app.main` reads its settings from the environment, long-polls the job queue,
and dispatches each message by its `type`. No job handlers exist yet; the specs that need
them (generation, validation, sandbox) add them to `app/jobs.py`.

- A message body is a JSON envelope: `{"type": "...", "job_id": "<uuid>", ...}`.
- A job type with no handler is logged (type, job id, message id) and **left on the
  queue**. It becomes visible again after the visibility timeout and, once the queue has a
  redrive policy (infra, task 11), moves to the dead-letter queue instead of being lost.
  Malformed messages are treated the same way.
- Only the job type, job id and SQS message id are logged, never the message body, which
  can carry intake data.
- Queue errors are logged and retried after a back-off; the worker does not crash-loop.
- SIGTERM or SIGINT stops it after the current long poll (at most `POLL_WAIT_SECONDS`,
  20 by default, inside ECS's 30-second stop timeout).

| Setting | Meaning |
| --- | --- |
| `JOB_QUEUE_URL` or `JOB_QUEUE_NAME` | The job queue (one is required) |
| `ARTIFACT_BUCKET` | Artifact bucket for the job handlers in later specs |
| `POLL_WAIT_SECONDS` | Long-poll wait, 0 to 20 (default 20) |
| `MAX_MESSAGES` | Messages per poll, 1 to 10 (default 1) |
| `ERROR_BACKOFF_SECONDS` | Delay after a queue error (default 5) |

AWS endpoint and credentials come from the standard AWS environment: LocalStack and its
dummy credentials locally, the ECS task role in AWS.

## Task role boundary

The worker task role may read and write **only the artifact bucket and the job queue**
(`security.md`). It has no access to tenant databases: job data arrives in the message
payload. This is enforced in three places:

- **IAM (infra, task 11):** the worker task role grants S3 actions on the artifact bucket
  and SQS receive/delete/visibility actions on the job queue, and nothing else. No RDS, no
  Secrets Manager entry for the database. Sandbox plan and apply get their own roles.
- **Configuration:** the worker has no database setting, and Compose does not pass it
  `DATABASE_URL` (only `api` and `migrate` get it).
- **Code:** `tests/test_boundary.py` fails if worker code imports the API's data package,
  SQLAlchemy, a Postgres driver or Alembic, or if a database library is a worker
  dependency or installed in its environment.

## Commands

```
docker compose run --rm --no-deps worker uv run pytest
docker compose run --rm --no-deps worker uv run ruff check .
docker compose run --rm --no-deps worker uv run mypy .
```
