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

variable "az_count" {
  description = "Availability Zones the workload runs in (1 or 2). Subnets always exist in two zones; this sets the number of NAT gateways and which application subnets are active."
  type        = number

  validation {
    condition     = contains([1, 2], var.az_count)
    error_message = "az_count must be 1 or 2."
  }
}

variable "availability_zones" {
  description = "Exactly two Availability Zone names in the project's region. Passed in so rendering stays deterministic and no account lookup is needed."
  type        = list(string)

  validation {
    condition     = length(var.availability_zones) == 2 && length(distinct(var.availability_zones)) == 2
    error_message = "availability_zones must be exactly two distinct zone names."
  }
}

variable "flow_log_destination_arn" {
  description = "ARN of the KMS-encrypted CloudWatch log group that receives VPC flow logs (from the monitoring module)."
  type        = string
}

variable "flow_log_role_arn" {
  description = "ARN of the IAM role that publishes flow logs (from the iam module)."
  type        = string
}
