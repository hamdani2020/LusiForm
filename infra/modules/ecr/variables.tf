variable "name_prefix" {
  type = string
}

variable "repositories" {
  description = "Repository names under <name_prefix>/, e.g. [\"api\", \"worker\"]."
  type        = list(string)
}

variable "kms_key_arn" {
  type = string
}

variable "keep_images" {
  type    = number
  default = 30
}
