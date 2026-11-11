variable "name_prefix" {
  type = string
}

variable "subnet_ids" {
  description = "Private subnets, one per AZ."
  type        = list(string)
}

variable "security_group_id" {
  description = "The database security group (allows the API security group only)."
  type        = string
}

variable "kms_key_arn" {
  description = "Key for storage, Performance Insights, and the master-password secret."
  type        = string
}

variable "port" {
  type    = number
  default = 5432
}

variable "db_name" {
  type    = string
  default = "lusiform"
}

variable "master_username" {
  type    = string
  default = "lusiform_admin"
}

variable "instance_class" {
  type    = string
  default = "db.t3.micro"
}

variable "allocated_storage_gb" {
  type    = number
  default = 20
}

variable "max_allocated_storage_gb" {
  description = "Storage autoscaling ceiling."
  type        = number
  default     = 100
}

variable "multi_az" {
  type    = bool
  default = false
}

variable "backup_retention_days" {
  type    = number
  default = 7

  validation {
    condition     = var.backup_retention_days >= 1 && var.backup_retention_days <= 35
    error_message = "Backups are required: backup_retention_days must be 1-35."
  }
}

variable "deletion_protection" {
  type    = bool
  default = true
}
