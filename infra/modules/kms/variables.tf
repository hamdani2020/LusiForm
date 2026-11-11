variable "name_prefix" {
  description = "Resource name prefix, e.g. lusiform-dev."
  type        = string
}

variable "environment" {
  description = "staging or prod. Scopes the CloudWatch Logs grant to /lusiform/<environment>/*."
  type        = string
}
