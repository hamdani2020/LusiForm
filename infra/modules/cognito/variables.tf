variable "name_prefix" {
  type = string
}

variable "domain_prefix" {
  description = "Prefix for the hosted login domain (<prefix>.auth.<region>.amazoncognito.com). Globally unique."
  type        = string
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
