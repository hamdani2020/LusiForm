variable "name_prefix" {
  type = string
}

variable "domain_prefix" {
  description = "Prefix for the hosted login domain (<prefix>.auth.<region>.amazoncognito.com). Globally unique."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", var.domain_prefix)) && !can(regex("aws|amazon|cognito", var.domain_prefix))
    error_message = "domain_prefix must be 1-63 lowercase letters, digits, or hyphens (no leading or trailing hyphen), and may not contain \"aws\", \"amazon\", or \"cognito\"."
  }
}

variable "web_base_urls" {
  description = "Origins the web app is served from. Used for the callback and sign-out URLs."
  type        = list(string)

  validation {
    condition     = length(var.web_base_urls) > 0 && alltrue([for u in var.web_base_urls : can(regex("^https://[^/]+$", u)) || can(regex("^http://localhost(:[0-9]+)?$", u))])
    error_message = "web_base_urls must be https origins without a path (http is allowed only for localhost)."
  }
}

variable "deletion_protection" {
  type    = bool
  default = true
}
