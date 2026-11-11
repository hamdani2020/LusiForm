# Network: one VPC with public, private application, and isolated data subnets.
#
# Subnets are always created in two Availability Zones, because an Application Load
# Balancer and an RDS subnet group each need subnets in at least two zones. `az_count`
# controls the workload instead: how many NAT gateways exist and which application
# subnets are active (see outputs). Data subnets have no route to the internet.

locals {
  # Fixed address plan, matching the Architecture-stage diagram. Not a parameter.
  vpc_cidr = "10.0.0.0/16"

  zone_indexes = [0, 1]
  active_zones = range(var.az_count)
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

resource "aws_subnet" "private_app" {
  count = length(local.zone_indexes)

  vpc_id            = aws_vpc.this.id
  availability_zone = var.availability_zones[count.index]
  cidr_block        = cidrsubnet(local.vpc_cidr, 8, 10 + count.index)

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-app-${var.availability_zones[count.index]}"
    Tier = "private-app"
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

# NAT: one gateway per active zone, so a zone outage cannot cut egress for the other.
resource "aws_eip" "nat" {
  count = var.az_count

  domain = "vpc"

  tags = merge(var.tags, { Name = "${var.name_prefix}-nat-${var.availability_zones[count.index]}" })

  depends_on = [aws_internet_gateway.this]
}

resource "aws_nat_gateway" "this" {
  count = var.az_count

  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id

  tags = merge(var.tags, { Name = "${var.name_prefix}-nat-${var.availability_zones[count.index]}" })

  depends_on = [aws_internet_gateway.this]
}

# Private application: one route table per zone. Only active zones get a default route
# through their own NAT gateway; the inactive zone's subnet has local routes only.
resource "aws_route_table" "private_app" {
  count = length(local.zone_indexes)

  vpc_id = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${var.name_prefix}-app-${var.availability_zones[count.index]}" })
}

resource "aws_route" "private_app_nat" {
  count = var.az_count

  route_table_id         = aws_route_table.private_app[count.index].id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.this[count.index].id
}

resource "aws_route_table_association" "private_app" {
  count = length(local.zone_indexes)

  subnet_id      = aws_subnet.private_app[count.index].id
  route_table_id = aws_route_table.private_app[count.index].id
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
