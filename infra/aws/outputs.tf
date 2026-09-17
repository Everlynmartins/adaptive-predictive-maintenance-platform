output "stage3_foundation" {
  description = "Non-sensitive LAB configuration settings."

  value = {
    aws_region  = var.aws_region
    environment = var.environment
    tags        = local.common_tags
  }
}

output "lab_network" {
  description = "Identifiers for the future Fargate task and private Single-AZ RDS."
  value = {
    vpc_id                        = aws_vpc.lab.id
    public_task_subnet_id         = aws_subnet.public_task.id
    private_database_subnet_ids   = [for subnet in aws_subnet.private_database : subnet.id]
    database_subnet_group_name    = aws_db_subnet_group.lab.name
    application_security_group_id = aws_security_group.application.id
    database_security_group_id    = aws_security_group.database.id
  }
}

output "ecs_role_arns" {
  description = "Separate execution and application roles; no credentials."
  value = {
    execution = aws_iam_role.task_execution.arn
    task      = aws_iam_role.task.arn
  }
}

output "future_resource_names" {
  description = "Naming contract for future scoped IAM and logging resources."
  value = {
    ecr_repository = local.ecr_repository_name
    log_groups     = local.log_group_names
  }
}

output "ecr_repository_name" {
  description = "Non-sensitive private ECR repository name for the shared application image."
  value       = aws_ecr_repository.application.name
}

output "ecr_repository_url" {
  description = "Non-sensitive private ECR repository URI for Docker tagging and push."
  value       = aws_ecr_repository.application.repository_url
}

output "rds_endpoint" {
  description = "Private RDS DNS hostname without port or credentials."
  value       = aws_db_instance.lab.address
}

output "rds_port" {
  description = "Private PostgreSQL port."
  value       = aws_db_instance.lab.port
}

output "rds_database_name" {
  description = "Initial LAB database name."
  value       = aws_db_instance.lab.db_name
}

output "rds_instance_identifier" {
  description = "Identifier for read-only checks and operator-controlled lifecycle actions."
  value       = aws_db_instance.lab.identifier
}

output "rds_master_secret_arn" {
  description = "Identifier only of the RDS-managed master secret; never its value."
  value       = aws_db_instance.lab.master_user_secret[0].secret_arn
}

output "ecs_cluster_name" {
  value       = aws_ecs_cluster.lab.name
  description = "Non-sensitive LAB cluster name."
}

output "ecs_service_name" {
  value       = aws_ecs_service.lab.name
  description = "Non-sensitive LAB service name."
}

output "ecs_task_definition_arn" {
  value       = aws_ecs_task_definition.lab.arn
  description = "Configured task revision; no secret values are present."
}

output "ecs_desired_count" {
  value       = var.ecs_desired_count
  description = "Declared zero/one task count; dynamic IP must be discovered through ECS/EC2."
}

output "cloudwatch_log_group_names" {
  value       = { for key, group in aws_cloudwatch_log_group.application : key => group.name }
  description = "Non-sensitive application log group names."
}
