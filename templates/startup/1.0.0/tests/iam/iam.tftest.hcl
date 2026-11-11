# IAM module tests, including the policy lint (no wildcard actions, no bare "*" resource).
# Mocked AWS provider: no credentials, no AWS calls.
#
# Every aws_iam_policy in the module must be listed in the lint below; a pytest check fails
# when a policy is added to the module but not here.

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

  # Mocked resources get random ids; the attachments validate that these are real ARNs.
  mock_resource "aws_iam_policy" {
    defaults = {
      arn = "arn:aws:iam::000000000000:policy/mock"
    }
  }
}

variables {
  name_prefix        = "demo-app"
  flow_log_group_arn = "arn:aws:logs:us-east-1:000000000000:log-group:/vpc/demo-app-flow-logs"
  db_secret_arn      = "arn:aws:secretsmanager:us-east-1:000000000000:secret:rds!db-0000-AbCdEf"
}

# --- Policy lint ---------------------------------------------------------------------------

run "no_policy_uses_a_wildcard_action_or_a_bare_wildcard_resource" {
  command = plan

  assert {
    condition = alltrue(flatten([
      for p in [
        aws_iam_policy.task_execution_secret,
        aws_iam_policy.task,
        aws_iam_policy.flow_logs,
        ] : [
        for s in jsondecode(p.policy).Statement : [
          for a in tolist(try(tolist(s.Action), [s.Action])) : !strcontains(a, "*")
        ]
      ]
    ]))
    error_message = "an IAM policy in this module grants a wildcard action"
  }

  assert {
    condition = alltrue(flatten([
      for p in [
        aws_iam_policy.task_execution_secret,
        aws_iam_policy.task,
        aws_iam_policy.flow_logs,
        ] : [
        for s in jsondecode(p.policy).Statement : [
          for r in tolist(try(tolist(s.Resource), [s.Resource])) : r != "*"
        ]
      ]
    ]))
    error_message = "an IAM policy in this module grants a bare * resource"
  }

  assert {
    condition = alltrue(flatten([
      for p in [
        aws_iam_policy.task_execution_secret,
        aws_iam_policy.task,
        aws_iam_policy.flow_logs,
        ] : [
        for s in jsondecode(p.policy).Statement : s.Effect == "Allow"
      ]
    ]))
    error_message = "policies in this module only allow; they never rely on deny statements"
  }
}

# --- Permissions are exactly the declared ones --------------------------------------------

run "task_roles_read_only_the_database_secret" {
  command = plan

  assert {
    condition = (
      jsondecode(aws_iam_policy.task.policy).Statement[0].Resource == [var.db_secret_arn] &&
      jsondecode(aws_iam_policy.task_execution_secret.policy).Statement[0].Resource == [var.db_secret_arn]
    )
    error_message = "both task roles may read the database secret and nothing else"
  }

  assert {
    condition = (
      jsondecode(aws_iam_policy.task.policy).Statement[0].Action == ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"] &&
      jsondecode(aws_iam_policy.task_execution_secret.policy).Statement[0].Action == ["secretsmanager:GetSecretValue"]
    )
    error_message = "task roles must not gain secret actions beyond read"
  }

  assert {
    condition = (
      length(jsondecode(aws_iam_policy.task.policy).Statement) == 1 &&
      length(jsondecode(aws_iam_policy.task_execution_secret.policy).Statement) == 1
    )
    error_message = "each task policy has exactly one statement"
  }
}

run "flow_log_role_writes_only_to_the_flow_log_group" {
  command = plan

  assert {
    condition = (
      jsondecode(aws_iam_policy.flow_logs.policy).Statement[0].Resource == [
        "arn:aws:logs:us-east-1:000000000000:log-group:/vpc/demo-app-flow-logs",
        "arn:aws:logs:us-east-1:000000000000:log-group:/vpc/demo-app-flow-logs:*",
      ]
    )
    error_message = "the flow log role must be limited to the one flow log group"
  }

  assert {
    condition     = toset(jsondecode(aws_iam_policy.flow_logs.policy).Statement[0].Action) == toset(["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"])
    error_message = "the flow log role may only create streams, put events, and describe streams"
  }
}

run "only_the_expected_aws_managed_policies_are_attached" {
  command = plan

  assert {
    condition     = aws_iam_role_policy_attachment.task_execution_managed.policy_arn == "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
    error_message = "the execution role uses the standard ECS execution policy"
  }

  assert {
    condition     = aws_iam_role_policy_attachment.rds_monitoring.policy_arn == "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
    error_message = "the RDS monitoring role uses the standard enhanced monitoring policy"
  }
}

# --- Trust policies --------------------------------------------------------------------------

run "each_role_trusts_one_service_in_this_account_only" {
  command = plan

  assert {
    condition = (
      jsondecode(aws_iam_role.task_execution.assume_role_policy).Statement[0].Principal.Service == "ecs-tasks.amazonaws.com" &&
      jsondecode(aws_iam_role.task.assume_role_policy).Statement[0].Principal.Service == "ecs-tasks.amazonaws.com" &&
      jsondecode(aws_iam_role.flow_logs.assume_role_policy).Statement[0].Principal.Service == "vpc-flow-logs.amazonaws.com" &&
      jsondecode(aws_iam_role.rds_monitoring.assume_role_policy).Statement[0].Principal.Service == "monitoring.rds.amazonaws.com"
    )
    error_message = "each role must trust exactly the AWS service that uses it"
  }

  assert {
    condition = alltrue([
      for r in [
        aws_iam_role.task_execution,
        aws_iam_role.task,
        aws_iam_role.flow_logs,
        aws_iam_role.rds_monitoring,
        ] : (
        length(jsondecode(r.assume_role_policy).Statement) == 1 &&
        jsondecode(r.assume_role_policy).Statement[0].Condition.StringEquals["aws:SourceAccount"] == "000000000000" &&
        can(jsondecode(r.assume_role_policy).Statement[0].Condition.ArnLike["aws:SourceArn"])
      )
    ])
    error_message = "every trust policy must carry aws:SourceAccount and aws:SourceArn conditions"
  }
}

# Applied against the mock so role ARNs resolve and can be compared.
run "outputs_point_at_the_matching_roles" {
  command = apply

  assert {
    condition = (
      output.task_execution_role_arn == aws_iam_role.task_execution.arn &&
      output.task_role_arn == aws_iam_role.task.arn &&
      output.flow_log_role_arn == aws_iam_role.flow_logs.arn &&
      output.rds_monitoring_role_arn == aws_iam_role.rds_monitoring.arn
    )
    error_message = "each output must export the role it is named after"
  }

  assert {
    condition = (
      aws_iam_role_policy_attachment.task_execution_secret.role == aws_iam_role.task_execution.name &&
      aws_iam_role_policy_attachment.task.role == aws_iam_role.task.name &&
      aws_iam_role_policy_attachment.flow_logs.role == aws_iam_role.flow_logs.name
    )
    error_message = "each custom policy must be attached to the role it was written for"
  }
}
