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
  description = "ACM certificate ARN for the HTTPS listener, in the same region."
  type        = string
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
