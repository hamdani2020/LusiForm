# Network module tests. Mocked AWS provider: no credentials, no AWS calls.
# Run from modules/network: terraform init -backend=false && terraform test -test-directory=<this dir>

mock_provider "aws" {}

variables {
  name_prefix              = "lf-demo"
  availability_zones       = ["us-east-1a", "us-east-1b"]
  flow_log_destination_arn = "arn:aws:logs:us-east-1:000000000000:log-group:/vpc/lf-demo-flow-logs"
  flow_log_role_arn        = "arn:aws:iam::000000000000:role/lf-demo-vpc-flow-logs"
}

run "two_zones_run_tasks_in_both_public_subnets" {
  command = plan

  variables {
    az_count = 2
  }

  assert {
    condition     = length(aws_subnet.public) == 2 && length(aws_subnet.data) == 2
    error_message = "subnets are always created in two zones for every tier"
  }

  assert {
    condition     = length(output.active_public_subnet_ids) == 2
    error_message = "both public subnets are active when az_count = 2"
  }
}

run "one_zone_runs_tasks_in_one_public_subnet_but_still_has_two_subnets_per_tier" {
  command = plan

  variables {
    az_count = 1
  }

  assert {
    condition     = length(aws_subnet.public) == 2 && length(aws_subnet.data) == 2
    error_message = "the load balancer and database subnet group need two zones even when az_count = 1"
  }

  assert {
    condition     = length(output.active_public_subnet_ids) == 1
    error_message = "only the first zone's public subnet is active when az_count = 1"
  }
}

run "address_plan_matches_the_architecture_diagram" {
  command = plan

  variables {
    az_count = 2
  }

  assert {
    condition     = aws_vpc.this.cidr_block == "10.0.0.0/16"
    error_message = "the VPC range is fixed at 10.0.0.0/16"
  }

  assert {
    condition     = [for s in aws_subnet.public : s.cidr_block] == ["10.0.1.0/24", "10.0.2.0/24"]
    error_message = "public subnets must be 10.0.1.0/24 and 10.0.2.0/24"
  }

  assert {
    condition     = [for s in aws_subnet.data : s.cidr_block] == ["10.0.20.0/24", "10.0.21.0/24"]
    error_message = "data subnets must be 10.0.20.0/24 and 10.0.21.0/24"
  }

  assert {
    condition     = [for s in aws_subnet.public : s.availability_zone] == ["us-east-1a", "us-east-1b"]
    error_message = "subnets must use the zones passed in, in order"
  }

  assert {
    condition     = alltrue([for s in aws_subnet.public : s.map_public_ip_on_launch == false])
    error_message = "public subnets must not auto-assign public IPs"
  }
}

# Applied against the mock so resource ids resolve and routes can be compared.
run "data_subnets_have_no_route_to_the_internet" {
  command = apply

  variables {
    az_count = 2
  }

  assert {
    condition     = aws_route.public_internet.route_table_id != aws_route_table.data.id
    error_message = "no route may be added to the data route table"
  }

  assert {
    condition     = alltrue([for a in aws_route_table_association.data : a.route_table_id == aws_route_table.data.id])
    error_message = "both data subnets must use the route table that has no internet route"
  }

  assert {
    condition     = aws_route.public_internet.gateway_id == aws_internet_gateway.this.id
    error_message = "the public route table sends the default route to the internet gateway"
  }
}

run "default_security_group_has_no_rules_and_flow_logs_are_on" {
  command = plan

  variables {
    az_count = 2
  }

  assert {
    condition     = length(aws_default_security_group.default.ingress) == 0 && length(aws_default_security_group.default.egress) == 0
    error_message = "the default security group must have no rules"
  }

  assert {
    condition = (
      aws_flow_log.this.traffic_type == "ALL" &&
      aws_flow_log.this.log_destination_type == "cloud-watch-logs" &&
      aws_flow_log.this.log_destination == var.flow_log_destination_arn &&
      aws_flow_log.this.iam_role_arn == var.flow_log_role_arn
    )
    error_message = "flow logs must record all traffic to the supplied CloudWatch log group using the supplied role"
  }
}

run "rejects_three_zones" {
  command = plan

  variables {
    az_count = 3
  }

  expect_failures = [var.az_count]
}

run "rejects_duplicate_zone_names" {
  command = plan

  variables {
    az_count           = 2
    availability_zones = ["us-east-1a", "us-east-1a"]
  }

  expect_failures = [var.availability_zones]
}

run "rejects_a_bad_name_prefix" {
  command = plan

  variables {
    az_count    = 2
    name_prefix = "Demo_App"
  }

  expect_failures = [var.name_prefix]
}

run "rejects_a_name_prefix_without_the_lf_prefix" {
  command = plan

  variables {
    az_count    = 2
    name_prefix = "demo-app"
  }

  expect_failures = [var.name_prefix]
}

run "rejects_a_name_prefix_longer_than_24_characters" {
  command = plan

  variables {
    az_count    = 2
    name_prefix = "lf-aaaaaaaaaaaaaaaaaaaaaa"
  }

  expect_failures = [var.name_prefix]
}

run "accepts_a_24_character_name_prefix" {
  command = plan

  variables {
    az_count    = 2
    name_prefix = "lf-aaaaaaaaaaaaaaaaaaaaa"
  }
}
