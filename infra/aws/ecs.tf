resource "aws_cloudwatch_log_group" "application" {
  for_each          = local.log_group_names
  name              = each.value
  retention_in_days = 7
}

resource "aws_ecs_cluster" "lab" {
  name = local.name_prefix
  setting {
    name  = "containerInsights"
    value = "disabled"
  }
}

resource "aws_ecs_task_definition" "lab" {
  family                   = local.name_prefix
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = tostring(var.ecs_cpu)
  memory                   = tostring(var.ecs_memory)
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name              = "api"
      image             = "${aws_ecr_repository.application.repository_url}:${var.ecs_image_tag}"
      essential         = true
      cpu               = floor(var.ecs_cpu * 0.75)
      memoryReservation = floor(var.ecs_memory * 0.75)
      workingDirectory  = "/app"
      startTimeout      = 120
      command           = ["python", "-c", file("${path.module}/runtime/api_bootstrap.py")]
      portMappings      = [{ containerPort = 8000, hostPort = 8000, protocol = "tcp" }]
      environment = [
        { name = "PREDICTIVE_MAINTENANCE_PROJECT_ROOT", value = "/app" },
        { name = "AWS_REGION", value = var.aws_region },
        { name = "DB_HOST", value = aws_db_instance.lab.address },
        { name = "DB_PORT", value = tostring(aws_db_instance.lab.port) },
        { name = "DB_NAME", value = aws_db_instance.lab.db_name },
      ]
      secrets = [
        { name = "DB_USERNAME", valueFrom = "${aws_db_instance.lab.master_user_secret[0].secret_arn}:username::" },
        { name = "DB_PASSWORD", valueFrom = "${aws_db_instance.lab.master_user_secret[0].secret_arn}:password::" },
      ]
      healthCheck = {
        command     = ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=10).close()"]
        interval    = 30
        timeout     = 15
        retries     = 3
        startPeriod = 180
      }
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.application["api"].name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
        }
      }
    },
    {
      name              = "dashboard"
      image             = "${aws_ecr_repository.application.repository_url}:${var.ecs_image_tag}"
      essential         = true
      cpu               = var.ecs_cpu - floor(var.ecs_cpu * 0.75)
      memoryReservation = floor(var.ecs_memory * 0.125)
      workingDirectory  = "/app"
      command           = ["streamlit", "run", "src/predictive_maintenance/ui/streamlit_app.py", "--server.address=0.0.0.0", "--server.port=8501", "--browser.gatherUsageStats=false"]
      portMappings      = [{ containerPort = 8501, hostPort = 8501, protocol = "tcp" }]
      environment = [
        { name = "PREDICTIVE_MAINTENANCE_PROJECT_ROOT", value = "/app" },
        { name = "APP_BACKEND", value = "api" },
        { name = "PREDICTIVE_MAINTENANCE_API_URL", value = "http://127.0.0.1:8000" },
      ]
      dependsOn = [{ containerName = "api", condition = "HEALTHY" }]
      healthCheck = {
        command     = ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=10).close()"]
        interval    = 30
        timeout     = 15
        retries     = 3
        startPeriod = 120
      }
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.application["dashboard"].name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
        }
      }
    },
  ])

  lifecycle {
    precondition {
      condition     = (var.ecs_cpu == 512 && var.ecs_memory == 4096) || (var.ecs_cpu == 1024 && var.ecs_memory <= 8192) || (var.ecs_cpu == 2048 && var.ecs_memory <= 16384)
      error_message = "Choose a supported Fargate CPU/memory combination (at least 4 GiB for this LAB runtime)."
    }
  }
}

resource "aws_ecs_service" "lab" {
  name                               = local.name_prefix
  cluster                            = aws_ecs_cluster.lab.id
  task_definition                    = aws_ecs_task_definition.lab.arn
  desired_count                      = var.ecs_desired_count
  launch_type                        = "FARGATE"
  platform_version                   = "1.4.0"
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100
  health_check_grace_period_seconds  = 300

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = [aws_subnet.public_task.id]
    security_groups  = [aws_security_group.application.id]
    assign_public_ip = true
  }

  depends_on = [
    aws_iam_role_policy.task_execution,
    aws_iam_role_policy.database_secret,
    aws_route.public_internet,
    aws_route_table_association.public_task,
  ]
}
