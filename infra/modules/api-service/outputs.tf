output "service_name" {
  value = aws_ecs_service.api.name
}

output "task_role_arn" {
  value = aws_iam_role.task.arn
}

output "execution_role_arn" {
  value = aws_iam_role.execution.arn
}

output "log_groups" {
  value = { for k, g in aws_cloudwatch_log_group.this : k => g.name }
}

output "migrate_task_family" {
  value = aws_ecs_task_definition.migrate.family
}

output "bootstrap_task_family" {
  value = aws_ecs_task_definition.bootstrap.family
}
