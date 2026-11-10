# The worker: an ECS Fargate service that long-polls the job queue. It takes no database
# inputs at all; its only data paths are the job queue and the artifact bucket.

locals {
  env = [
    { name = "ENVIRONMENT", value = var.environment },
    { name = "AWS_REGION", value = local.region },
    { name = "SERVICE_NAME", value = "lusiform-worker" },
    { name = "JOB_QUEUE_URL", value = var.job_queue.url },
    { name = "ARTIFACT_BUCKET", value = var.artifact_bucket.name },
  ]
}

resource "aws_cloudwatch_log_group" "this" {
  name              = "/lusiform/${var.environment}/worker"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn
}

resource "aws_ecs_task_definition" "this" {
  family                   = "${var.name_prefix}-worker"
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

  # Scratch space for rendering and validators; the root filesystem stays read-only.
  volume {
    name = "scratch"
  }

  container_definitions = jsonencode([{
    name        = "worker"
    image       = var.image
    essential   = true
    environment = local.env
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.this.name
        awslogs-region        = local.region
        awslogs-stream-prefix = "worker"
      }
    }
    readonlyRootFilesystem = true
    user                   = "10001"
    # The loop finishes its current long poll (<= 20 s) after SIGTERM.
    stopTimeout = 30
    mountPoints = [{ sourceVolume = "scratch", containerPath = "/tmp", readOnly = false }]
  }])
}

resource "aws_ecs_service" "this" {
  name            = "worker"
  cluster         = var.cluster_id
  task_definition = aws_ecs_task_definition.this.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  enable_execute_command = false
  propagate_tags         = "SERVICE"

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = [var.security_group_id]
    assign_public_ip = var.assign_public_ip
  }

  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 200

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
}
