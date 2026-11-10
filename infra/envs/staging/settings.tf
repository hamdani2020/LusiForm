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

  # No log retention: staging's log groups keep events forever (no expiry).
  log_retention_days = 7

  # The local Vite dev server may sign in against the staging user pool, so the web app can
  # be tested locally with real Cognito (see infra/README.md, "Local sign-in").
  extra_web_base_urls = ["http://localhost:5173"]
}
