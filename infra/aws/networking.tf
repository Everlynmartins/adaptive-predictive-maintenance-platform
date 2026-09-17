# LAB only: one public task subnet; two private subnets meet the RDS subnet-group
# requirement without creating another database or adding high availability.
resource "aws_vpc" "lab" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = local.name_prefix }

  lifecycle {
    precondition {
      condition     = var.environment == "lab"
      error_message = "This topology implements the approved LAB only; PORTFOLIO needs a separate reviewed change."
    }
    precondition {
      condition     = alltrue([for zone in var.availability_zones : startswith(zone, var.aws_region) && length(zone) == length(var.aws_region) + 1])
      error_message = "Both Availability Zones must belong to aws_region."
    }
  }
}

resource "aws_internet_gateway" "lab" {
  vpc_id = aws_vpc.lab.id
  tags   = { Name = "${local.name_prefix}-internet" }
}

resource "aws_subnet" "public_task" {
  vpc_id                  = aws_vpc.lab.id
  availability_zone       = var.availability_zones[0]
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, 0)
  map_public_ip_on_launch = false # Future Fargate task must explicitly assign its public IP.
  tags                    = { Name = "${local.name_prefix}-public-task" }
}

resource "aws_subnet" "private_database" {
  for_each                = local.private_subnets
  vpc_id                  = aws_vpc.lab.id
  availability_zone       = each.value.zone
  cidr_block              = each.value.cidr
  map_public_ip_on_launch = false
  tags                    = { Name = "${local.name_prefix}-private-db-${each.key}" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.lab.id
  tags   = { Name = "${local.name_prefix}-public" }
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.lab.id
}

resource "aws_route_table_association" "public_task" {
  subnet_id      = aws_subnet.public_task.id
  route_table_id = aws_route_table.public.id
}

# Only the automatically provided VPC-local route: no NAT or internet route.
resource "aws_route_table" "private_database" {
  vpc_id = aws_vpc.lab.id
  tags   = { Name = "${local.name_prefix}-private-db" }
}

resource "aws_route_table_association" "private_database" {
  for_each       = aws_subnet.private_database
  subnet_id      = each.value.id
  route_table_id = aws_route_table.private_database.id
}

resource "aws_db_subnet_group" "lab" {
  name       = "${local.name_prefix}-db"
  subnet_ids = [for subnet in aws_subnet.private_database : subnet.id]
  tags       = { Name = "${local.name_prefix}-db" }
}
