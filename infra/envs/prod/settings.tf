# Everything that differs between environments. main.tf is identical in staging and prod.
#
# Prod keeps ECS tasks in the private subnets (no public IPs) with a NAT gateway per AZ.

locals {
  environment = "prod"
  name_prefix = "lusiform-prod"

  vpc_cidr                = "10.40.0.0/16"
  nat_gateway_count       = 2
  tasks_in_public_subnets = false

  api_desired_count    = 2 # one per AZ (Technical Design availability target)
  worker_desired_count = 2

  db_instance_class        = "db.t3.medium"
  db_multi_az              = true
  db_backup_retention_days = 14

  deletion_protection = true
  log_retention_days  = 365

  # Prod refuses to plan without certificate_arn: clients reach it over HTTPS only.
  require_https = true

  extra_web_base_urls = []
}
