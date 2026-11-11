output "vpc_id" {
  description = "VPC id."
  value       = aws_vpc.this.id
}

output "vpc_cidr" {
  description = "VPC CIDR block."
  value       = aws_vpc.this.cidr_block
}

output "public_subnet_ids" {
  description = "Public subnet ids, one per zone (both zones, for the load balancer)."
  value       = aws_subnet.public[*].id
}

output "private_app_subnet_ids" {
  description = "Private application subnet ids, one per zone (both zones)."
  value       = aws_subnet.private_app[*].id
}

output "active_private_app_subnet_ids" {
  description = "Private application subnets where tasks run: the first az_count zones."
  value       = slice(aws_subnet.private_app[*].id, 0, var.az_count)
}

output "data_subnet_ids" {
  description = "Isolated data subnet ids, one per zone (both zones, for the database subnet group)."
  value       = aws_subnet.data[*].id
}

output "nat_gateway_count" {
  description = "Number of NAT gateways, equal to az_count."
  value       = length(aws_nat_gateway.this)
}
