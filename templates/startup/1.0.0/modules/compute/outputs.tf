output "alb_dns_name" {
  description = "Public DNS name of the load balancer."
  value       = aws_lb.this.dns_name
}

output "alb_arn_suffix" {
  description = "Load balancer ARN suffix, used by CloudWatch alarms."
  value       = aws_lb.this.arn_suffix
}

output "cluster_name" {
  description = "ECS cluster name."
  value       = aws_ecs_cluster.this.name
}

output "service_name" {
  description = "ECS service name."
  value       = aws_ecs_service.app.name
}

output "task_security_group_id" {
  description = "Security group of the tasks, the only source the database accepts."
  value       = aws_security_group.tasks.id
}

output "alb_security_group_id" {
  description = "Load balancer security group id."
  value       = aws_security_group.alb.id
}
