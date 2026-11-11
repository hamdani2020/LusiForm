variable "name_prefix" {
  description = "Prefix for resource names, taken from the project slug."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,22}[a-z0-9]$", var.name_prefix))
    error_message = "name_prefix must be 3 to 24 characters: lowercase letters, digits, and hyphens, starting with a letter and not ending with a hyphen."
  }
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}

variable "flow_log_group_arn" {
  description = "ARN of the VPC flow log group (from the monitoring module). The flow log role can write to this group only."
  type        = string
}

variable "db_secret_arn" {
  description = "ARN of the Secrets Manager secret holding the database master credentials (from the database module). The task roles can read this secret only."
  type        = string
}
