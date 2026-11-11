locals {
  environment = "staging"
  name_prefix = "lusiform-staging"

  vpc_cidr                = "10.30.0.0/16"
  nat_gateway_count       = 0
  tasks_in_public_subnets = true

  api_desired_count    = 1
  worker_desired_count = 1

  db_instance_class        = "db.t3.micro"
  db_multi_az              = false
  db_backup_retention_days = 7

  deletion_protection = true

  # Staging keeps its log groups' events for 7 days.
  log_retention_days = 7

  require_https = false

  extra_web_base_urls = ["http://localhost:5173"]
}
