variable "region" {
  description = "AWS region for every resource in this project."
  type        = string
  default     = "us-east-1"
}

variable "name_prefix" {
  description = "Prefix for resource names. Fixed when the project was generated."
  type        = string
  default     = "lf-fix-default"
}

# --- Template parameters (adjustable within the template's allowed values) ---

variable "az_count" {
  description = "Availability Zones the workload runs in: 1 or 2."
  type        = number
  default     = 1
}

variable "task_size" {
  description = "Fargate task size: 0.25vcpu-0.5gb, 0.5vcpu-1gb, 1vcpu-2gb, or 2vcpu-4gb."
  type        = string
  default     = "0.25vcpu-0.5gb"
}

variable "min_tasks" {
  description = "Minimum number of tasks, 1 to 10."
  type        = number
  default     = 2
}

variable "max_tasks" {
  description = "Maximum number of tasks, 2 to 20, at least min_tasks."
  type        = number
  default     = 6
}

variable "instance_class" {
  description = "RDS instance class: db.t3.micro, db.t3.small, or db.t3.medium."
  type        = string
  default     = "db.t3.micro"
}

variable "storage_gb" {
  description = "Database storage in GB, 20 to 1000."
  type        = number
  default     = 20
}

variable "backup_retention_days" {
  description = "Database backup retention in days, 1 to 35."
  type        = number
  default     = 7
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days: 7, 14, 30, 90, or 365."
  type        = number
  default     = 30
}

# --- Deploy-time settings ---

variable "container_image" {
  description = "Container image to run, for example registry.example.com/team/app:1.0.0. Required; the template contains no image."
  type        = string
}

variable "container_port" {
  description = "Port the container listens on."
  type        = number
  default     = 8080
}

variable "health_check_path" {
  description = "HTTP path the load balancer uses to check the container."
  type        = string
  default     = "/"
}

variable "certificate_arn" {
  description = "Optional ACM certificate ARN. When set, the load balancer serves HTTPS and HTTP redirects to it. When empty, it serves HTTP only."
  type        = string
  default     = ""
}

variable "deletion_protection" {
  description = "Protect the database and load balancer from deletion. Set to false and apply before a destroy."
  type        = bool
  default     = true
}

variable "skip_final_snapshot" {
  description = "Skip the final database snapshot on destroy."
  type        = bool
  default     = false
}
