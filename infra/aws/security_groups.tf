# No inline rules: all ingress/egress is explicitly managed below.
resource "aws_security_group" "application" {
  name        = "${local.name_prefix}-application"
  description = "LAB task: operator-only ingress, HTTPS and database egress"
  vpc_id      = aws_vpc.lab.id
  tags        = { Name = "${local.name_prefix}-application" }
}

resource "aws_security_group" "database" {
  name        = "${local.name_prefix}-database"
  description = "Private PostgreSQL: application task only"
  vpc_id      = aws_vpc.lab.id
  tags        = { Name = "${local.name_prefix}-database" }
}

resource "aws_vpc_security_group_ingress_rule" "operator" {
  for_each          = { api = 8000, dashboard = 8501 }
  security_group_id = aws_security_group.application.id
  description       = "Operator access to ${each.key}; temporary simulated LAB HTTP"
  cidr_ipv4         = var.operator_ipv4_cidr
  ip_protocol       = "tcp"
  from_port         = each.value
  to_port           = each.value
}

resource "aws_vpc_security_group_ingress_rule" "postgresql" {
  security_group_id            = aws_security_group.database.id
  referenced_security_group_id = aws_security_group.application.id
  description                  = "PostgreSQL from application task only"
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_vpc_security_group_egress_rule" "postgresql" {
  security_group_id            = aws_security_group.application.id
  referenced_security_group_id = aws_security_group.database.id
  description                  = "Application to private PostgreSQL"
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

# Public ECR (including image layers in S3), Logs and Secrets Manager endpoints
# have changing addresses. Limit the protocol/port, not an unreliable IP list.
resource "aws_vpc_security_group_egress_rule" "aws_https" {
  security_group_id = aws_security_group.application.id
  description       = "HTTPS to AWS public endpoints without NAT or paid VPC endpoints"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

# Database has no outbound rules. Security groups permit stateful responses.
# Same-task dashboard -> API uses loopback, not a separate ingress rule.
