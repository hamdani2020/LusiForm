# The API: an ECS Fargate service behind the load balancer, plus two one-off task
# definitions that use the same image and database access:
#
#   migrate    alembic upgrade head, before each API rollout
#   bootstrap  creates the first platform operator (see infra/README.md)

locals {
  common_env = [
    { name = "ENVIRONMENT", value = var.environment },
    { name = "AWS_REGION", value = local.region },
  ]

  # The password is injected from the RDS-managed secret; the rest are not secrets.
  # See the README: the API must assemble its database URL from these.
  db_env = [
    { name = "DB_HOST", value = var.database.address },
    { name = "DB_PORT", value = tostring(var.database.port) },
    { name = "DB_NAME", value = var.database.name },
    { name = "DB_USER", value = var.database.username },
    { name = "DB_SSLMODE", value = "verify-full" },
  ]
  db_secrets = [
    { name = "DB_PASSWORD", valueFrom = "${var.database.master_user_secret_arn}:password::" },
  ]

  api_env = concat(local.common_env, local.db_env, [
    { name = "SERVICE_NAME", value = "lusiform-api" },
    { name = "COGNITO_REGION", value = local.region },
    { name = "COGNITO_USER_POOL_ID", value = var.cognito.user_pool_id },
    { name = "COGNITO_APP_CLIENT_ID", value = var.cognito.web_client_id },
    { name = "JOB_QUEUE_URL", value = var.job_queue.url },
    { name = "ARTIFACT_BUCKET", value = var.artifact_bucket.name },
  ])

  log_config = {
    for name, group in aws_cloudwatch_log_group.this : name => {
      logDriver = "awslogs"
      options = {
        awslogs-group         = group.name
        awslogs-region        = local.region
        awslogs-stream-prefix = name
      }
    }
  }
}

resource "aws_cloudwatch_log_group" "this" {
  for_each = toset(["api", "migrate", "bootstrap"])

  name              = "/lusiform/${var.environment}/${each.key}"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn
}

# --- the API service ---

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.name_prefix}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name                   = "api"
    image                  = var.image
    essential              = true
    portMappings           = [{ containerPort = var.container_port, protocol = "tcp" }]
    environment            = local.api_env
    secrets                = local.db_secrets
    logConfiguration       = local.log_config["api"]
    readonlyRootFilesystem = true
    user                   = "10001"
    stopTimeout            = 30
  }])
}

# Orders the service after the HTTPS listener without a module-wide depends_on (which
# would defer this module's data sources to apply time).
resource "terraform_data" "listener_ready" {
  input = var.load_balancer_listener_arn
}

resource "aws_ecs_service" "api" {
  name            = "api"
  cluster         = var.cluster_id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  enable_execute_command = false
  propagate_tags         = "SERVICE"

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = [var.security_group_id]
    assign_public_ip = var.assign_public_ip
  }

  load_balancer {
    target_group_arn = var.target_group_arn
    container_name   = "api"
    container_port   = var.container_port
  }

  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200
  health_check_grace_period_seconds  = 30

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  depends_on = [terraform_data.listener_ready]
}

# --- one-off tasks (run with aws ecs run-task; see infra/README.md) ---

resource "aws_ecs_task_definition" "migrate" {
  family                   = "${var.name_prefix}-migrate"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name             = "migrate"
    image            = var.image
    essential        = true
    command          = ["alembic", "upgrade", "head"]
    environment      = concat(local.common_env, local.db_env, [{ name = "SERVICE_NAME", value = "lusiform-migrate" }])
    secrets          = local.db_secrets
    logConfiguration = local.log_config["migrate"]
    user             = "10001"
  }])
}

# The command's arguments are supplied at run time with --overrides.
resource "aws_ecs_task_definition" "bootstrap" {
  family                   = "${var.name_prefix}-bootstrap"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name             = "bootstrap"
    image            = var.image
    essential        = true
    command          = ["python", "-m", "app.bootstrap_operator", "--help"]
    environment      = concat(local.common_env, local.db_env, [{ name = "SERVICE_NAME", value = "lusiform-bootstrap" }])
    secrets          = local.db_secrets
    logConfiguration = local.log_config["bootstrap"]
    user             = "10001"
  }])
}
