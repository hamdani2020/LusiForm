variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "certificate_arn" {
  description = "ACM certificate for the API hostname, in aws_region. Optional where require_https is off (staging without a domain); required in prod."
  type        = string
  default     = null
}

variable "cognito_domain_prefix" {
  description = "Globally unique prefix for the hosted login domain (an AWS-provided domain; no domain of your own needed)."
  type        = string
}

variable "web_base_urls" {
  description = "https origins the web app is served from. Optional in staging (localhost is allowed there); prod needs at least one."
  type        = list(string)
  default     = []
}

variable "api_image_tag" {
  type = string
}

variable "worker_image_tag" {
  type = string
}
