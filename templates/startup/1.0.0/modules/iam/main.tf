# IAM: least-privilege roles for ECS, VPC flow logs, and RDS enhanced monitoring.
#
# No policy here uses a wildcard action or a bare "*" resource; the only wildcard is the
# ":*" log-stream suffix on a single named log group. Trust policies are limited to the
# AWS service that assumes the role and to this account, to prevent confused-deputy use.
#
# The caller identity lookup is one local STS call at plan time, so no account ID is
# written into the files.

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_region" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
  region     = data.aws_region.current.name

  managed_policy_prefix = "arn:${local.partition}:iam::aws:policy/service-role"
}

# --- ECS task execution role: pulls the image, writes logs, injects the DB secret ---

resource "aws_iam_role" "task_execution" {
  name = "${var.name_prefix}-ecs-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = local.account_id }
        ArnLike      = { "aws:SourceArn" = "arn:${local.partition}:ecs:${local.region}:${local.account_id}:*" }
      }
    }]
  })

  tags = merge(var.tags, { Name = "${var.name_prefix}-ecs-execution" })
}

resource "aws_iam_role_policy_attachment" "task_execution_managed" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "${local.managed_policy_prefix}/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_policy" "task_execution_secret" {
  name        = "${var.name_prefix}-ecs-execution-secret"
  description = "Lets ECS inject the database credentials secret into the task."

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "ReadDatabaseSecret"
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = [var.db_secret_arn]
    }]
  })

  tags = merge(var.tags, { Name = "${var.name_prefix}-ecs-execution-secret" })
}

resource "aws_iam_role_policy_attachment" "task_execution_secret" {
  role       = aws_iam_role.task_execution.name
  policy_arn = aws_iam_policy.task_execution_secret.arn
}

# --- ECS task role: what the running application may do ---

resource "aws_iam_role" "task" {
  name = "${var.name_prefix}-ecs-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = local.account_id }
        ArnLike      = { "aws:SourceArn" = "arn:${local.partition}:ecs:${local.region}:${local.account_id}:*" }
      }
    }]
  })

  tags = merge(var.tags, { Name = "${var.name_prefix}-ecs-task" })
}

resource "aws_iam_policy" "task" {
  name        = "${var.name_prefix}-ecs-task"
  description = "Read access to the database credentials secret, and nothing else."

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "ReadDatabaseSecret"
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
      Resource = [var.db_secret_arn]
    }]
  })

  tags = merge(var.tags, { Name = "${var.name_prefix}-ecs-task" })
}

resource "aws_iam_role_policy_attachment" "task" {
  role       = aws_iam_role.task.name
  policy_arn = aws_iam_policy.task.arn
}

# --- VPC flow log role: writes to the one flow log group ---

resource "aws_iam_role" "flow_logs" {
  name = "${var.name_prefix}-vpc-flow-logs"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "vpc-flow-logs.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = local.account_id }
        ArnLike      = { "aws:SourceArn" = "arn:${local.partition}:ec2:${local.region}:${local.account_id}:vpc-flow-log/*" }
      }
    }]
  })

  tags = merge(var.tags, { Name = "${var.name_prefix}-vpc-flow-logs" })
}

resource "aws_iam_policy" "flow_logs" {
  name        = "${var.name_prefix}-vpc-flow-logs"
  description = "Write VPC flow logs to the project flow log group."

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "WriteFlowLogs"
      Effect   = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
      Resource = [var.flow_log_group_arn, "${var.flow_log_group_arn}:*"]
    }]
  })

  tags = merge(var.tags, { Name = "${var.name_prefix}-vpc-flow-logs" })
}

resource "aws_iam_role_policy_attachment" "flow_logs" {
  role       = aws_iam_role.flow_logs.name
  policy_arn = aws_iam_policy.flow_logs.arn
}

# --- RDS enhanced monitoring role ---

resource "aws_iam_role" "rds_monitoring" {
  name = "${var.name_prefix}-rds-monitoring"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "monitoring.rds.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = local.account_id }
        ArnLike      = { "aws:SourceArn" = "arn:${local.partition}:rds:${local.region}:${local.account_id}:db:*" }
      }
    }]
  })

  tags = merge(var.tags, { Name = "${var.name_prefix}-rds-monitoring" })
}

resource "aws_iam_role_policy_attachment" "rds_monitoring" {
  role       = aws_iam_role.rds_monitoring.name
  policy_arn = "${local.managed_policy_prefix}/AmazonRDSEnhancedMonitoringRole"
}
