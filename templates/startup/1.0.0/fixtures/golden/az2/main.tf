terraform {
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.47"
    }
  }

  # State location (bucket, key, region) is supplied at init time with -backend-config.
  # Locking uses a lock file in the same bucket; no DynamoDB table is needed.
  backend "s3" {
    use_lockfile = true
    encrypt      = true
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      "lusiform-managed"          = "true"
      "lusiform-project"          = var.name_prefix
      "lusiform-template-version" = "1.0.0"
    }
  }
}

locals {
  # Subnets always exist in two zones; az_count decides which ones run the workload.
  availability_zones = ["${var.region}a", "${var.region}b"]
}

module "network" {
  source = "./modules/network"

  name_prefix              = var.name_prefix
  az_count                 = var.az_count
  availability_zones       = local.availability_zones
  flow_log_destination_arn = module.monitoring.flow_log_group_arn
  flow_log_role_arn        = module.iam.flow_log_role_arn
}

module "iam" {
  source = "./modules/iam"

  name_prefix        = var.name_prefix
  flow_log_group_arn = module.monitoring.flow_log_group_arn
  db_secret_arn      = module.database.master_user_secret_arn
}

module "monitoring" {
  source = "./modules/monitoring"

  name_prefix            = var.name_prefix
  log_retention_days     = var.log_retention_days
  alb_arn_suffix         = module.compute.alb_arn_suffix
  ecs_cluster_name       = module.compute.cluster_name
  ecs_service_name       = module.compute.service_name
  db_instance_identifier = module.database.identifier
  db_storage_gb          = var.storage_gb
}

module "database" {
  source = "./modules/database"

  name_prefix               = var.name_prefix
  vpc_id                    = module.network.vpc_id
  subnet_ids                = module.network.data_subnet_ids
  primary_availability_zone = local.availability_zones[0]
  allowed_security_group_id = module.compute.task_security_group_id
  monitoring_role_arn       = module.iam.rds_monitoring_role_arn
  instance_class            = var.instance_class
  storage_gb                = var.storage_gb
  backup_retention_days     = var.backup_retention_days
  az_count                  = var.az_count
  deletion_protection       = var.deletion_protection
  skip_final_snapshot       = var.skip_final_snapshot
}

module "compute" {
  source = "./modules/compute"

  name_prefix         = var.name_prefix
  vpc_id              = module.network.vpc_id
  vpc_cidr            = module.network.vpc_cidr
  public_subnet_ids   = module.network.public_subnet_ids
  private_subnet_ids  = module.network.active_private_app_subnet_ids
  task_size           = var.task_size
  min_tasks           = var.min_tasks
  max_tasks           = var.max_tasks
  container_image     = var.container_image
  container_port      = var.container_port
  health_check_path   = var.health_check_path
  execution_role_arn  = module.iam.task_execution_role_arn
  task_role_arn       = module.iam.task_role_arn
  log_group_name      = module.monitoring.ecs_log_group_name
  db_host             = module.database.address
  db_port             = module.database.port
  db_name             = module.database.db_name
  db_secret_arn       = module.database.master_user_secret_arn
  certificate_arn     = var.certificate_arn
  deletion_protection = var.deletion_protection
}
