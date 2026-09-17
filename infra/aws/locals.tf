locals {
  name_prefix         = "${var.project_name}-${var.environment}"
  ecr_repository_name = local.name_prefix
  log_group_names = {
    api       = "/${local.name_prefix}/api"
    dashboard = "/${local.name_prefix}/dashboard"
  }
  private_subnets = {
    a = { zone = var.availability_zones[0], cidr = cidrsubnet(var.vpc_cidr, 8, 10) }
    b = { zone = var.availability_zones[1], cidr = cidrsubnet(var.vpc_cidr, 8, 11) }
  }
  common_tags = merge(
    var.additional_tags,
    {
      project     = var.project_name
      environment = var.environment
      managed_by  = var.managed_by
      stage       = "3"
    },
    var.owner != "" ? { owner = var.owner } : {},
    var.expiration_date != "" ? { expiration_date = var.expiration_date } : {},
  )
}
