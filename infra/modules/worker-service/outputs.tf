output "service_name" {
  value = aws_ecs_service.this.name
}

output "task_role_arn" {
  description = "The sandbox-deployment spec will let partner sandbox roles trust this."
  value       = aws_iam_role.task.arn
}

output "execution_role_arn" {
  value = aws_iam_role.execution.arn
}

output "log_group" {
  value = aws_cloudwatch_log_group.this.name
}
