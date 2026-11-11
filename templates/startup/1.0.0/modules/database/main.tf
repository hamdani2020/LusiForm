# Database: RDS PostgreSQL 16 in the isolated data subnets.
#
# Encrypted with a customer-managed key, not publicly accessible, reachable only from the
# compute tasks' security group. The master password is created and rotated-ready in
# Secrets Manager by RDS (manage_master_user_password); no password is in these files.

locals {
  identifier = "${var.name_prefix}-db"

  # Storage autoscaling ceiling.
  max_storage_gb = var.storage_gb * 2
}

resource "aws_kms_key" "database" {
  description             = "${var.name_prefix} database storage encryption"
  enable_key_rotation     = true
  deletion_window_in_days = 7

  tags = merge(var.tags, { Name = "${var.name_prefix}-database-key" })
}

resource "aws_kms_alias" "database" {
  name          = "alias/${var.name_prefix}-database"
  target_key_id = aws_kms_key.database.key_id
}

resource "aws_db_subnet_group" "this" {
  name        = "${var.name_prefix}-db"
  description = "Isolated data subnets for ${var.name_prefix}"
  subnet_ids  = var.subnet_ids

  tags = merge(var.tags, { Name = "${var.name_prefix}-db" })
}

resource "aws_db_parameter_group" "this" {
  name        = "${var.name_prefix}-postgres16"
  description = "PostgreSQL 16 settings for ${var.name_prefix}"
  family      = "postgres16"

  # Require TLS for every connection.
  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  parameter {
    name  = "log_statement"
    value = "ddl"
  }

  parameter {
    name  = "log_min_duration_statement"
    value = "1000"
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-postgres16" })
}

resource "aws_security_group" "database" {
  name        = "${var.name_prefix}-db"
  description = "PostgreSQL access from the application tasks only"
  vpc_id      = var.vpc_id

  # Terraform removes the default allow-all egress rule; the database needs none.
  ingress {
    description     = "PostgreSQL from the application tasks"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [var.allowed_security_group_id]
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-db" })
}

resource "aws_db_instance" "this" {
  identifier = local.identifier

  engine         = "postgres"
  engine_version = var.engine_version
  instance_class = var.instance_class

  allocated_storage     = var.storage_gb
  max_allocated_storage = local.max_storage_gb
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = aws_kms_key.database.arn

  db_name  = "app"
  username = "app_admin"

  # RDS creates and manages the master password in Secrets Manager.
  manage_master_user_password = true

  db_subnet_group_name   = aws_db_subnet_group.this.name
  parameter_group_name   = aws_db_parameter_group.this.name
  vpc_security_group_ids = [aws_security_group.database.id]
  publicly_accessible    = false

  # Multi-AZ keeps a standby in the second zone. A single-zone instance is pinned to the
  # primary zone so it sits next to the tasks; the two settings cannot be combined.
  multi_az          = var.az_count == 2
  availability_zone = var.az_count == 1 ? var.primary_availability_zone : null

  backup_retention_period = var.backup_retention_days
  backup_window           = "03:00-04:00"
  maintenance_window      = "sun:04:30-sun:05:30"

  auto_minor_version_upgrade          = true
  copy_tags_to_snapshot               = true
  iam_database_authentication_enabled = true

  monitoring_interval = 60
  monitoring_role_arn = var.monitoring_role_arn

  deletion_protection       = var.deletion_protection
  skip_final_snapshot       = var.skip_final_snapshot
  final_snapshot_identifier = var.skip_final_snapshot ? null : "${local.identifier}-final"

  tags = merge(var.tags, { Name = local.identifier })
}
