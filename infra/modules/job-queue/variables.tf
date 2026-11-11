variable "name_prefix" {
  type = string
}

variable "kms_key_arn" {
  type = string
}

variable "visibility_timeout_seconds" {
  description = "How long a received job stays hidden from other workers. Longer than the slowest job."
  type        = number
  default     = 900
}

variable "max_receive_count" {
  description = "Receives before a job moves to the dead-letter queue."
  type        = number
  default     = 5
}
