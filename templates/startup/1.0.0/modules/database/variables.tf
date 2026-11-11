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

variable "vpc_id" {
  description = "VPC id (from the network module)."
  type        = string
}

variable "subnet_ids" {
  description = "Isolated data subnet ids, in two zones (from the network module)."
  type        = list(string)

  validation {
    condition     = length(var.subnet_ids) == 2
    error_message = "subnet_ids must be the two data subnets."
  }
}

variable "primary_availability_zone" {
  description = "Zone for a single-zone database (used only when az_count is 1)."
  type        = string
}

variable "allowed_security_group_id" {
  description = "Security group of the compute tasks, the only source allowed to reach PostgreSQL."
  type        = string
}

variable "monitoring_role_arn" {
  description = "RDS enhanced monitoring role ARN (from the iam module)."
  type        = string
}

variable "instance_class" {
  description = "RDS instance class."
  type        = string

  validation {
    condition     = contains(["db.t4g.micro", "db.t4g.small", "db.t4g.medium"], var.instance_class)
    error_message = "instance_class must be one of db.t4g.micro, db.t4g.small, or db.t4g.medium."
  }
}

variable "storage_gb" {
  description = "Allocated storage in GB. Storage can autoscale up to twice this value."
  type        = number

  validation {
    condition     = var.storage_gb >= 20 && var.storage_gb <= 1000
    error_message = "storage_gb must be between 20 and 1000."
  }
}

variable "backup_retention_days" {
  description = "Automated backup retention in days."
  type        = number

  validation {
    condition     = var.backup_retention_days >= 1 && var.backup_retention_days <= 35
    error_message = "backup_retention_days must be between 1 and 35."
  }
}

variable "az_count" {
  description = "Availability Zones the workload runs in. With 2, the database has a standby in the second zone."
  type        = number

  validation {
    condition     = contains([1, 2], var.az_count)
    error_message = "az_count must be 1 or 2."
  }
}

variable "engine_version" {
  description = "PostgreSQL version. A major version only; RDS picks the current minor and applies minor upgrades."
  type        = string
  default     = "16"

  validation {
    condition     = can(regex("^16(\\.[0-9]+)?$", var.engine_version))
    error_message = "engine_version must be PostgreSQL 16, for example \"16\" or \"16.4\"."
  }
}

variable "deletion_protection" {
  description = "Block deletion of the instance. On by default; sandbox teardown must turn it off and apply before destroy."
  type        = bool
  default     = true
}

variable "skip_final_snapshot" {
  description = "Skip the final snapshot on destroy. Off by default; sandbox teardown may turn it on."
  type        = bool
  default     = false
}
