# Network module tests. Mocked AWS provider: no credentials, no AWS calls.
# Run from modules/network: terraform init -backend=false && terraform test -test-directory=<this dir>

mock_provider "aws" {}

variables {
  name_prefix              = "demo-app"
  availability_zones       = ["us-east-1a", "us-east-1b"]
  flow_log_destination_arn = "arn:aws:logs:us-east-1:000000000000:log-group:/vpc/demo-app-flow-logs"
  flow_log_role_arn        = "arn:aws:iam::000000000000:role/demo-app-vpc-flow-logs"
}

run "two_zones_have_two_nat_gateways_and_all_subnets" {
  command = plan

  variables {
    az_count = 2
  }

  assert {
    condition     = length(aws_nat_gateway.this) == 2 && length(aws_eip.nat) == 2
    error_message = "az_count = 2 must create one NAT gateway and one Elastic IP per zone"
  }

  assert {
    condition     = output.nat_gateway_count == 2
    error_message = "nat_gateway_count must equal az_count"
  }

  assert {
    condition = (
      length(aws_subnet.public) == 2 &&
      length(aws_subnet.private_app) == 2 &&
      length(aws_subnet.data) == 2
    )
    error_message = "subnets are always created in two zones for every tier"
  }

  assert {
    condition     = length(output.active_private_app_subnet_ids) == 2
    error_message = "both application subnets are active when az_count = 2"
  }

  assert {
    condition     = length(aws_route.private_app_nat) == 2
    error_message = "each active application subnet needs its own NAT route"
  }
}

run "one_zone_has_one_nat_gateway_but_still_two_subnets_per_tier" {
  command = plan

  variables {
    az_count = 1
  }

  assert {
    condition     = length(aws_nat_gateway.this) == 1 && length(aws_eip.nat) == 1
    error_message = "az_count = 1 must create exactly one NAT gateway and one Elastic IP"
  }

  assert {
    condition     = output.nat_gateway_count == 1
    error_message = "nat_gateway_count must equal az_count"
  }

  assert {
    condition = (
      length(aws_subnet.public) == 2 &&
      length(aws_subnet.private_app) == 2 &&
      length(aws_subnet.data) == 2
    )
    error_message = "the load balancer and database subnet group need two zones even when az_count = 1"
  }

  assert {
    condition     = length(output.active_private_app_subnet_ids) == 1
    error_message = "only the first zone's application subnet is active when az_count = 1"
  }

  assert {
    condition     = length(aws_route.private_app_nat) == 1
    error_message = "only the active zone gets a NAT route"
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
    condition     = [for s in aws_subnet.private_app : s.cidr_block] == ["10.0.10.0/24", "10.0.11.0/24"]
    error_message = "application subnets must be 10.0.10.0/24 and 10.0.11.0/24"
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
    condition = alltrue([
      for r in concat([aws_route.public_internet], aws_route.private_app_nat) :
      r.route_table_id != aws_route_table.data.id
    ])
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

  assert {
    condition = alltrue([
      for i, r in aws_route.private_app_nat :
      r.nat_gateway_id == aws_nat_gateway.this[i].id && r.route_table_id == aws_route_table.private_app[i].id
    ])
    error_message = "each application route table must use the NAT gateway in its own zone"
  }

  assert {
    condition     = alltrue([for i, n in aws_nat_gateway.this : n.subnet_id == aws_subnet.public[i].id])
    error_message = "NAT gateways must sit in the public subnet of their own zone"
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
