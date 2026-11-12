# DELIBERATELY INSECURE. This project exists only to prove that the Checkov gate catches
# violations. It is never rendered, packaged, or deployed, and it holds no real credentials.
#
# It breaks three rules on purpose:
#   1. the database is not encrypted at rest and is reachable from the internet,
#   2. an IAM policy allows every action on every resource,
#   3. a security group opens SSH to the world.

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
  region = "us-east-1"
}

variable "db_password" {
  description = "Master password. Supplied by the caller; never stored here."
  type        = string
  sensitive   = true
}

resource "aws_db_instance" "insecure" {
  identifier          = "lf-insecure-db"
  engine              = "postgres"
  engine_version      = "16"
  instance_class      = "db.t4g.micro"
  allocated_storage   = 20
  username            = "app_admin"
  password            = var.db_password
  storage_encrypted   = false
  publicly_accessible = true
  skip_final_snapshot = true
}

resource "aws_iam_policy" "insecure" {
  name = "lf-insecure-policy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "*"
      Resource = "*"
    }]
  })
}

resource "aws_security_group" "insecure" {
  name        = "lf-insecure-sg"
  description = "SSH open to the world"

  ingress {
    description = "SSH from anywhere"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
