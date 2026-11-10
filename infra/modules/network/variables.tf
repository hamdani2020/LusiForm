variable "name_prefix" {
  type = string
}

variable "environment" {
  type = string
}

variable "vpc_cidr" {
  description = "VPC CIDR. Two public and two private subnets are carved from it, one per AZ."
  type        = string
}

variable "nat_gateway_count" {
  description = "0 (tasks must then run in public subnets), 1 (single-AZ egress), or 2 (one per AZ)."
  type        = number
  default     = 1

  validation {
    condition     = contains([0, 1, 2], var.nat_gateway_count)
    error_message = "nat_gateway_count must be 0, 1, or 2."
  }
}

variable "tasks_in_public_subnets" {
  description = <<-EOT
    Run ECS tasks in the public subnets with public IPs, for internet egress without a NAT
    gateway (cheaper). Security groups are unchanged: the API still accepts traffic only
    from the load balancer, the worker accepts none, and the database stays private.
  EOT
  type        = bool
  default     = false
}

variable "api_port" {
  description = "Port the API container serves TLS on (load balancer -> API)."
  type        = number
  default     = 8443
}

variable "db_port" {
  type    = number
  default = 5432
}

variable "kms_key_arn" {
  description = "Key for the flow-log group."
  type        = string
}

variable "log_retention_days" {
  description = "Days to keep the log groups' events. null keeps them forever (no expiry)."
  type        = number
  default     = null
}
