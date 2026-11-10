variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "certificate_arn" {
  description = "ACM certificate for the API hostname, in aws_region."
  type        = string
}

variable "cognito_domain_prefix" {
  description = "Globally unique prefix for the hosted login domain."
  type        = string
}

variable "web_base_urls" {
  description = "https origins the web app is served from."
  type        = list(string)
}

variable "api_image_tag" {
  type = string
}

variable "worker_image_tag" {
  type = string
}
