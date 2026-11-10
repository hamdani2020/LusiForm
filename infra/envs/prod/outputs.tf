# Endpoints and identifiers for this environment (none are secrets). Identical in staging and prod.

output "api_load_balancer_dns_name" {
  value = module.alb.dns_name
}

output "api_base_url" {
  description = "https:// with a certificate; http:// without one (staging until it has a domain)."
  value       = module.alb.base_url
}

output "web_app_settings" {
  description = "Values for the web app's VITE_COGNITO_* settings."
  value = {
    VITE_COGNITO_DOMAIN    = module.cognito.hosted_login_domain
    VITE_COGNITO_CLIENT_ID = module.cognito.web_client_id
  }
}

output "cognito_user_pool_id" {
  value = module.cognito.user_pool_id
}

output "job_queue" {
  value = {
    url     = module.job_queue.url
    dlq_url = module.job_queue.dlq_url
  }
}

output "artifact_bucket" {
  value = module.artifact_bucket.bucket
}

output "ecr_repository_urls" {
  value = module.ecr.repository_urls
}

output "ecs_cluster_name" {
  value = module.ecs_cluster.name
}

output "log_groups" {
  value = merge(module.api_service.log_groups, { worker = module.worker_service.log_group })
}

output "one_off_tasks" {
  description = "For aws ecs run-task (see infra/README.md)."
  value = {
    migrate          = module.api_service.migrate_task_family
    bootstrap        = module.api_service.bootstrap_task_family
    subnets          = module.network.task_subnet_ids
    security_groups  = [module.network.security_group_ids.api]
    assign_public_ip = module.network.assign_public_ip
  }
}
