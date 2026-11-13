output "kms_key_arn" {
  description = "ARN of the customer-managed key that encrypts the log groups."
  value       = aws_kms_key.logs.arn
}

output "ecs_log_group_name" {
  description = "Log group for the ECS service."
  value       = aws_cloudwatch_log_group.ecs.name
}

output "ecs_log_group_arn" {
  description = "ARN of the ECS service log group."
  value       = aws_cloudwatch_log_group.ecs.arn
}

output "flow_log_group_arn" {
  description = "ARN of the VPC flow log group."
  value       = aws_cloudwatch_log_group.flow_logs.arn
}

output "alarm_names" {
  description = "Names of the alarms created."
  value = [
    aws_cloudwatch_metric_alarm.alb_5xx.alarm_name,
    aws_cloudwatch_metric_alarm.ecs_cpu.alarm_name,
    aws_cloudwatch_metric_alarm.rds_cpu.alarm_name,
    aws_cloudwatch_metric_alarm.rds_free_storage.alarm_name,
  ]
}
