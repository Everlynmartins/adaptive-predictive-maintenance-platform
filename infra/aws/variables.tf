variable "aws_region" {
  description = "AWS Region selected by the local operator for the Stage 3 LAB."
  type        = string
  nullable    = false
}

variable "project_name" {
  description = "Stable project tag and future resource-name prefix."
  type        = string
  default     = "adaptive-predictive-maintenance"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,39}$", var.project_name))
    error_message = "project_name must use 2-40 lowercase letters, digits or hyphens, starting with a letter."
  }
}

variable "environment" {
  description = "Deployment profile. Foundation defaults to the disposable LAB profile."
  type        = string
  default     = "lab"

  validation {
    condition     = contains(["lab", "portfolio"], var.environment)
    error_message = "environment must be either lab or portfolio."
  }
}

variable "managed_by" {
  description = "Tag identifying the infrastructure management mechanism."
  type        = string
  default     = "terraform"
}

variable "owner" {
  description = "Optional non-sensitive owner tag for lifecycle review."
  type        = string
  default     = ""
}

variable "expiration_date" {
  description = "Optional ISO-8601 date tag. It documents intent and does not stop resources."
  type        = string
  default     = ""
}

variable "additional_tags" {
  description = "Optional non-sensitive tags merged with the common tags."
  type        = map(string)
  default     = {}
}

variable "vpc_cidr" {
  description = "Dedicated IPv4 network; /16 through /20 leave room for the three subnets."
  type        = string
  default     = "10.42.0.0/16"
  nullable    = false

  validation {
    condition     = can(cidrnetmask(var.vpc_cidr)) && can(regex("/(16|17|18|19|20)$", var.vpc_cidr))
    error_message = "vpc_cidr must be an IPv4 CIDR with a /16 through /20 prefix."
  }
}

variable "availability_zones" {
  description = "Two distinct standard Availability Zones in aws_region, selected by the operator."
  type        = list(string)
  nullable    = false

  validation {
    condition     = length(var.availability_zones) == 2 && length(distinct(var.availability_zones)) == 2 && alltrue([for zone in var.availability_zones : can(regex("^[a-z]{2}(-[a-z]+)+-[0-9]+[a-z]$", zone))])
    error_message = "Provide exactly two distinct standard Availability Zone names."
  }
}

variable "operator_ipv4_cidr" {
  description = "Operator's current public IPv4 address as /32; only source allowed into API/dashboard."
  type        = string
  nullable    = false

  validation {
    condition     = can(cidrnetmask(var.operator_ipv4_cidr)) && can(regex("/32$", var.operator_ipv4_cidr))
    error_message = "operator_ipv4_cidr must be a single IPv4 address with /32, never a broad network."
  }
}

variable "enable_database_secret_access" {
  description = "Legacy compatibility input for existing tfvars; ECS now always enables access to its exact RDS secret, regardless of this flag."
  type        = bool
  default     = false
}

variable "database_secret_arn" {
  description = "Legacy optional ARN assertion; if supplied it must match the managed RDS ARN. ECS uses that ARN automatically."
  type        = string
  default     = null

  validation {
    condition     = var.database_secret_arn == null ? true : can(regex("^arn:[a-z0-9-]+:secretsmanager:[a-z0-9-]+:[0-9]{12}:secret:[A-Za-z0-9/_+=.@-]+$", var.database_secret_arn))
    error_message = "Use a full Secrets Manager secret ARN without wildcards or JSON-key/version suffixes."
  }
}

variable "ecs_image_tag" {
  description = "Published immutable ECR tag shared by API/dashboard. latest is deliberately rejected."
  type        = string
  default     = "stage3-lab-v1"
  nullable    = false
  validation {
    condition     = var.ecs_image_tag != "latest" && can(regex("^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$", var.ecs_image_tag))
    error_message = "Choose a published versioned Docker tag, not latest."
  }
}

variable "ecs_cpu" {
  description = "Fargate CPU units; 1024 equals one vCPU for the two-container LAB."
  type        = number
  default     = 1024
  nullable    = false
  validation {
    condition     = contains([512, 1024, 2048], var.ecs_cpu)
    error_message = "LAB CPU must be 512, 1024 or 2048 units."
  }
}

variable "ecs_memory" {
  description = "Shared task memory in MiB; initial 4 GiB is provisional pending actual peak measurements."
  type        = number
  default     = 4096
  nullable    = false
  validation {
    condition     = var.ecs_memory >= 4096 && var.ecs_memory <= 16384 && var.ecs_memory % 1024 == 0
    error_message = "LAB memory must be a whole GiB from 4096 through 16384 MiB, paired with supported CPU."
  }
}

variable "ecs_desired_count" {
  description = "Zero by default to avoid paid task startup; explicitly choose one to run the LAB."
  type        = number
  default     = 0
  nullable    = false
  validation {
    condition     = contains([0, 1], var.ecs_desired_count)
    error_message = "LAB desired count must be zero or one."
  }
}

variable "db_name" {
  description = "Initial database name; compatible with the existing SQLAlchemy PostgreSQL schema."
  type        = string
  default     = "predictive_maintenance"
  nullable    = false

  validation {
    condition     = can(regex("^[A-Za-z][A-Za-z0-9_]{0,62}$", var.db_name)) && !contains(["postgres", "template0", "template1"], lower(var.db_name))
    error_message = "db_name must start with a letter, use 1-63 letters/digits/underscores, and not name a system database."
  }
}

variable "db_username" {
  description = "RDS master username for the isolated disposable LAB; this is not a password."
  type        = string
  default     = "pm_lab"
  nullable    = false

  validation {
    condition     = can(regex("^[A-Za-z][A-Za-z0-9_]{0,15}$", var.db_username)) && !contains(["postgres", "rdsadmin"], lower(var.db_username))
    error_message = "Use a non-reserved master username with 1-16 letters/digits/underscores, starting with a letter."
  }
}

variable "db_engine_version" {
  description = "Exact PostgreSQL 16 minor version; verified against regional RDS availability during plan. Major changes need review."
  type        = string
  default     = "16.13"
  nullable    = false

  validation {
    condition     = can(regex("^16\\.[0-9]+$", var.db_engine_version))
    error_message = "Provide an exact PostgreSQL 16 minor version, such as 16.13."
  }
}

variable "db_instance_class" {
  description = "Small configurable RDS class; confirm class/version/gp3 availability and pricing in aws_region before apply."
  type        = string
  default     = "db.t4g.micro"
  nullable    = false

  validation {
    condition     = can(regex("^db\\.[a-z0-9]+\\.[a-z0-9]+$", var.db_instance_class))
    error_message = "Provide an RDS instance class, such as db.t4g.micro."
  }
}

variable "db_allocated_storage" {
  description = "Initial gp3 storage in GiB, limited to 20-100 for this LAB; automatic storage growth is disabled."
  type        = number
  default     = 20
  nullable    = false

  validation {
    condition     = var.db_allocated_storage >= 20 && var.db_allocated_storage <= 100 && floor(var.db_allocated_storage) == var.db_allocated_storage
    error_message = "LAB gp3 storage must be an integer from 20 through 100 GiB."
  }
}
