# Roles for the worker.
#
#   execution role  Fargate agent: pull the worker image, write the worker logs.
#   task role       the worker application: the job queue and the artifact bucket only
#                   (security.md). No database secret, no sts:AssumeRole yet (sandbox
#                   plan/apply roles arrive with the sandbox-deployment spec).
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
  name               = "${var.name_prefix}-worker-execution"
  description        = "Fargate agent for the worker task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json
}

data "aws_iam_policy_document" "execution" {
  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"] # this action has no resource-level permissions
  }
  statement {
    sid       = "PullWorkerImage"
    actions   = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
    resources = [var.ecr_repository_arn]
  }
  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.this.arn}:*"]
  }
  statement {
    sid       = "DecryptImageLayers"
    actions   = ["kms:Decrypt"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_role_policy" "execution" {
  name   = "worker-execution"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution.json
}

# --- task role ---

resource "aws_iam_role" "task" {
  name               = "${var.name_prefix}-worker-task"
  description        = "Worker application: artifact bucket and job queue only"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json
}

data "aws_iam_policy_document" "task" {
  statement {
    sid = "ConsumeJobs"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:ChangeMessageVisibility",
      "sqs:GetQueueUrl",
      "sqs:GetQueueAttributes",
    ]
    resources = [var.job_queue.arn]
  }
  statement {
    sid       = "ListArtifacts"
    actions   = ["s3:ListBucket"]
    resources = [var.artifact_bucket.arn]
  }
  statement {
    sid       = "ReadWriteArtifacts"
    actions   = ["s3:GetObject", "s3:PutObject"]
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
  name   = "worker-task"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}
