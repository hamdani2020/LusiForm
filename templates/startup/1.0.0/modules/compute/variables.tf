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

variable "vpc_cidr" {
  description = "VPC CIDR block. Security group egress is limited to this range, apart from HTTPS."
  type        = string
}

variable "public_subnet_ids" {
  description = "Public subnet ids in both zones, for the load balancer."
  type        = list(string)

  validation {
    condition     = length(var.public_subnet_ids) == 2
    error_message = "public_subnet_ids must be the two public subnets."
  }
}

variable "private_subnet_ids" {
  description = "Active private application subnet ids, one per active zone. This is what places the tasks."
  type        = list(string)

  validation {
    condition     = length(var.private_subnet_ids) >= 1 && length(var.private_subnet_ids) <= 2
    error_message = "private_subnet_ids must hold one or two subnets."
  }
}

variable "task_size" {
  description = "Fargate vCPU and memory per task."
  type        = string

  validation {
    condition     = contains(["0.25vcpu-0.5gb", "0.5vcpu-1gb", "1vcpu-2gb", "2vcpu-4gb"], var.task_size)
    error_message = "task_size must be one of 0.25vcpu-0.5gb, 0.5vcpu-1gb, 1vcpu-2gb, or 2vcpu-4gb."
  }
}

variable "min_tasks" {
  description = "Desired task count at rest and the auto scaling floor."
  type        = number

  validation {
    condition     = var.min_tasks >= 1 && var.min_tasks <= 10
    error_message = "min_tasks must be between 1 and 10."
  }
}

variable "max_tasks" {
  description = "Auto scaling ceiling."
  type        = number

  validation {
    condition     = var.max_tasks >= 2 && var.max_tasks <= 20
    error_message = "max_tasks must be between 2 and 20."
  }

  validation {
    condition     = var.max_tasks >= var.min_tasks
    error_message = "max_tasks must be greater than or equal to min_tasks."
  }
}

variable "container_image" {
  description = "Container image to run, supplied at deploy time. The template holds no account-specific registry URL."
  type        = string

  validation {
    condition     = length(var.container_image) > 0
    error_message = "container_image must not be empty."
  }
}

variable "container_port" {
  description = "Port the container listens on."
  type        = number
  default     = 8080
}

variable "health_check_path" {
  description = "HTTP path the load balancer probes."
  type        = string
  default     = "/"
}

variable "execution_role_arn" {
  description = "ECS task execution role ARN (from the iam module)."
  type        = string
}

variable "task_role_arn" {
  description = "ECS task role ARN (from the iam module)."
  type        = string
}

variable "log_group_name" {
  description = "Log group for the container logs (from the monitoring module)."
  type        = string
}

variable "db_host" {
  description = "Database host name, passed to the container as DB_HOST."
  type        = string
}

variable "db_port" {
  description = "Database port, passed to the container as DB_PORT."
  type        = number
}

variable "db_name" {
  description = "Database name, passed to the container as DB_NAME."
  type        = string
}

variable "db_secret_arn" {
  description = "Secrets Manager secret with the database credentials. ECS injects it as DB_CREDENTIALS."
  type        = string
}

variable "certificate_arn" {
  description = "Optional ACM certificate ARN. When set, the load balancer serves HTTPS on 443 and HTTP redirects to it. When empty, it serves HTTP only."
  type        = string
  default     = ""
}

variable "deletion_protection" {
  description = "Block deletion of the load balancer. On by default; sandbox teardown must turn it off and apply before destroy."
  type        = bool
  default     = true
}

variable "read_only_root_filesystem" {
  description = "Run the container with a read-only root filesystem."
  type        = bool
  default     = true
}
