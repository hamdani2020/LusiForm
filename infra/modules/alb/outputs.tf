output "dns_name" {
  description = "Point the API hostname (CNAME/alias) here."
  value       = aws_lb.this.dns_name
}

output "arn" {
  value = aws_lb.this.arn
}

output "target_group_arn" {
  value = aws_lb_target_group.api.arn
}

output "https_listener_arn" {
  description = "Pass to the API service so it is created after the listener exists."
  value       = aws_lb_listener.https.arn
}
