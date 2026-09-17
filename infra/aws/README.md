# Stage 3 AWS Terraform foundation

This directory declares the approved LAB network, ECS IAM roles, one private
ECR repository, a private Single-AZ RDS PostgreSQL instance with an RDS-managed
master secret, and an ECS Fargate service/task with two containers and log groups.
The default desired count is zero: no paid Fargate task starts automatically.
No AWS resources have been deployed by Codex. There are no credentials, database
passwords or connection strings. Scientific artifacts and contracts are unchanged.

The planned LAB architecture is documented in
[`docs/stage3_architecture_plan.md`](../../docs/stage3_architecture_plan.md).
Stage 3 AWS is VALIDATED for LAB, using operator-provided E2E, RDS persistence,
ECS recovery and visual dashboard evidence. See
[`docs/stage3_validation_report.md`](../../docs/stage3_validation_report.md).
Codex did not access AWS or change the applied Terraform. This topology rejects
`environment = "portfolio"`; that profile needs its own reviewed networking change.

## Local prerequisites

- Terraform 1.6 or newer and AWS CLI v2 on the Windows workstation.
- An AWS CLI profile or SSO session already configured locally. This repository
  never runs `aws configure` and must not contain access keys or tokens.
- A selected AWS Region, LAB/PORTFOLIO profile, cost estimate, operator CIDR and
  lifecycle decision as described in the Stage 3 plans.

Check local tooling and the authenticated account without modifying AWS:

```powershell
.\scripts\aws_check.ps1
```

## Configure a local plan

Copy the non-sensitive example, then replace the Region, two available standard
AZs in that Region, and the TEST-NET operator IPv4 `/32` placeholder:

```powershell
Copy-Item .\infra\aws\terraform.tfvars.example .\infra\aws\terraform.tfvars
```

Alternatively, supply the Region for the current shell (AZs and operator CIDR
are still required in the local file or corresponding `TF_VAR_` variables):

```powershell
$env:TF_VAR_aws_region = "your-selected-region"
```

`terraform.tfvars`, `terraform.tfstate*`, plan files and `.terraform/` are
ignored. Keep the generated `.terraform.lock.hcl` under version control after a
reviewed `terraform init`, so provider resolution can be reproduced. Local state
can record resource identifiers later; it must remain protected and never contain
secret values by design.

Run the safe foundation workflow from any directory:

```powershell
.\scripts\terraform_plan.ps1
```

It runs `terraform init`, `terraform fmt`, `terraform validate` and
`terraform plan`. It never runs `terraform apply` or `terraform destroy`.
With all Stage 3 resources already applied and configuration aligned, a plan
should show no changes; investigate drift instead of reapplying blindly. Account/engine discovery
during plan is read-only. Validate needs
no AWS credentials after provider installation. Do not replace existing local
tfvars with the example when incorporating the new database settings.

Before any future apply, review the generated plan, confirm the account and
Region, inspect the pricing estimate, and follow the shutdown/destruction
procedure in [`docs/stage3_resource_lifecycle.md`](../../docs/stage3_resource_lifecycle.md).

## Network and security groups

```text
Operator IPv4/32 -> internet gateway -> future public-IP Fargate task
                                        dashboard :8501 -> loopback API :8000
                                        API -> VPC-local route -> private RDS :5432
                                        ECS agent -> HTTPS public AWS endpoints
```

- Dedicated VPC with DNS support/hostnames, one public task subnet in the first
  selected AZ and two private database subnets in two distinct AZs. The database
  subnet group does not create a database or imply Multi-AZ deployment.
- Public route table: `0.0.0.0/0` through the internet gateway. Public-IP assignment
  is disabled on the subnet; the future Fargate service must explicitly enable it.
- Private route table: only the implicit VPC-local route, no internet route.
  RDS uses this subnet group, database SG, Single-AZ configuration and
  `publicly_accessible = false`.
- Application ingress: TCP 8000 and 8501 only from the operator IPv4 `/32`.
  Database ingress: TCP 5432 only from the application SG.
- Application egress: TCP 5432 only to the database SG; TCP 443 to public
  endpoints. Database has no outbound rules; stateful responses are permitted.
- HTTPS egress uses `0.0.0.0/0` because ECR, S3 image layers, Secrets Manager and
  Logs have changing endpoint addresses. It also permits other HTTPS destinations:
  an explicit LAB limitation. AmazonProvidedDNS is not filtered by SGs.
- No NAT, ALB, service discovery, paid interface endpoints, transit gateway,
  VPN, WAF, replicas or additional high availability.

Containers remain separate components sharing one task network. The future
dashboard uses `APP_BACKEND=api` and
`PREDICTIVE_MAINTENANCE_API_URL=http://127.0.0.1:8000` without direct database access.
External HTTP is restricted to the operator for a temporary simulated benchmark,
not sensitive operational data. CIDR/subnet defaults must be reviewed for overlap
with any future network integration.

## IAM and secrets

- Execution role: ECR authentication, image pull from exactly the future project
  repository, stream creation/writes only in two future project log groups.
  Later resources must reuse `future_resource_names`. Terraform will create log
  groups; the role has no `CreateLogGroup` permission.
- Task role: ECS trust policy only, with no AWS application permissions.
- Trust policies restrict source account/Region. The ECS SourceArn suffix
  wildcard is necessary because ECS does not support scoping this condition to
  one cluster. `ecr:GetAuthorizationToken` requires resource `*`; stream wildcards
  stay inside two named log groups. No AdministratorAccess or general AWS access.
- ECS secret permission references the exact RDS-managed secret automatically.
  The legacy `enable_database_secret_access` input is retained for compatibility
  but no longer disables the permission required by the task. A legacy supplied
  `database_secret_arn` must match the managed ARN. Only `GetSecretValue` is allowed.
- RDS uses `manage_master_user_password = true` and an AWS-managed key.
  There is no password variable, random password, secret-version resource or
  secret-value data source. No secret is output; state contains identifiers only.
- ECS injects username/password JSON fields through the execution role. The
  infrastructure adapter in `runtime/api_bootstrap.py` is embedded in the task
  command, so the published image does not need rebuilding. It builds DATABASE_URL
  in memory using SQLAlchemy escaping, downloads only the public regional RDS CA
  over verified HTTPS, and enables `sslmode=verify-full`. It never logs credentials.
  No `kms:Decrypt` policy is needed here for the AWS-managed key; a customer-managed
  key would require separately scoped permissions and a reviewed change.

References: [ECS execution role](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_execution_IAM_role.html),
[ECS task role trust](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-iam-roles.html),
[VPC security group rules](https://docs.aws.amazon.com/vpc/latest/userguide/security-group-rules.html).

## Checks, cost and lifecycle

```powershell
terraform -chdir=infra/aws init -input=false
terraform -chdir=infra/aws fmt -recursive
terraform -chdir=infra/aws validate
terraform -chdir=infra/aws plan -input=false
```

Only on the operator workstation, after review: create using a reviewed apply;
verify routes, SG restrictions and IAM policies; destroy through Terraform under
the lifecycle plan. Network objects cannot be switched off and are removed by
destroy. RDS, storage and its managed secret introduce costs after the operator's
apply. Log groups are declared; task compute and its public IP only exist when
desired count is explicitly increased to one. Basic
VPC/subnet/route/SG/IAM configuration adds no hourly service charge; task IPv4,
Fargate, RDS, ECR, logs and secrets retain the costs in
the cost plan. Review [VPC pricing](https://aws.amazon.com/vpc/pricing/) locally.

RDS-step checks: Terraform fmt and validate passed locally in Codex, without
plan/apply/destroy or resource-modifying AWS calls. Regional engine/class checks
and actual database health still require the operator's AWS workstation.

## ECR image publication

One private repository stores one Linux x86_64 image reused by the future API
and dashboard containers. The Dockerfile already provides both binaries; ECS
will select each container command. The repository uses basic scan on push,
AWS-managed AES-256 encryption and no replication.

Versioned tags are immutable. Only `latest` is mutable so it can track the most
recent LAB image. The lifecycle policy keeps ten newest manifests; ECR applies
expiration asynchronously. Do not deploy a future ECS task from `latest`:
record a verified versioned tag or digest.

After reviewed local apply, publish without credentials in files:

```powershell
$env:AWS_PROFILE = "stage3-lab"
$env:AWS_REGION = "sa-east-1"
.\scripts\aws_ecr_push.ps1 -VersionTag "stage3-lab-v1"
.\scripts\aws_ecr_check.ps1 -ExpectedTag "stage3-lab-v1"
```

The scripts read Terraform outputs for the repository identity and use the AWS
CLI profile/Region already selected by the operator. They do not embed an account
ID, registry URL or ECR password. The login password remains only in process memory.

## Private RDS LAB

Defaults: database `predictive_maintenance`, master username `pm_lab`, PostgreSQL
16.13, `db.t4g.micro`, 20 GiB gp3, encrypted AWS-managed storage and secret keys.
Version/class/storage/name/username are configurable. The exact minor version is
checked against regional availability during plan; the class/gp3 combination must
also be reviewed locally. PostgreSQL 16 matches the validated Compose engine.

Backup retention is one day. There is no deletion protection, retained automated
backup or final snapshot at destroy. This deliberately discards simulated LAB
data. Automatic minor and major upgrades are disabled; review AWS version notices
and explicitly update when required. No Multi-AZ, replica, proxy, storage growth,
paid monitoring, custom KMS key or networking changes are introduced.

```powershell
$env:AWS_PROFILE = "stage3-lab"
$env:AWS_REGION = "sa-east-1"
.\scripts\terraform_plan.ps1
# After reviewed local apply:
.\scripts\aws_rds_check.ps1
```

Outputs contain only DNS hostname, port, database name, instance identifier and
the managed secret ARN. ECS reuses the existing exact-ARN secret policy. No password is
read by Terraform or the metadata checker. No SQL connection is expected from
Windows to the private database. See the lifecycle document for stop/start and
full-LAB destruction, including the seven-day automatic restart limitation.

## ECS Fargate LAB

One Linux x86_64 task, configurable 1 vCPU/4 GiB initial sizing (not measured),
reuses `stage3-lab-v1` for Uvicorn and Streamlit. Dashboard uses API mode and
loopback `http://127.0.0.1:8000`. Python container health checks require no curl;
dashboard starts after API HEALTHY. Logging retention is seven days. No ALB,
NAT, autoscaling, service discovery or new network resources are added.

```powershell
$env:TF_VAR_ecs_desired_count = "0"
.\scripts\terraform_plan.ps1
# After the operator's reviewed local apply:
.\scripts\aws_ecs_check.ps1  # READY / NOT RUNNING
.\scripts\aws_lab.ps1 start
# Wait for healthy containers:
.\scripts\aws_ecs_check.ps1
.\scripts\aws_ecs_endpoint.ps1
.\scripts\aws_lab.ps1 stop
```

The LAB controller applies a saved Terraform plan locally only if managed changes
are limited to the existing service's desired count. It does not stop/start RDS.
In a new shell, set TF_VAR_ecs_desired_count to the intended zero/one count before
normal plan/apply; avoid overriding it in tfvars. See the resource lifecycle
document for reconciliation, secret rotation, cost and destruction procedures.
The check/endpoint scripts are read-only and never retrieve secret values.
Cloud replay, SQL persistence, startup memory and latency need real AWS validation.
