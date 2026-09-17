# Shared read-only helpers. Loading this file does not call AWS or Terraform.
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$TerraformRoot = Join-Path $ProjectRoot "infra\aws"

function Require-Tool {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) { throw "$Name nao encontrado no PATH." }
}

function Invoke-LabNative {
    param([string]$FileName, [string[]]$Arguments, [int[]]$AllowedExitCodes = @(0))
    $savedPreference = $ErrorActionPreference
    try {
        # Display stderr without treating a warning as a failed process.
        $ErrorActionPreference = "Continue"
        $output = & $FileName @Arguments
        $code = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $savedPreference }
    if ($code -notin $AllowedExitCodes) { throw "$FileName $($Arguments -join ' ') falhou (exit code $code)." }
    return ($output | Out-String).Trim()
}

function Get-LabOutput {
    param([string]$Name)
    return Invoke-LabNative terraform @("-chdir=$TerraformRoot", "output", "-raw", $Name)
}

function Initialize-LabRead {
    Require-Tool aws
    Require-Tool terraform
    $script:LabRegion = $env:AWS_REGION
    if ([string]::IsNullOrWhiteSpace($script:LabRegion)) { $script:LabRegion = $env:AWS_DEFAULT_REGION }
    if ([string]::IsNullOrWhiteSpace($script:LabRegion)) {
        $script:LabRegion = Invoke-LabNative aws @("configure", "get", "region")
    }
    if ([string]::IsNullOrWhiteSpace($script:LabRegion)) { throw "Defina AWS_REGION ou a regiao do perfil AWS." }
    # AWS_PROFILE is inherited by AWS CLI, with no embedded credentials.
    $script:LabCluster = Get-LabOutput "ecs_cluster_name"
    $script:LabService = Get-LabOutput "ecs_service_name"
}

function Invoke-LabAws {
    param([string[]]$Arguments)
    $json = Invoke-LabNative aws ($Arguments + @("--region", $script:LabRegion, "--output", "json", "--no-cli-pager"))
    return $json | ConvertFrom-Json
}

function Get-LabService {
    $response = Invoke-LabAws @("ecs", "describe-services", "--cluster", $script:LabCluster, "--services", $script:LabService)
    if (@($response.failures).Count -gt 0 -or @($response.services).Count -ne 1) { throw "Service ECS nao encontrado." }
    return $response.services[0]
}

function Get-LabRunningTasks {
    $listing = Invoke-LabAws @("ecs", "list-tasks", "--cluster", $script:LabCluster, "--service-name", $script:LabService, "--desired-status", "RUNNING")
    if (@($listing.taskArns).Count -eq 0) { return }
    $response = Invoke-LabAws (@("ecs", "describe-tasks", "--cluster", $script:LabCluster, "--tasks") + @($listing.taskArns))
    if (@($response.failures).Count -gt 0) { throw "Falha ao consultar tasks ECS." }
    return $response.tasks
}

function Get-LabPublicIp {
    param($Task)
    $eniIds = @($Task.attachments | Where-Object { $_.type -eq "ElasticNetworkInterface" } |
        ForEach-Object { $_.details } | Where-Object { $_.name -eq "networkInterfaceId" } |
        ForEach-Object { $_.value })
    if ($eniIds.Count -ne 1) { throw "ENI da task nao encontrada de forma unica." }
    $response = Invoke-LabAws @("ec2", "describe-network-interfaces", "--network-interface-ids", $eniIds[0])
    return $response.NetworkInterfaces[0].Association.PublicIp
}
