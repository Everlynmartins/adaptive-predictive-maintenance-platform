# The exact configured minor version must be supported in the selected Region.
# This lookup is read-only during the operator's plan, not performed by Codex.
data "aws_rds_engine_version" "postgres" {
  engine  = "postgres"
  version = var.db_engine_version
}

resource "aws_db_instance" "lab" {
  identifier               = "${local.name_prefix}-db"
  engine                   = "postgres"
  engine_version           = data.aws_rds_engine_version.postgres.version
  engine_lifecycle_support = "open-source-rds-extended-support-disabled"
  instance_class           = var.db_instance_class
  db_name                  = var.db_name
  username                 = var.db_username
  port                     = 5432

  manage_master_user_password = true
  storage_encrypted           = true
  storage_type                = "gp3"
  allocated_storage           = var.db_allocated_storage
  max_allocated_storage       = 0

  db_subnet_group_name   = aws_db_subnet_group.lab.name
  vpc_security_group_ids = [aws_security_group.database.id]
  availability_zone      = var.availability_zones[0]
  multi_az               = false
  publicly_accessible    = false

  backup_retention_period     = 1
  delete_automated_backups    = true
  deletion_protection         = false
  skip_final_snapshot         = true
  copy_tags_to_snapshot       = true
  auto_minor_version_upgrade  = false
  allow_major_version_upgrade = false
  apply_immediately           = false

  monitoring_interval             = 0
  performance_insights_enabled    = false
  enabled_cloudwatch_logs_exports = []

  tags = { Name = "${local.name_prefix}-db" }

  depends_on = [
    aws_vpc_security_group_ingress_rule.postgresql,
    aws_vpc_security_group_egress_rule.postgresql,
  ]

  lifecycle {
    precondition {
      condition     = data.aws_rds_engine_version.postgres.version == var.db_engine_version
      error_message = "The exact configured PostgreSQL minor version must be available; no silent version substitution."
    }
  }
}
