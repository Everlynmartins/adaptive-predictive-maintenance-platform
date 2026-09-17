# ECS requires this permission even when the service is initially scaled to zero.
# Reuse the existing policy address; only the exact RDS-managed ARN is permitted.
resource "aws_iam_role_policy" "database_secret" {
  count = 1
  name  = "read-specific-database-secret"
  role  = aws_iam_role.task_execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "secretsmanager:GetSecretValue"
      Resource = aws_db_instance.lab.master_user_secret[0].secret_arn
    }]
  })

  lifecycle {
    precondition {
      condition     = var.database_secret_arn == null ? true : var.database_secret_arn == aws_db_instance.lab.master_user_secret[0].secret_arn
      error_message = "A legacy database_secret_arn override must match the exact RDS-managed secret ARN."
    }
  }
}
