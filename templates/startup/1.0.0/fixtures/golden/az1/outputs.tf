output "alb_dns_name" {
  description = "Public DNS name of the load balancer."
  value       = module.compute.alb_dns_name
}

output "vpc_id" {
  description = "VPC id."
  value       = module.network.vpc_id
}

output "ecs_cluster_name" {
  description = "ECS cluster name."
  value       = module.compute.cluster_name
}

output "ecs_service_name" {
  description = "ECS service name."
  value       = module.compute.service_name
}

output "ecs_log_group_name" {
  description = "CloudWatch log group for the application containers."
  value       = module.monitoring.ecs_log_group_name
}

output "database_address" {
  description = "Database host name."
  value       = module.database.address
}

output "database_port" {
  description = "Database port."
  value       = module.database.port
}

output "database_name" {
  description = "Name of the initial database."
  value       = module.database.db_name
}

output "database_secret_arn" {
  description = "Secrets Manager secret that holds the database credentials. The ARN only; the secret value is never output."
  value       = module.database.master_user_secret_arn
}
