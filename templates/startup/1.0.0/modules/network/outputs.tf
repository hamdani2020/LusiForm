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

output "active_public_subnet_ids" {
  description = "Public subnets where tasks run: the first az_count zones."
  value       = slice(aws_subnet.public[*].id, 0, var.az_count)
}

output "data_subnet_ids" {
  description = "Isolated data subnet ids, one per zone (both zones, for the database subnet group)."
  value       = aws_subnet.data[*].id
}
