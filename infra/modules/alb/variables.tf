variable "name_prefix" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "public_subnet_ids" {
  type = list(string)
}

variable "security_group_id" {
  description = "The load balancer security group (from the network module)."
  type        = string
}

variable "certificate_arn" {
  description = "ACM certificate ARN for the HTTPS listener, in the same region. null serves plain HTTP on port 80 instead (only allowed when require_https = false)."
  type        = string
  default     = null

  validation {
    condition     = var.certificate_arn == null || can(regex("^arn:aws[a-z-]*:acm:[a-z0-9-]+:[0-9]{12}:certificate/[A-Za-z0-9-]+$", var.certificate_arn))
    error_message = "certificate_arn must be a real ACM certificate ARN (arn:aws:acm:<region>:<12-digit account id>:certificate/<id>), or unset. A placeholder from an example file is not valid."
  }
}

variable "require_https" {
  description = "Refuse to plan without a certificate. On in prod; off in staging until it has a domain."
  type        = bool
  default     = true
}

variable "target_port" {
  description = "Port the API container serves TLS on."
  type        = number
}

variable "health_check_path" {
  type    = string
  default = "/api/health"
}

variable "deletion_protection" {
  type    = bool
  default = true
}
