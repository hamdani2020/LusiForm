output "user_pool_id" {
  value = aws_cognito_user_pool.this.id
}

output "user_pool_arn" {
  value = aws_cognito_user_pool.this.arn
}

output "web_client_id" {
  description = "VITE_COGNITO_CLIENT_ID for the web app (public client, no secret)."
  value       = aws_cognito_user_pool_client.web.id
}

output "hosted_login_domain" {
  description = "VITE_COGNITO_DOMAIN for the web app."
  value       = "https://${aws_cognito_user_pool_domain.this.domain}.auth.${data.aws_region.current.name}.amazoncognito.com"
}
