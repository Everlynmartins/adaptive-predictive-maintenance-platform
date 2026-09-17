$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$TerraformRoot = Join-Path $ProjectRoot "infra\aws"

function Require-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name nao encontrado no PATH."
    }
}

function Invoke-ReadNative {
    param([string]$FileName, [string[]]$Arguments)
    $savedPreference = $ErrorActionPreference
    try {
        # Native stderr is displayed; only the process exit code decides failure.
        $ErrorActionPreference = "Continue"
        $output = & $FileName @Arguments
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $savedPreference
    }
    if ($exitCode -ne 0) {
        throw "$FileName $($Arguments -join ' ') falhou com exit code $exitCode."
    }
    return ($output | Out-String).Trim()
}

function Get-TerraformOutput {
    param([string]$Name)
    $value = Invoke-ReadNative -FileName "terraform" -Arguments @("-chdir=$TerraformRoot", "output", "-raw", $Name)
    if ([string]::IsNullOrWhiteSpace($value)) { throw "Output Terraform '$Name' ausente; execute o apply aprovado primeiro." }
    return $value
}

try {
    Require-Command aws
    Require-Command terraform
    $region = $env:AWS_REGION
    if ([string]::IsNullOrWhiteSpace($region)) { $region = $env:AWS_DEFAULT_REGION }
    if ([string]::IsNullOrWhiteSpace($region)) {
        $region = Invoke-ReadNative -FileName "aws" -Arguments @("configure", "get", "region")
    }
    if ([string]::IsNullOrWhiteSpace($region)) { throw "Defina AWS_REGION ou a regiao do perfil AWS." }
    # AWS_PROFILE is inherited by AWS CLI; no credentials or profile are embedded.
    $identifier = Get-TerraformOutput -Name "rds_instance_identifier"
    $expectedEndpoint = Get-TerraformOutput -Name "rds_endpoint"
    $expectedPort = [int](Get-TerraformOutput -Name "rds_port")
    $expectedDatabase = Get-TerraformOutput -Name "rds_database_name"
    $expectedSecretArn = Get-TerraformOutput -Name "rds_master_secret_arn"
    $network = (Invoke-ReadNative -FileName "terraform" -Arguments @("-chdir=$TerraformRoot", "output", "-json", "lab_network")) | ConvertFrom-Json

    $response = (Invoke-ReadNative -FileName "aws" -Arguments @("rds", "describe-db-instances", "--db-instance-identifier", $identifier, "--region", $region, "--output", "json", "--no-cli-pager")) | ConvertFrom-Json
    $instances = @($response.DBInstances)
    if ($instances.Count -ne 1) { throw "Instancia RDS nao encontrada de forma unica." }
    $db = $instances[0]
    $secretConfigured = -not [string]::IsNullOrWhiteSpace($db.MasterUserSecret.SecretArn)

    Write-Host "RDS status: $($db.DBInstanceStatus)"
    Write-Host "Engine: $($db.Engine) $($db.EngineVersion)"
    Write-Host "Endpoint: $($db.Endpoint.Address):$($db.Endpoint.Port)"
    Write-Host "Public access: $($db.PubliclyAccessible)"
    Write-Host "Multi AZ: $($db.MultiAZ)"
    Write-Host "Secret configured: $secretConfigured"
    Write-Host "Class: $($db.DBInstanceClass); storage: $($db.AllocatedStorage) GiB $($db.StorageType); encrypted: $($db.StorageEncrypted)"
    Write-Host "DB subnet group: $($db.DBSubnetGroup.DBSubnetGroupName)"
    Write-Host "Security Groups: $((@($db.VpcSecurityGroups) | ForEach-Object { $_.VpcSecurityGroupId }) -join ', ')"

    $failures = @()
    if ($db.DBInstanceIdentifier -ne $identifier) { $failures += "Identificador diferente do output Terraform." }
    if ($db.Engine -ne "postgres" -or $db.EngineVersion -notmatch '^16\.[0-9]+') { $failures += "Engine deve ser PostgreSQL 16." }
    if ($db.DBInstanceStatus -ne "available") { $failures += "RDS ainda nao esta available; aguarde ou investigue o status." }
    if ($db.PubliclyAccessible -ne $false) { $failures += "RDS deve permanecer privado." }
    if ($db.MultiAZ -ne $false) { $failures += "Multi AZ nao pertence ao LAB." }
    if ($db.Endpoint.Address -ne $expectedEndpoint -or $db.Endpoint.Port -ne $expectedPort -or $expectedPort -ne 5432) { $failures += "Endpoint/porta diferentes do contrato Terraform." }
    if ($db.DBName -ne $expectedDatabase) { $failures += "Database name diferente do output Terraform." }
    if ($db.DBSubnetGroup.DBSubnetGroupName -ne $network.database_subnet_group_name -or $db.DBSubnetGroup.VpcId -ne $network.vpc_id) { $failures += "DB subnet group/VPC diferentes da fundacao aplicada." }
    $actualSubnets = @($db.DBSubnetGroup.Subnets | ForEach-Object { $_.SubnetIdentifier })
    if (@(Compare-Object -ReferenceObject @($network.private_database_subnet_ids) -DifferenceObject $actualSubnets).Count -gt 0) { $failures += "Subnets diferentes das privadas esperadas." }
    $actualGroups = @($db.VpcSecurityGroups | ForEach-Object { $_.VpcSecurityGroupId })
    if ($actualGroups.Count -ne 1 -or $actualGroups[0] -ne $network.database_security_group_id) { $failures += "Security Group diferente do grupo de banco esperado." }
    if ($db.StorageEncrypted -ne $true -or $db.StorageType -ne "gp3" -or $db.AllocatedStorage -lt 20 -or $db.DBInstanceClass -notmatch '^db\.') { $failures += "Classe/storage/encryption invalidos para o LAB." }
    if (-not $secretConfigured -or $db.MasterUserSecret.SecretArn -ne $expectedSecretArn -or $db.MasterUserSecret.SecretStatus -ne "active") { $failures += "Master secret ausente, inativo ou diferente do output Terraform." }

    if ($failures.Count -gt 0) { throw ($failures -join " ") }
    # Read secret metadata only: never GetSecretValue or a secret-version value.
    $actualSecretArn = Invoke-ReadNative -FileName "aws" -Arguments @("secretsmanager", "describe-secret", "--secret-id", $expectedSecretArn, "--region", $region, "--query", "ARN", "--output", "text", "--no-cli-pager")
    if ($actualSecretArn -ne $expectedSecretArn) { throw "Master secret nao confirmado no Secrets Manager." }
    Write-Host "Resultado: PASS (metadados; conexao SQL sera validada em ECS)."
}
catch {
    Write-Host "Resultado: FAIL"
    Write-Error $_.Exception.Message -ErrorAction Continue
    exit 1
}
