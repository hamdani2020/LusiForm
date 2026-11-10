# Wires the platform modules together. This file is identical in staging and prod;
# per-environment values live in settings.tf, the state key in backend.tf.
#
# Dependency order: kms -> network -> data services (rds, cognito, artifact_bucket,
# job_queue, ecr) -> alb, ecs_cluster -> api_service, worker_service.

terraform {
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.47"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "lusiform"
      Environment = local.environment
      ManagedBy   = "terraform"
    }
  }
}

module "kms" {
  source = "../../modules/kms"

  name_prefix = local.name_prefix
  environment = local.environment
}

module "network" {
  source = "../../modules/network"

  name_prefix             = local.name_prefix
  environment             = local.environment
  vpc_cidr                = local.vpc_cidr
  nat_gateway_count       = local.nat_gateway_count
  tasks_in_public_subnets = local.tasks_in_public_subnets
  kms_key_arn             = module.kms.key_arn
  log_retention_days      = local.log_retention_days
}

module "rds" {
  source = "../../modules/rds"

  name_prefix           = local.name_prefix
  subnet_ids            = module.network.private_subnet_ids
  security_group_id     = module.network.security_group_ids.db
  port                  = module.network.db_port
  kms_key_arn           = module.kms.key_arn
  instance_class        = local.db_instance_class
  multi_az              = local.db_multi_az
  backup_retention_days = local.db_backup_retention_days
  deletion_protection   = local.deletion_protection
}

module "cognito" {
  source = "../../modules/cognito"

  name_prefix         = local.name_prefix
  domain_prefix       = var.cognito_domain_prefix
  web_base_urls       = concat(var.web_base_urls, local.extra_web_base_urls)
  deletion_protection = local.deletion_protection
}

module "artifact_bucket" {
  source = "../../modules/artifact-bucket"

  name_prefix = local.name_prefix
  kms_key_arn = module.kms.key_arn
}

module "job_queue" {
  source = "../../modules/job-queue"

  name_prefix = local.name_prefix
  kms_key_arn = module.kms.key_arn
}

module "ecr" {
  source = "../../modules/ecr"

  name_prefix  = local.name_prefix
  repositories = ["api", "worker"]
  kms_key_arn  = module.kms.key_arn
}

module "alb" {
  source = "../../modules/alb"

  name_prefix         = local.name_prefix
  vpc_id              = module.network.vpc_id
  public_subnet_ids   = module.network.public_subnet_ids
  security_group_id   = module.network.security_group_ids.alb
  certificate_arn     = var.certificate_arn
  target_port         = module.network.api_port
  deletion_protection = local.deletion_protection
}

module "ecs_cluster" {
  source = "../../modules/ecs-cluster"

  name = local.name_prefix
}

module "api_service" {
  source = "../../modules/api-service"

  name_prefix        = local.name_prefix
  environment        = local.environment
  cluster_id         = module.ecs_cluster.id
  image              = "${module.ecr.repository_urls["api"]}:${var.api_image_tag}"
  ecr_repository_arn = module.ecr.repository_arns["api"]
  desired_count      = local.api_desired_count
  container_port     = module.network.api_port
  subnet_ids         = module.network.task_subnet_ids
  assign_public_ip   = module.network.assign_public_ip
  security_group_id  = module.network.security_group_ids.api
  kms_key_arn        = module.kms.key_arn
  log_retention_days = local.log_retention_days

  target_group_arn           = module.alb.target_group_arn
  load_balancer_listener_arn = module.alb.https_listener_arn

  database = {
    address                = module.rds.address
    port                   = module.rds.port
    name                   = module.rds.db_name
    username               = module.rds.master_username
    master_user_secret_arn = module.rds.master_user_secret_arn
  }
  cognito = {
    user_pool_id  = module.cognito.user_pool_id
    web_client_id = module.cognito.web_client_id
  }
  job_queue = {
    url = module.job_queue.url
    arn = module.job_queue.arn
  }
  artifact_bucket = {
    name = module.artifact_bucket.bucket
    arn  = module.artifact_bucket.arn
  }
}

module "worker_service" {
  source = "../../modules/worker-service"

  name_prefix        = local.name_prefix
  environment        = local.environment
  cluster_id         = module.ecs_cluster.id
  image              = "${module.ecr.repository_urls["worker"]}:${var.worker_image_tag}"
  ecr_repository_arn = module.ecr.repository_arns["worker"]
  desired_count      = local.worker_desired_count
  subnet_ids         = module.network.task_subnet_ids
  assign_public_ip   = module.network.assign_public_ip
  security_group_id  = module.network.security_group_ids.worker
  kms_key_arn        = module.kms.key_arn
  log_retention_days = local.log_retention_days

  job_queue = {
    url = module.job_queue.url
    arn = module.job_queue.arn
  }
  artifact_bucket = {
    name = module.artifact_bucket.bucket
    arn  = module.artifact_bucket.arn
  }
}
