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
  description = "Full API image URI including the tag."
  type        = string
}

variable "ecr_repository_arn" {
  description = "The API image repository (the execution role may pull from it only)."
  type        = string
}

variable "cpu" {
  type    = number
  default = 512
}

variable "memory" {
  type    = number
  default = 1024
}

variable "desired_count" {
  description = "API tasks. Two spreads them across both AZs."
  type        = number
  default     = 2
}

variable "container_port" {
  description = "Port the API container serves TLS on."
  type        = number
}

variable "subnet_ids" {
  description = "Subnets the API and its one-off tasks run in (network module's task_subnet_ids)."
  type        = list(string)
}

variable "assign_public_ip" {
  description = "Give tasks a public IP (only when they run in public subnets, for egress without NAT)."
  type        = bool
  default     = false
}

variable "security_group_id" {
  description = "The api security group (also used by the migrate and bootstrap tasks)."
  type        = string
}

variable "target_group_arn" {
  type = string
}

variable "load_balancer_listener_arn" {
  description = "HTTPS listener; the service is created only once it exists."
  type        = string
}

variable "kms_key_arn" {
  description = "Key for the log groups, the database secret, and SQS/S3 data keys."
  type        = string
}

variable "log_retention_days" {
  description = "Days to keep the log groups' events. null keeps them forever (no expiry)."
  type        = number
  default     = null
}

variable "database" {
  description = "Connection details. The password comes from the RDS-managed secret."
  type = object({
    address                = string
    port                   = number
    name                   = string
    username               = string
    master_user_secret_arn = string
  })
}

variable "cognito" {
  type = object({
    user_pool_id  = string
    web_client_id = string
  })
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
