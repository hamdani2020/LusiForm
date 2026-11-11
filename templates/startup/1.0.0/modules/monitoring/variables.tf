variable "name_prefix" {
  description = "Prefix for resource names, taken from the project slug."
  type        = string

  validation {
    condition     = can(regex("^lf-[a-z0-9]([a-z0-9-]{0,19}[a-z0-9])?$", var.name_prefix))
    error_message = "name_prefix must start with lf- and continue with lowercase letters, digits, and hyphens, 4 to 24 characters in all, not ending with a hyphen."
  }
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}

variable "log_retention_days" {
  description = "Retention for the log groups, in days."
  type        = number

  validation {
    condition     = contains([7, 14, 30, 90, 365], var.log_retention_days)
    error_message = "log_retention_days must be one of 7, 14, 30, 90, or 365."
  }
}

variable "alb_arn_suffix" {
  description = "ARN suffix of the load balancer (from the compute module), used by the 5xx alarm."
  type        = string
}

variable "ecs_cluster_name" {
  description = "ECS cluster name (from the compute module), used by the CPU alarm."
  type        = string
}

variable "ecs_service_name" {
  description = "ECS service name (from the compute module), used by the CPU alarm."
  type        = string
}

variable "db_instance_identifier" {
  description = "RDS instance identifier (from the database module), used by the database alarms."
  type        = string
}

variable "db_storage_gb" {
  description = "Allocated database storage in GB. The free-storage alarm fires below 20 percent of it."
  type        = number

  validation {
    condition     = var.db_storage_gb >= 20 && var.db_storage_gb <= 1000
    error_message = "db_storage_gb must be between 20 and 1000."
  }
}

variable "alarm_action_arns" {
  description = "Optional ARNs notified when an alarm fires and when it recovers. Empty by default: the template creates no SNS topic."
  type        = list(string)
  default     = []
}
