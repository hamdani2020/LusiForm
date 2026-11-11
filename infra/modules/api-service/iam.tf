# Roles for the API and its one-off tasks.
#
#   execution role  Fargate agent: pull the API image, write the api/migrate/bootstrap
#                   logs, read the database secret. Shared by all three task definitions.
#   task role       the API application: enqueue jobs, read artifacts. Migrate and
#                   bootstrap have no task role (they call no AWS API).
#
# Both trust only ECS acting for this account and region (confused-deputy protection).

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
data "aws_partition" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.name
  partition  = data.aws_partition.current.partition
}

data "aws_iam_policy_document" "ecs_tasks_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:${local.partition}:ecs:${local.region}:${local.account_id}:*"]
    }
  }
}

# --- execution role ---

resource "aws_iam_role" "execution" {
  name               = "${var.name_prefix}-api-execution"
  description        = "Fargate agent for the API, migrate, and bootstrap tasks"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json
}

data "aws_iam_policy_document" "execution" {
  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"] # this action has no resource-level permissions
  }
  statement {
    sid       = "PullApiImage"
    actions   = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
    resources = [var.ecr_repository_arn]
  }
  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = [for g in aws_cloudwatch_log_group.this : "${g.arn}:*"]
  }
  statement {
    sid       = "ReadDatabaseSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.database.master_user_secret_arn]
  }
  statement {
    sid       = "DecryptWithPlatformKey"
    actions   = ["kms:Decrypt"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_role_policy" "execution" {
  name   = "api-execution"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution.json
}

# --- task role ---

resource "aws_iam_role" "task" {
  name               = "${var.name_prefix}-api-task"
  description        = "API application: enqueue jobs, read artifacts"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json
}

data "aws_iam_policy_document" "task" {
  statement {
    sid       = "EnqueueJobs"
    actions   = ["sqs:SendMessage", "sqs:GetQueueUrl", "sqs:GetQueueAttributes"]
    resources = [var.job_queue.arn]
  }
  statement {
    sid       = "ReadArtifacts"
    actions   = ["s3:GetObject"]
    resources = ["${var.artifact_bucket.arn}/*"]
  }
  statement {
    sid       = "UsePlatformKeyForQueueAndArtifacts"
    actions   = ["kms:GenerateDataKey", "kms:Decrypt"]
    resources = [var.kms_key_arn]
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["sqs.${local.region}.amazonaws.com", "s3.${local.region}.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "task" {
  name   = "api-task"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}
