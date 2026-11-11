# Monitoring module tests. Mocked AWS provider: no credentials, no AWS calls.

mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "000000000000"
    }
  }

  mock_data "aws_partition" {
    defaults = {
      partition = "aws"
    }
  }

  mock_data "aws_region" {
    defaults = {
      name = "us-east-1"
    }
  }

  mock_resource "aws_kms_key" {
    defaults = {
      arn = "arn:aws:kms:us-east-1:000000000000:key/00000000-0000-0000-0000-000000000000"
    }
  }
}

variables {
  name_prefix            = "demo-app"
  log_retention_days     = 30
  alb_arn_suffix         = "app/demo-app-alb/0123456789abcdef"
  ecs_cluster_name       = "demo-app-cluster"
  ecs_service_name       = "demo-app-app"
  db_instance_identifier = "demo-app-db"
  db_storage_gb          = 20
}

# Applied against the mock so the key ARN resolves and can be compared.
run "log_groups_are_encrypted_named_and_retained" {
  command = apply

  assert {
    condition     = aws_cloudwatch_log_group.ecs.name == "/ecs/demo-app" && aws_cloudwatch_log_group.flow_logs.name == "/vpc/demo-app-flow-logs"
    error_message = "log group names must be derived from the name prefix"
  }

  assert {
    condition = (
      aws_cloudwatch_log_group.ecs.retention_in_days == 30 &&
      aws_cloudwatch_log_group.flow_logs.retention_in_days == 30
    )
    error_message = "both log groups must use log_retention_days"
  }

  assert {
    condition = (
      aws_cloudwatch_log_group.ecs.kms_key_id == aws_kms_key.logs.arn &&
      aws_cloudwatch_log_group.flow_logs.kms_key_id == aws_kms_key.logs.arn
    )
    error_message = "both log groups must be encrypted with the module's customer-managed key"
  }
}

run "retention_follows_the_parameter" {
  command = plan

  variables {
    log_retention_days = 365
  }

  assert {
    condition     = aws_cloudwatch_log_group.ecs.retention_in_days == 365
    error_message = "log_retention_days must reach the log group"
  }
}

run "key_rotates_and_policy_is_scoped" {
  command = plan

  assert {
    condition     = aws_kms_key.logs.enable_key_rotation == true
    error_message = "key rotation must be on"
  }

  assert {
    condition     = length(jsondecode(aws_kms_key.logs.policy).Statement) == 2
    error_message = "the key policy must have exactly the account administration and CloudWatch Logs statements"
  }

  assert {
    condition = alltrue([
      for s in jsondecode(aws_kms_key.logs.policy).Statement :
      try(s.Principal == "*" || s.Principal.AWS == "*", false) == false
    ])
    error_message = "no key policy statement may use a wildcard principal"
  }

  assert {
    condition = (
      jsondecode(aws_kms_key.logs.policy).Statement[1].Principal.Service == "logs.us-east-1.amazonaws.com" &&
      jsondecode(aws_kms_key.logs.policy).Statement[1].Condition.ArnEquals["kms:EncryptionContext:aws:logs:arn"] == [
        "arn:aws:logs:us-east-1:000000000000:log-group:/ecs/demo-app",
        "arn:aws:logs:us-east-1:000000000000:log-group:/vpc/demo-app-flow-logs",
      ]
    )
    error_message = "CloudWatch Logs may use the key only for this project's two log groups"
  }

  assert {
    condition     = aws_kms_alias.logs.name == "alias/demo-app-logs"
    error_message = "the key alias must be derived from the name prefix"
  }
}

run "four_alarms_watch_the_right_metrics" {
  command = plan

  assert {
    condition = (
      aws_cloudwatch_metric_alarm.alb_5xx.namespace == "AWS/ApplicationELB" &&
      aws_cloudwatch_metric_alarm.alb_5xx.metric_name == "HTTPCode_ELB_5XX_Count" &&
      aws_cloudwatch_metric_alarm.alb_5xx.dimensions.LoadBalancer == "app/demo-app-alb/0123456789abcdef"
    )
    error_message = "the 5xx alarm must watch the load balancer"
  }

  assert {
    condition = (
      aws_cloudwatch_metric_alarm.ecs_cpu.namespace == "AWS/ECS" &&
      aws_cloudwatch_metric_alarm.ecs_cpu.metric_name == "CPUUtilization" &&
      aws_cloudwatch_metric_alarm.ecs_cpu.dimensions.ClusterName == "demo-app-cluster" &&
      aws_cloudwatch_metric_alarm.ecs_cpu.dimensions.ServiceName == "demo-app-app"
    )
    error_message = "the ECS CPU alarm must watch the service"
  }

  assert {
    condition = (
      aws_cloudwatch_metric_alarm.rds_cpu.namespace == "AWS/RDS" &&
      aws_cloudwatch_metric_alarm.rds_cpu.metric_name == "CPUUtilization" &&
      aws_cloudwatch_metric_alarm.rds_cpu.dimensions.DBInstanceIdentifier == "demo-app-db"
    )
    error_message = "the RDS CPU alarm must watch the database"
  }

  assert {
    condition = (
      aws_cloudwatch_metric_alarm.rds_free_storage.metric_name == "FreeStorageSpace" &&
      aws_cloudwatch_metric_alarm.rds_free_storage.comparison_operator == "LessThanThreshold" &&
      aws_cloudwatch_metric_alarm.rds_free_storage.dimensions.DBInstanceIdentifier == "demo-app-db"
    )
    error_message = "the free storage alarm must fire when space drops below the threshold"
  }

  assert {
    condition     = length(output.alarm_names) == 4
    error_message = "exactly four alarms are created"
  }
}

run "free_storage_threshold_is_twenty_percent_of_allocated_in_bytes" {
  command = plan

  assert {
    condition     = aws_cloudwatch_metric_alarm.rds_free_storage.threshold == 4294967296
    error_message = "20 GB allocated means an alarm below 4 GiB (4294967296 bytes)"
  }
}

run "free_storage_threshold_scales_with_storage" {
  command = plan

  variables {
    db_storage_gb = 1000
  }

  assert {
    condition     = aws_cloudwatch_metric_alarm.rds_free_storage.threshold == 214748364800
    error_message = "1000 GB allocated means an alarm below 200 GiB (214748364800 bytes)"
  }
}

run "alarms_notify_nobody_by_default_and_follow_supplied_actions" {
  command = plan

  assert {
    condition = alltrue([
      for a in [
        aws_cloudwatch_metric_alarm.alb_5xx,
        aws_cloudwatch_metric_alarm.ecs_cpu,
        aws_cloudwatch_metric_alarm.rds_cpu,
        aws_cloudwatch_metric_alarm.rds_free_storage,
      ] : length(a.alarm_actions) == 0
    ])
    error_message = "the template creates no SNS topic, so alarms have no actions by default"
  }
}

run "supplied_alarm_actions_reach_every_alarm" {
  command = plan

  variables {
    alarm_action_arns = ["arn:aws:sns:us-east-1:000000000000:ops"]
  }

  assert {
    condition = alltrue([
      for a in [
        aws_cloudwatch_metric_alarm.alb_5xx,
        aws_cloudwatch_metric_alarm.ecs_cpu,
        aws_cloudwatch_metric_alarm.rds_cpu,
        aws_cloudwatch_metric_alarm.rds_free_storage,
      ] : contains(a.alarm_actions, "arn:aws:sns:us-east-1:000000000000:ops")
    ])
    error_message = "alarm_action_arns must be set on every alarm"
  }
}

run "rejects_a_retention_the_ui_does_not_offer" {
  command = plan

  variables {
    log_retention_days = 60
  }

  expect_failures = [var.log_retention_days]
}

run "rejects_storage_outside_the_schema_range" {
  command = plan

  variables {
    db_storage_gb = 10
  }

  expect_failures = [var.db_storage_gb]
}
