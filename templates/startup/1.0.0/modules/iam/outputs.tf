output "task_execution_role_arn" {
  description = "ECS task execution role ARN."
  value       = aws_iam_role.task_execution.arn
}

output "task_role_arn" {
  description = "ECS task role ARN."
  value       = aws_iam_role.task.arn
}

output "flow_log_role_arn" {
  description = "VPC flow log publishing role ARN."
  value       = aws_iam_role.flow_logs.arn
}

output "rds_monitoring_role_arn" {
  description = "RDS enhanced monitoring role ARN."
  value       = aws_iam_role.rds_monitoring.arn
}
