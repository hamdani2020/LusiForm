#!/bin/sh
# Runs inside LocalStack when it is ready. Local dev resources only.
set -eu
awslocal s3 mb s3://lusiform-artifacts-local || true
awslocal sqs create-queue --queue-name lusiform-jobs-local || true
