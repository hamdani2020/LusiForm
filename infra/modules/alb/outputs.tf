output "dns_name" {
  description = "Point the API hostname (CNAME/alias) here."
  value       = aws_lb.this.dns_name
}

output "base_url" {
  description = "How clients reach the API: https:// with a certificate, http:// without."
  value       = "${local.https_enabled ? "https" : "http"}://${aws_lb.this.dns_name}"
}

output "https_enabled" {
  value = local.https_enabled
}

output "arn" {
  value = aws_lb.this.arn
}

output "target_group_arn" {
  value = aws_lb_target_group.api.arn
}

output "listener_arn" {
  description = "The listener that forwards to the API (HTTPS, or HTTP without a certificate). Pass to the API service so it is created after the listener exists."
  value       = local.https_enabled ? aws_lb_listener.https[0].arn : aws_lb_listener.http_forward[0].arn
}
