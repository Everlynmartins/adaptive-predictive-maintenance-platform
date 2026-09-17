# One image contains the frozen artifacts and Python runtime used by both containers.
# API and Streamlit remain distinct ECS containers with different commands.
resource "aws_ecr_repository" "application" {
  name                 = local.ecr_repository_name
  image_tag_mutability = "IMMUTABLE_WITH_EXCLUSION"
  force_delete         = false

  # A human-friendly moving tag is useful in LAB; versioned tags stay immutable.
  image_tag_mutability_exclusion_filter {
    filter      = "latest"
    filter_type = "WILDCARD"
  }

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = { Name = local.ecr_repository_name }
}

# Keeps the ten most recent image manifests regardless of tag.
# ECR expiration is asynchronous and no image is selected by more than one rule.
resource "aws_ecr_lifecycle_policy" "application" {
  repository = aws_ecr_repository.application.name
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep the ten newest LAB image manifests"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = { type = "expire" }
      },
    ]
  })
}
