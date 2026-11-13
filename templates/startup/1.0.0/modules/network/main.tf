# Network: one VPC with public and isolated data subnets. There is no NAT gateway.
#
# Application tasks run in the public subnets with a public IP address, so they can reach
# the image registry and AWS APIs through the internet gateway. What protects them is their
# security group (see the compute module): it admits traffic from the load balancer only.
# Data subnets have no route to the internet.
#
# Subnets are always created in two Availability Zones, because an Application Load
# Balancer and an RDS subnet group each need subnets in at least two zones. `az_count`
# controls the workload instead: which public subnets run tasks (see outputs) and, in the
# database module, whether there is a standby.

locals {
  # Fixed address plan, matching the Architecture-stage diagram. Not a parameter.
  vpc_cidr = "10.0.0.0/16"

  zone_indexes = [0, 1]
}

resource "aws_vpc" "this" {
  cidr_block           = local.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = merge(var.tags, { Name = "${var.name_prefix}-vpc" })
}

# Lock down the default security group: no rules, so nothing can use it by accident.
resource "aws_default_security_group" "default" {
  vpc_id = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${var.name_prefix}-default-sg" })
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${var.name_prefix}-igw" })
}

resource "aws_subnet" "public" {
  count = length(local.zone_indexes)

  vpc_id                  = aws_vpc.this.id
  availability_zone       = var.availability_zones[count.index]
  cidr_block              = cidrsubnet(local.vpc_cidr, 8, 1 + count.index)
  map_public_ip_on_launch = false

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-public-${var.availability_zones[count.index]}"
    Tier = "public"
  })
}

resource "aws_subnet" "data" {
  count = length(local.zone_indexes)

  vpc_id            = aws_vpc.this.id
  availability_zone = var.availability_zones[count.index]
  cidr_block        = cidrsubnet(local.vpc_cidr, 8, 20 + count.index)

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-data-${var.availability_zones[count.index]}"
    Tier = "data"
  })
}

# Public: default route to the internet gateway.
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${var.name_prefix}-public" })
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this.id
}

resource "aws_route_table_association" "public" {
  count = length(local.zone_indexes)

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# Data: local routes only. No route to the internet or to a NAT gateway.
resource "aws_route_table" "data" {
  vpc_id = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${var.name_prefix}-data" })
}

resource "aws_route_table_association" "data" {
  count = length(local.zone_indexes)

  subnet_id      = aws_subnet.data[count.index].id
  route_table_id = aws_route_table.data.id
}

# Flow logs go to a KMS-encrypted CloudWatch log group owned by the monitoring module.
resource "aws_flow_log" "this" {
  vpc_id                   = aws_vpc.this.id
  traffic_type             = "ALL"
  log_destination_type     = "cloud-watch-logs"
  log_destination          = var.flow_log_destination_arn
  iam_role_arn             = var.flow_log_role_arn
  max_aggregation_interval = 600

  tags = merge(var.tags, { Name = "${var.name_prefix}-flow-log" })
}
