# Compute module tests. Mocked AWS provider: no credentials, no AWS calls.

mock_provider "aws" {
  mock_data "aws_region" {
    defaults = {
      name = "us-east-1"
    }
  }

  mock_resource "aws_lb" {
    defaults = {
      arn        = "arn:aws:elasticloadbalancing:us-east-1:000000000000:loadbalancer/app/lf-demo-alb/0123456789abcdef"
      arn_suffix = "app/lf-demo-alb/0123456789abcdef"
      dns_name   = "lf-demo-alb-123456789.us-east-1.elb.amazonaws.com"
    }
  }

  mock_resource "aws_lb_target_group" {
    defaults = {
      arn = "arn:aws:elasticloadbalancing:us-east-1:000000000000:targetgroup/lf-demo-tg/0123456789abcdef"
    }
  }

  mock_resource "aws_ecs_task_definition" {
    defaults = {
      arn = "arn:aws:ecs:us-east-1:000000000000:task-definition/lf-demo-app:1"
    }
  }

  mock_resource "aws_ecs_cluster" {
    defaults = {
      arn = "arn:aws:ecs:us-east-1:000000000000:cluster/lf-demo-cluster"
    }
  }
}

variables {
  name_prefix        = "lf-demo"
  vpc_id             = "vpc-0123456789abcdef0"
  vpc_cidr           = "10.0.0.0/16"
  public_subnet_ids  = ["subnet-0aaaaaaaaaaaaaaa1", "subnet-0bbbbbbbbbbbbbbb2"]
  private_subnet_ids = ["subnet-0ccccccccccccccc3", "subnet-0ddddddddddddddd4"]
  task_size          = "0.25vcpu-0.5gb"
  min_tasks          = 2
  max_tasks          = 6
  container_image    = "registry.example.com/team/app:1.2.3"
  execution_role_arn = "arn:aws:iam::000000000000:role/lf-demo-ecs-execution"
  task_role_arn      = "arn:aws:iam::000000000000:role/lf-demo-ecs-task"
  log_group_name     = "/ecs/lf-demo"
  db_host            = "lf-demo-db.example.us-east-1.rds.amazonaws.com"
  db_port            = 5432
  db_name            = "app"
  db_secret_arn      = "arn:aws:secretsmanager:us-east-1:000000000000:secret:rds!db-0000-AbCdEf"
}

# --- Task sizing and container ---------------------------------------------------------------

run "task_size_maps_to_fargate_cpu_and_memory" {
  command = plan

  assert {
    condition     = aws_ecs_task_definition.app.cpu == "256" && aws_ecs_task_definition.app.memory == "512"
    error_message = "0.25vcpu-0.5gb is 256 CPU units and 512 MiB"
  }
}

run "task_size_half_vcpu" {
  command = plan

  variables {
    task_size = "0.5vcpu-1gb"
  }

  assert {
    condition     = aws_ecs_task_definition.app.cpu == "512" && aws_ecs_task_definition.app.memory == "1024"
    error_message = "0.5vcpu-1gb is 512 CPU units and 1024 MiB"
  }
}

run "task_size_one_vcpu" {
  command = plan

  variables {
    task_size = "1vcpu-2gb"
  }

  assert {
    condition     = aws_ecs_task_definition.app.cpu == "1024" && aws_ecs_task_definition.app.memory == "2048"
    error_message = "1vcpu-2gb is 1024 CPU units and 2048 MiB"
  }
}

run "task_size_two_vcpu" {
  command = plan

  variables {
    task_size = "2vcpu-4gb"
  }

  assert {
    condition     = aws_ecs_task_definition.app.cpu == "2048" && aws_ecs_task_definition.app.memory == "4096"
    error_message = "2vcpu-4gb is 2048 CPU units and 4096 MiB"
  }
}

run "task_runs_on_fargate_x86_with_awsvpc" {
  command = plan

  assert {
    condition     = contains(aws_ecs_task_definition.app.requires_compatibilities, "FARGATE") && aws_ecs_task_definition.app.network_mode == "awsvpc"
    error_message = "the task must be a Fargate awsvpc task"
  }

  assert {
    condition     = one(aws_ecs_task_definition.app.runtime_platform).cpu_architecture == "X86_64" && one(aws_ecs_task_definition.app.runtime_platform).operating_system_family == "LINUX"
    error_message = "the platform is Linux on x86_64, with no Graviton-only construct"
  }
}

run "container_is_hardened_and_uses_the_supplied_image_and_roles" {
  command = plan

  assert {
    condition     = jsondecode(aws_ecs_task_definition.app.container_definitions)[0].image == "registry.example.com/team/app:1.2.3"
    error_message = "the image comes from the container_image variable"
  }

  assert {
    condition = (
      jsondecode(aws_ecs_task_definition.app.container_definitions)[0].privileged == false &&
      jsondecode(aws_ecs_task_definition.app.container_definitions)[0].readonlyRootFilesystem == true
    )
    error_message = "the container must be non-privileged with a read-only root filesystem"
  }

  assert {
    condition     = aws_ecs_task_definition.app.execution_role_arn == var.execution_role_arn && aws_ecs_task_definition.app.task_role_arn == var.task_role_arn
    error_message = "the task must use the roles from the iam module"
  }
}

run "read_only_root_filesystem_can_be_relaxed" {
  command = plan

  variables {
    read_only_root_filesystem = false
  }

  assert {
    condition     = jsondecode(aws_ecs_task_definition.app.container_definitions)[0].readonlyRootFilesystem == false
    error_message = "apps that must write to disk can opt out"
  }
}

run "logs_go_to_the_supplied_group_and_credentials_come_from_secrets_manager" {
  command = plan

  assert {
    condition = (
      jsondecode(aws_ecs_task_definition.app.container_definitions)[0].logConfiguration.logDriver == "awslogs" &&
      jsondecode(aws_ecs_task_definition.app.container_definitions)[0].logConfiguration.options["awslogs-group"] == "/ecs/lf-demo" &&
      jsondecode(aws_ecs_task_definition.app.container_definitions)[0].logConfiguration.options["awslogs-region"] == "us-east-1"
    )
    error_message = "container logs must go to the monitoring module's log group"
  }

  assert {
    condition = (
      jsondecode(aws_ecs_task_definition.app.container_definitions)[0].secrets == [
        { name = "DB_CREDENTIALS", valueFrom = "arn:aws:secretsmanager:us-east-1:000000000000:secret:rds!db-0000-AbCdEf" }
      ]
    )
    error_message = "database credentials must be injected from Secrets Manager"
  }

  assert {
    condition = alltrue([
      for e in jsondecode(aws_ecs_task_definition.app.container_definitions)[0].environment :
      !can(regex("(?i)pass|secret|token|key", e.name))
    ])
    error_message = "no plain environment variable may carry a credential"
  }
}

# --- Service and placement ----------------------------------------------------------------------

run "service_starts_at_min_tasks_in_the_supplied_private_subnets" {
  command = plan

  assert {
    condition     = aws_ecs_service.app.desired_count == 2 && aws_ecs_service.app.launch_type == "FARGATE"
    error_message = "the service starts at min_tasks on Fargate"
  }

  assert {
    condition     = one(aws_ecs_service.app.network_configuration).subnets == toset(var.private_subnet_ids)
    error_message = "tasks must be placed in the private subnets passed in"
  }

  assert {
    condition     = one(aws_ecs_service.app.network_configuration).assign_public_ip == false
    error_message = "tasks must not get public IPs"
  }

  assert {
    condition     = one(aws_ecs_service.app.deployment_circuit_breaker).enable == true && one(aws_ecs_service.app.deployment_circuit_breaker).rollback == true
    error_message = "a failing deployment must roll back"
  }
}

run "one_active_zone_places_tasks_in_one_subnet" {
  command = plan

  variables {
    private_subnet_ids = ["subnet-0ccccccccccccccc3"]
  }

  assert {
    condition     = length(one(aws_ecs_service.app.network_configuration).subnets) == 1
    error_message = "tasks follow the active subnets the network module reports"
  }
}

run "cluster_has_container_insights" {
  command = plan

  assert {
    condition     = anytrue([for s in aws_ecs_cluster.this.setting : s.name == "containerInsights" && s.value == "enabled"])
    error_message = "Container Insights must be on"
  }
}

# --- Auto scaling -------------------------------------------------------------------------------

run "autoscaling_spans_min_to_max_on_cpu" {
  command = plan

  assert {
    condition     = aws_appautoscaling_target.service.min_capacity == 2 && aws_appautoscaling_target.service.max_capacity == 6
    error_message = "scaling bounds must be min_tasks and max_tasks"
  }

  assert {
    condition     = aws_appautoscaling_target.service.scalable_dimension == "ecs:service:DesiredCount" && aws_appautoscaling_target.service.resource_id == "service/lf-demo-cluster/lf-demo-app"
    error_message = "scaling must target the service's desired count"
  }

  assert {
    condition = (
      aws_appautoscaling_policy.cpu.policy_type == "TargetTrackingScaling" &&
      one(aws_appautoscaling_policy.cpu.target_tracking_scaling_policy_configuration).predefined_metric_specification[0].predefined_metric_type == "ECSServiceAverageCPUUtilization"
    )
    error_message = "scaling is target tracking on average CPU"
  }
}

run "scaling_bounds_follow_the_parameters" {
  command = plan

  variables {
    min_tasks = 4
    max_tasks = 12
  }

  assert {
    condition     = aws_appautoscaling_target.service.min_capacity == 4 && aws_appautoscaling_target.service.max_capacity == 12 && aws_ecs_service.app.desired_count == 4
    error_message = "min_tasks and max_tasks must reach the scaling target and the service"
  }
}

# --- Load balancer ------------------------------------------------------------------------------

run "load_balancer_is_public_in_the_public_subnets_and_hardened" {
  command = plan

  assert {
    condition     = aws_lb.this.internal == false && aws_lb.this.load_balancer_type == "application"
    error_message = "the load balancer is a public Application Load Balancer"
  }

  assert {
    condition     = aws_lb.this.subnets == toset(var.public_subnet_ids)
    error_message = "the load balancer spans both public subnets"
  }

  assert {
    condition     = aws_lb.this.drop_invalid_header_fields == true
    error_message = "invalid headers must be dropped"
  }

  assert {
    condition     = aws_lb.this.enable_deletion_protection == true
    error_message = "deletion protection defaults to on"
  }
}

run "sandbox_teardown_can_turn_load_balancer_protection_off" {
  command = plan

  variables {
    deletion_protection = false
  }

  assert {
    condition     = aws_lb.this.enable_deletion_protection == false
    error_message = "the variable must be able to switch protection off"
  }
}

run "without_a_certificate_only_http_is_served" {
  command = plan

  assert {
    condition     = length(aws_lb_listener.https) == 0
    error_message = "no HTTPS listener without a certificate"
  }

  assert {
    condition     = aws_lb_listener.http.port == 80 && one(aws_lb_listener.http.default_action).type == "forward"
    error_message = "port 80 forwards to the tasks when there is no certificate"
  }

  assert {
    condition     = length([for i in aws_security_group.alb.ingress : i if i.from_port == 443]) == 0
    error_message = "port 443 stays closed without a certificate"
  }
}

run "with_a_certificate_https_is_served_and_http_redirects" {
  command = plan

  variables {
    certificate_arn = "arn:aws:acm:us-east-1:000000000000:certificate/00000000-0000-0000-0000-000000000000"
  }

  assert {
    condition     = length(aws_lb_listener.https) == 1
    error_message = "an HTTPS listener must exist when a certificate is supplied"
  }

  assert {
    condition = (
      aws_lb_listener.https[0].port == 443 &&
      aws_lb_listener.https[0].protocol == "HTTPS" &&
      aws_lb_listener.https[0].certificate_arn == var.certificate_arn &&
      aws_lb_listener.https[0].ssl_policy == "ELBSecurityPolicy-TLS13-1-2-2021-06"
    )
    error_message = "HTTPS uses the supplied certificate and a TLS 1.2+ policy"
  }

  assert {
    condition     = one(aws_lb_listener.http.default_action).type == "redirect" && one(one(aws_lb_listener.http.default_action).redirect).protocol == "HTTPS"
    error_message = "port 80 must redirect to HTTPS"
  }

  assert {
    condition     = length([for i in aws_security_group.alb.ingress : i if i.from_port == 443]) == 1
    error_message = "port 443 opens only when a certificate is supplied"
  }
}

# --- Security groups ------------------------------------------------------------------------------

# Applied against the mock so group ids resolve and can be compared.
run "tasks_accept_traffic_from_the_load_balancer_only" {
  command = apply

  assert {
    condition     = length(aws_security_group.tasks.ingress) == 1
    error_message = "tasks have exactly one ingress rule"
  }

  assert {
    condition = (
      one(aws_security_group.tasks.ingress).from_port == 8080 &&
      one(aws_security_group.tasks.ingress).security_groups == toset([aws_security_group.alb.id])
    )
    error_message = "the rule must be the container port from the load balancer's security group"
  }

  assert {
    condition     = try(length(one(aws_security_group.tasks.ingress).cidr_blocks), 0) == 0
    error_message = "no address range may reach the tasks directly"
  }

  assert {
    condition     = output.task_security_group_id == aws_security_group.tasks.id && output.alb_security_group_id == aws_security_group.alb.id
    error_message = "both security group ids are exported"
  }
}

run "tasks_egress_is_limited_to_https_and_postgres" {
  command = plan

  assert {
    condition     = toset([for e in aws_security_group.tasks.egress : e.from_port]) == toset([443, 5432])
    error_message = "tasks may only reach HTTPS and PostgreSQL"
  }

  assert {
    condition     = alltrue([for e in aws_security_group.tasks.egress : e.protocol == "tcp" && e.from_port == e.to_port])
    error_message = "every egress rule is a single TCP port"
  }

  assert {
    condition     = alltrue([for e in aws_security_group.tasks.egress : e.from_port != 5432 || toset(e.cidr_blocks) == toset([var.vpc_cidr])])
    error_message = "PostgreSQL egress stays inside the VPC"
  }
}

run "load_balancer_egress_reaches_only_the_container_port_in_the_vpc" {
  command = plan

  assert {
    condition     = length(aws_security_group.alb.egress) == 1 && one(aws_security_group.alb.egress).from_port == 8080 && toset(one(aws_security_group.alb.egress).cidr_blocks) == toset([var.vpc_cidr])
    error_message = "the load balancer may only forward to the container port inside the VPC"
  }
}

run "load_balancer_listens_on_80_from_the_internet" {
  command = plan

  assert {
    condition     = anytrue([for i in aws_security_group.alb.ingress : i.from_port == 80 && toset(i.cidr_blocks) == toset(["0.0.0.0/0"])])
    error_message = "the public load balancer accepts HTTP from the internet"
  }
}

# --- Target group and outputs -------------------------------------------------------------------

run "target_group_uses_ip_targets_on_the_container_port" {
  command = plan

  assert {
    condition     = aws_lb_target_group.app.target_type == "ip" && aws_lb_target_group.app.port == 8080 && aws_lb_target_group.app.protocol == "HTTP"
    error_message = "Fargate tasks register by IP on the container port"
  }

  assert {
    condition     = one(aws_lb_target_group.app.health_check).path == "/"
    error_message = "the health check path comes from health_check_path"
  }
}

run "outputs_feed_monitoring_and_dns" {
  command = apply

  assert {
    condition     = output.alb_arn_suffix == "app/lf-demo-alb/0123456789abcdef" && output.alb_dns_name == "lf-demo-alb-123456789.us-east-1.elb.amazonaws.com"
    error_message = "the load balancer identifiers are exported"
  }

  assert {
    condition     = output.cluster_name == "lf-demo-cluster" && output.service_name == "lf-demo-app"
    error_message = "the cluster and service names are exported for the CPU alarm"
  }
}

# --- Validation ---------------------------------------------------------------------------------

run "rejects_a_task_size_outside_the_schema" {
  command = plan

  variables {
    task_size = "4vcpu-8gb"
  }

  expect_failures = [var.task_size]
}

run "rejects_zero_min_tasks" {
  command = plan

  variables {
    min_tasks = 0
  }

  expect_failures = [var.min_tasks]
}

run "rejects_max_tasks_below_min_tasks" {
  command = plan

  variables {
    min_tasks = 5
    max_tasks = 3
  }

  expect_failures = [var.max_tasks]
}

run "rejects_max_tasks_above_twenty" {
  command = plan

  variables {
    max_tasks = 21
  }

  expect_failures = [var.max_tasks]
}

run "rejects_an_empty_container_image" {
  command = plan

  variables {
    container_image = ""
  }

  expect_failures = [var.container_image]
}

run "rejects_three_private_subnets" {
  command = plan

  variables {
    private_subnet_ids = ["subnet-1", "subnet-2", "subnet-3"]
  }

  expect_failures = [var.private_subnet_ids]
}

run "rejects_a_name_prefix_without_the_lf_prefix" {
  command = plan

  variables {
    name_prefix = "demo-app"
  }

  expect_failures = [var.name_prefix]
}

run "rejects_a_name_prefix_longer_than_24_characters" {
  command = plan

  variables {
    name_prefix = "lf-aaaaaaaaaaaaaaaaaaaaaa"
  }

  expect_failures = [var.name_prefix]
}

run "accepts_a_24_character_name_prefix" {
  command = plan

  variables {
    name_prefix = "lf-aaaaaaaaaaaaaaaaaaaaa"
  }
}
