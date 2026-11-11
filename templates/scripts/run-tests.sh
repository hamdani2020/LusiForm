#!/usr/bin/env sh
# Run the template test suite inside the worker container, which carries the pinned
# Terraform, tflint, and Checkov (see worker/Dockerfile). Used locally and by CI.
# Extra arguments are passed to pytest.
set -eu

cd "$(dirname "$0")/../.."

exec docker compose run --rm --no-deps -w /app/templates worker \
  uv run --frozen --project /app/worker pytest "$@"
