output "vpc_id" {
  value = aws_vpc.this.id
}

output "public_subnet_ids" {
  value = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "The database subnets."
  value       = aws_subnet.private[*].id
}

output "task_subnet_ids" {
  description = "Where ECS tasks (services and one-off tasks) run."
  value       = var.tasks_in_public_subnets ? aws_subnet.public[*].id : aws_subnet.private[*].id
}

output "assign_public_ip" {
  description = "Whether ECS tasks need a public IP (true when they run in the public subnets)."
  value       = var.tasks_in_public_subnets
}

output "security_group_ids" {
  description = "alb, api, worker, db."
  value = {
    alb    = aws_security_group.alb.id
    api    = aws_security_group.api.id
    worker = aws_security_group.worker.id
    db     = aws_security_group.db.id
  }
}

output "api_port" {
  value = var.api_port
}

output "db_port" {
  value = var.db_port
}
