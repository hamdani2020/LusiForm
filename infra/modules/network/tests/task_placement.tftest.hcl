# Where ECS tasks run, and the NAT guard. Uses a mocked AWS provider: no credentials, no
# AWS calls. Run from modules/network: terraform init -backend=false && terraform test

mock_provider "aws" {
  mock_data "aws_availability_zones" {
    defaults = {
      names = ["us-east-1a", "us-east-1b", "us-east-1c"]
    }
  }

  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{}"
    }
  }

  # Mocked resources get random ids; the flow log validates that these are real ARNs.
  mock_resource "aws_cloudwatch_log_group" {
    defaults = {
      arn = "arn:aws:logs:us-east-1:111111111111:log-group:/lusiform/test/vpc-flow-logs"
    }
  }

  mock_resource "aws_iam_role" {
    defaults = {
      arn = "arn:aws:iam::111111111111:role/lusiform-test-vpc-flow-logs"
    }
  }
}

variables {
  name_prefix = "lusiform-test"
  environment = "staging"
  vpc_cidr    = "10.30.0.0/16"
  kms_key_arn = "arn:aws:kms:us-east-1:111111111111:key/test"
}

run "staging_has_no_nat_and_runs_tasks_in_public_subnets" {
  command = plan

  variables {
    nat_gateway_count       = 0
    tasks_in_public_subnets = true
  }

  assert {
    condition     = length(aws_nat_gateway.this) == 0 && length(aws_eip.nat) == 0
    error_message = "staging must not create NAT gateways or their Elastic IPs"
  }

  assert {
    condition     = output.assign_public_ip == true
    error_message = "tasks in public subnets need a public IP for egress"
  }
}

run "staging_task_subnets_are_the_public_ones" {
  command = apply # mocked: resolves subnet ids and routes so they can be compared

  variables {
    nat_gateway_count       = 0
    tasks_in_public_subnets = true
  }

  assert {
    condition     = alltrue([for r in aws_route_table.private : length(r.route) == 0])
    error_message = "without a NAT gateway the private (database) subnets must have no internet route"
  }

  assert {
    condition     = output.task_subnet_ids == aws_subnet.public[*].id
    error_message = "staging tasks must run in the public subnets"
  }

  assert {
    condition     = length(setintersection(output.task_subnet_ids, output.private_subnet_ids)) == 0
    error_message = "staging tasks must not share subnets with the database"
  }
}

run "prod_keeps_tasks_private_behind_a_nat_per_az" {
  command = apply # mocked

  variables {
    environment             = "prod"
    nat_gateway_count       = 2
    tasks_in_public_subnets = false
  }

  assert {
    condition     = length(aws_nat_gateway.this) == 2
    error_message = "prod has one NAT gateway per AZ"
  }

  assert {
    condition     = output.assign_public_ip == false
    error_message = "prod tasks get no public IP"
  }

  assert {
    condition     = output.task_subnet_ids == output.private_subnet_ids
    error_message = "prod tasks must run in the private subnets"
  }
}

run "no_nat_with_private_tasks_is_refused" {
  command = plan

  variables {
    nat_gateway_count       = 0
    tasks_in_public_subnets = false
  }

  expect_failures = [aws_route_table.private]
}

run "only_two_azs_are_used" {
  command = plan

  variables {
    nat_gateway_count       = 0
    tasks_in_public_subnets = true
  }

  assert {
    condition     = length(aws_subnet.public) == 2 && length(aws_subnet.private) == 2
    error_message = "the platform uses exactly two AZs"
  }
}

run "unset_retention_keeps_flow_logs_forever" {
  command = plan

  variables {
    nat_gateway_count       = 0
    tasks_in_public_subnets = true
    log_retention_days      = null
  }

  # No retention attribute at all: CloudWatch keeps the events forever.
  assert {
    condition     = aws_cloudwatch_log_group.flow_logs.retention_in_days == null
    error_message = "with no retention set, the flow-log group must have no expiry configured"
  }
}

run "prod_keeps_its_retention" {
  command = plan

  variables {
    environment             = "prod"
    nat_gateway_count       = 2
    tasks_in_public_subnets = false
    log_retention_days      = 365
  }

  assert {
    condition     = aws_cloudwatch_log_group.flow_logs.retention_in_days == 365
    error_message = "prod flow logs are kept for 365 days"
  }
}
