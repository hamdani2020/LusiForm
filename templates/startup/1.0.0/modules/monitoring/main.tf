# Monitoring: a customer-managed KMS key, the KMS-encrypted log groups, and a small set
# of alarms. No dashboards in the MVP.
#
# The caller identity lookup is one local STS call at plan time. It is needed for the
# key policy's account root statement so no account ID is written into the files.

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_region" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
  region     = data.aws_region.current.name

  ecs_log_group_name  = "/ecs/${var.name_prefix}"
  flow_log_group_name = "/vpc/${var.name_prefix}-flow-logs"

  log_group_arn_prefix = "arn:${local.partition}:logs:${local.region}:${local.account_id}:log-group"

  # 20 percent of allocated storage, in bytes (FreeStorageSpace is reported in bytes).
  # Integer arithmetic only, so the threshold is exact.
  free_storage_threshold_bytes = var.db_storage_gb * 1073741824 / 5
}

resource "aws_kms_key" "logs" {
  description             = "${var.name_prefix} CloudWatch log group encryption"
  enable_key_rotation     = true
  deletion_window_in_days = 7

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "EnableAccountAdministration"
        Effect    = "Allow"
        Principal = { AWS = "arn:${local.partition}:iam::${local.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        # CloudWatch Logs may use the key only for this project's log groups.
        Sid       = "AllowCloudWatchLogsForProjectLogGroups"
        Effect    = "Allow"
        Principal = { Service = "logs.${local.region}.amazonaws.com" }
        Action = [
          "kms:Encrypt*",
          "kms:Decrypt*",
          "kms:ReEncrypt*",
          "kms:GenerateDataKey*",
          "kms:Describe*",
        ]
        Resource = "*"
        Condition = {
          ArnEquals = {
            "kms:EncryptionContext:aws:logs:arn" = [
              "${local.log_group_arn_prefix}:${local.ecs_log_group_name}",
              "${local.log_group_arn_prefix}:${local.flow_log_group_name}",
            ]
          }
        }
      },
    ]
  })

  tags = merge(var.tags, { Name = "${var.name_prefix}-logs-key" })
}

resource "aws_kms_alias" "logs" {
  name          = "alias/${var.name_prefix}-logs"
  target_key_id = aws_kms_key.logs.key_id
}

resource "aws_cloudwatch_log_group" "ecs" {
  name              = local.ecs_log_group_name
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.logs.arn

  tags = merge(var.tags, { Name = "${var.name_prefix}-ecs-logs" })
}

resource "aws_cloudwatch_log_group" "flow_logs" {
  name              = local.flow_log_group_name
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.logs.arn

  tags = merge(var.tags, { Name = "${var.name_prefix}-flow-logs" })
}

resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  alarm_name          = "${var.name_prefix}-alb-5xx"
  alarm_description   = "The load balancer returned 5xx responses."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_ELB_5XX_Count"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 10
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.alarm_action_arns
  ok_actions          = var.alarm_action_arns

  dimensions = {
    LoadBalancer = var.alb_arn_suffix
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-alb-5xx" })
}

resource "aws_cloudwatch_metric_alarm" "ecs_cpu" {
  alarm_name          = "${var.name_prefix}-ecs-cpu"
  alarm_description   = "ECS service CPU is above 85 percent."
  namespace           = "AWS/ECS"
  metric_name         = "CPUUtilization"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 3
  threshold           = 85
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.alarm_action_arns
  ok_actions          = var.alarm_action_arns

  dimensions = {
    ClusterName = var.ecs_cluster_name
    ServiceName = var.ecs_service_name
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-ecs-cpu" })
}

resource "aws_cloudwatch_metric_alarm" "rds_cpu" {
  alarm_name          = "${var.name_prefix}-rds-cpu"
  alarm_description   = "Database CPU is above 80 percent."
  namespace           = "AWS/RDS"
  metric_name         = "CPUUtilization"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 3
  threshold           = 80
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.alarm_action_arns
  ok_actions          = var.alarm_action_arns

  dimensions = {
    DBInstanceIdentifier = var.db_instance_identifier
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-rds-cpu" })
}

resource "aws_cloudwatch_metric_alarm" "rds_free_storage" {
  alarm_name          = "${var.name_prefix}-rds-free-storage"
  alarm_description   = "Database free storage is below 20 percent of allocated storage."
  namespace           = "AWS/RDS"
  metric_name         = "FreeStorageSpace"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 1
  threshold           = local.free_storage_threshold_bytes
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.alarm_action_arns
  ok_actions          = var.alarm_action_arns

  dimensions = {
    DBInstanceIdentifier = var.db_instance_identifier
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-rds-free-storage" })
}
