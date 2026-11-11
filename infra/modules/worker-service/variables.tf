# Deliberately no database inputs: the worker has no tenant database access (security.md).

variable "name_prefix" {
  type = string
}

variable "environment" {
  description = "staging or prod. Passed to the app as ENVIRONMENT."
  type        = string
}

variable "cluster_id" {
  type = string
}

variable "image" {
  description = "Full worker image URI including the tag."
  type        = string
}

variable "ecr_repository_arn" {
  description = "The worker image repository (the execution role may pull from it only)."
  type        = string
}

variable "cpu" {
  type    = number
  default = 1024
}

variable "memory" {
  type    = number
  default = 2048
}

variable "desired_count" {
  type    = number
  default = 1
}

variable "subnet_ids" {
  description = "Subnets the worker runs in (network module's task_subnet_ids)."
  type        = list(string)
}

variable "assign_public_ip" {
  description = "Give tasks a public IP (only when they run in public subnets, for egress without NAT)."
  type        = bool
  default     = false
}

variable "security_group_id" {
  description = "The worker security group (no ingress, HTTPS egress only)."
  type        = string
}

variable "kms_key_arn" {
  type = string
}

variable "log_retention_days" {
  description = "Days to keep the log groups' events. null keeps them forever (no expiry)."
  type        = number
  default     = null
}

variable "job_queue" {
  type = object({
    url = string
    arn = string
  })
}

variable "artifact_bucket" {
  type = object({
    name = string
    arn  = string
  })
}
