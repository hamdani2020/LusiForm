# Database module tests. Mocked AWS provider: no credentials, no AWS calls.

mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "000000000000"
    }
  }

  mock_data "aws_partition" {
    defaults = {
      partition = "aws"
    }
  }

  mock_resource "aws_kms_key" {
    defaults = {
      arn = "arn:aws:kms:us-east-1:000000000000:key/00000000-0000-0000-0000-000000000000"
    }
  }

  mock_resource "aws_db_instance" {
    defaults = {
      address = "lf-demo-db.example.us-east-1.rds.amazonaws.com"
      port    = 5432
      master_user_secret = [{
        secret_arn    = "arn:aws:secretsmanager:us-east-1:000000000000:secret:rds!db-0000-AbCdEf"
        kms_key_id    = "alias/aws/secretsmanager"
        secret_status = "active"
      }]
    }
  }
}

variables {
  name_prefix               = "lf-demo"
  vpc_id                    = "vpc-0123456789abcdef0"
  subnet_ids                = ["subnet-0aaaaaaaaaaaaaaa1", "subnet-0bbbbbbbbbbbbbbb2"]
  primary_availability_zone = "us-east-1a"
  allowed_security_group_id = "sg-0123456789abcdef0"
  monitoring_role_arn       = "arn:aws:iam::000000000000:role/lf-demo-rds-monitoring"
  instance_class            = "db.t3.micro"
  storage_gb                = 20
  backup_retention_days     = 7
  az_count                  = 2
}

run "engine_is_postgres_16_with_the_chosen_sizing" {
  command = plan

  variables {
    instance_class        = "db.t3.small"
    storage_gb            = 100
    backup_retention_days = 14
  }

  assert {
    condition     = aws_db_instance.this.engine == "postgres" && aws_db_instance.this.engine_version == "16"
    error_message = "the database must be PostgreSQL 16"
  }

  assert {
    condition     = aws_db_instance.this.instance_class == "db.t3.small"
    error_message = "instance_class must reach the instance"
  }

  assert {
    condition     = aws_db_instance.this.allocated_storage == 100 && aws_db_instance.this.max_allocated_storage == 200
    error_message = "storage autoscaling must be allowed up to twice the allocated storage"
  }

  assert {
    condition     = aws_db_instance.this.backup_retention_period == 14
    error_message = "backup_retention_days must reach the instance"
  }

  assert {
    condition     = aws_db_instance.this.identifier == "lf-demo-db"
    error_message = "the identifier is derived from the name prefix"
  }
}

# Applied against the mock so the key ARN resolves and can be compared.
run "storage_is_encrypted_with_the_customer_managed_key" {
  command = apply

  assert {
    condition     = aws_db_instance.this.storage_encrypted == true && aws_db_instance.this.kms_key_id == aws_kms_key.database.arn
    error_message = "database storage must be encrypted with the module's customer-managed key"
  }

  assert {
    condition     = aws_kms_key.database.enable_key_rotation == true
    error_message = "key rotation must be on"
  }

  assert {
    condition     = output.kms_key_arn == aws_kms_key.database.arn
    error_message = "the key ARN must be exported"
  }
}

run "key_policy_is_the_default_one_written_out" {
  command = plan

  assert {
    condition     = length(jsondecode(aws_kms_key.database.policy).Statement) == 1
    error_message = "the key policy has exactly one statement"
  }

  assert {
    condition = (
      jsondecode(aws_kms_key.database.policy).Statement[0].Principal.AWS == "arn:aws:iam::000000000000:root" &&
      jsondecode(aws_kms_key.database.policy).Statement[0].Action == "kms:*" &&
      jsondecode(aws_kms_key.database.policy).Statement[0].Effect == "Allow"
    )
    error_message = "the account administers the key and delegates use through IAM; no other principal"
  }
}

run "database_is_private_and_holds_no_password" {
  command = plan

  assert {
    condition     = aws_db_instance.this.publicly_accessible == false
    error_message = "the database must not be publicly accessible"
  }

  assert {
    condition     = aws_db_instance.this.manage_master_user_password == true
    error_message = "RDS must create and hold the master password in Secrets Manager"
  }

  assert {
    condition     = aws_db_instance.this.password == null && aws_db_instance.this.password_wo == null
    error_message = "no password may be set in configuration"
  }

  assert {
    condition     = aws_db_instance.this.iam_database_authentication_enabled == true
    error_message = "IAM database authentication must be on"
  }
}

run "two_zones_means_multi_az_and_no_pinned_zone" {
  command = plan

  variables {
    az_count = 2
  }

  assert {
    condition     = aws_db_instance.this.multi_az == true
    error_message = "az_count = 2 must give the database a standby in the second zone"
  }

  # availability_zone is optional and computed, so the mock fills in a random value where AWS
  # would pick a zone. What matters is that the config does not pin it to the primary zone.
  assert {
    condition     = aws_db_instance.this.availability_zone != var.primary_availability_zone
    error_message = "a Multi-AZ instance must not be pinned to a zone"
  }
}

run "one_zone_means_single_az_pinned_next_to_the_tasks" {
  command = plan

  variables {
    az_count = 1
  }

  assert {
    condition     = aws_db_instance.this.multi_az == false
    error_message = "az_count = 1 must not create a standby"
  }

  assert {
    condition     = aws_db_instance.this.availability_zone == "us-east-1a"
    error_message = "a single-zone database must sit in the primary zone"
  }
}

run "security_group_accepts_postgres_only_from_the_task_group" {
  command = plan

  assert {
    condition     = length(aws_security_group.database.ingress) == 1
    error_message = "exactly one ingress rule"
  }

  assert {
    condition = (
      one(aws_security_group.database.ingress).from_port == 5432 &&
      one(aws_security_group.database.ingress).to_port == 5432 &&
      one(aws_security_group.database.ingress).protocol == "tcp" &&
      one(aws_security_group.database.ingress).security_groups == toset(["sg-0123456789abcdef0"])
    )
    error_message = "the rule must be PostgreSQL from the task security group"
  }

  assert {
    condition     = try(length(one(aws_security_group.database.ingress).cidr_blocks), 0) == 0 && try(length(one(aws_security_group.database.ingress).ipv6_cidr_blocks), 0) == 0
    error_message = "no address range may be allowed to reach the database"
  }

  assert {
    condition     = length(aws_security_group.database.egress) == 0
    error_message = "the database needs no egress rules"
  }
}

run "subnet_group_uses_the_data_subnets" {
  command = plan

  assert {
    condition     = aws_db_subnet_group.this.subnet_ids == toset(var.subnet_ids)
    error_message = "the database must live in the isolated data subnets"
  }
}

run "tls_is_required" {
  command = plan

  assert {
    condition     = aws_db_parameter_group.this.family == "postgres16"
    error_message = "the parameter group must match PostgreSQL 16"
  }

  assert {
    condition     = anytrue([for p in aws_db_parameter_group.this.parameter : p.name == "rds.force_ssl" && p.value == "1"])
    error_message = "rds.force_ssl must be 1 so every connection uses TLS"
  }
}

run "enhanced_monitoring_and_minor_upgrades_are_on" {
  command = plan

  assert {
    condition     = aws_db_instance.this.monitoring_interval == 60 && aws_db_instance.this.monitoring_role_arn == var.monitoring_role_arn
    error_message = "enhanced monitoring must use the supplied role"
  }

  assert {
    condition     = aws_db_instance.this.auto_minor_version_upgrade == true && aws_db_instance.this.copy_tags_to_snapshot == true
    error_message = "minor upgrades and tag copying must be on"
  }

  assert {
    condition     = aws_db_instance.this.backup_window != null && aws_db_instance.this.maintenance_window != null
    error_message = "fixed windows keep behaviour deterministic"
  }
}

run "deletion_protection_and_final_snapshot_are_on_by_default" {
  command = plan

  assert {
    condition     = aws_db_instance.this.deletion_protection == true
    error_message = "deletion protection must default to on"
  }

  assert {
    condition     = aws_db_instance.this.skip_final_snapshot == false && aws_db_instance.this.final_snapshot_identifier == "lf-demo-db-final"
    error_message = "a final snapshot must be taken by default"
  }
}

run "sandbox_teardown_can_turn_protection_off" {
  command = plan

  variables {
    deletion_protection = false
    skip_final_snapshot = true
  }

  assert {
    condition     = aws_db_instance.this.deletion_protection == false && aws_db_instance.this.skip_final_snapshot == true
    error_message = "the variables must be able to switch protection off"
  }

  assert {
    condition     = aws_db_instance.this.final_snapshot_identifier == null
    error_message = "no snapshot identifier when the final snapshot is skipped"
  }
}

run "outputs_expose_connection_details_but_never_a_password" {
  command = apply

  assert {
    condition     = output.address == "lf-demo-db.example.us-east-1.rds.amazonaws.com" && output.port == 5432 && output.db_name == "app"
    error_message = "connection details must be exported"
  }

  assert {
    condition     = output.master_user_secret_arn == "arn:aws:secretsmanager:us-east-1:000000000000:secret:rds!db-0000-AbCdEf"
    error_message = "only the secret's ARN is exported"
  }
}

run "rejects_an_instance_class_outside_the_schema" {
  command = plan

  variables {
    instance_class = "db.r6g.large"
  }

  expect_failures = [var.instance_class]
}

run "rejects_storage_below_the_minimum" {
  command = plan

  variables {
    storage_gb = 10
  }

  expect_failures = [var.storage_gb]
}

run "rejects_storage_above_the_maximum" {
  command = plan

  variables {
    storage_gb = 1001
  }

  expect_failures = [var.storage_gb]
}

run "rejects_backup_retention_outside_one_to_thirty_five" {
  command = plan

  variables {
    backup_retention_days = 36
  }

  expect_failures = [var.backup_retention_days]
}

run "rejects_a_third_zone" {
  command = plan

  variables {
    az_count = 3
  }

  expect_failures = [var.az_count]
}

run "rejects_another_major_version" {
  command = plan

  variables {
    engine_version = "15"
  }

  expect_failures = [var.engine_version]
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
