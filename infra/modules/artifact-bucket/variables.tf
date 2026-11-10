variable "name_prefix" {
  type = string
}

variable "kms_key_arn" {
  type = string
}

variable "noncurrent_version_days" {
  description = "Days to keep overwritten or deleted object versions."
  type        = number
  default     = 90
}
