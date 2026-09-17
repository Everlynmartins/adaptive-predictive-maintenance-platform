$ErrorActionPreference = "Stop"

function Require-Command {
    param([string]$Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name não encontrado no PATH."
    }
}

function Invoke-CheckedNative {
    param(
        [string]$FileName,
        [string[]]$Arguments
    )

    & $FileName @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FileName falhou com exit code $LASTEXITCODE."
    }
}

try {
    Require-Command aws
    Require-Command terraform

    Write-Host "AWS CLI:"
    Invoke-CheckedNative -FileName "aws" -Arguments @("--version")

    Write-Host "Terraform:"
    Invoke-CheckedNative -FileName "terraform" -Arguments @("version")

    Write-Host "AWS caller identity:"
    Invoke-CheckedNative -FileName "aws" -Arguments @("sts", "get-caller-identity", "--output", "json")

    $configuredRegion = $env:AWS_REGION
    if ([string]::IsNullOrWhiteSpace($configuredRegion)) {
        $configuredRegion = $env:AWS_DEFAULT_REGION
    }
    if ([string]::IsNullOrWhiteSpace($configuredRegion)) {
        $configuredRegion = (& aws configure get region | Out-String).Trim()
        if ($LASTEXITCODE -ne 0) {
            throw "aws configure get region falhou com exit code $LASTEXITCODE."
        }
    }
    if ([string]::IsNullOrWhiteSpace($configuredRegion)) {
        Write-Host "Região configurada: não definida"
        Write-Host "Defina aws_region em infra/aws/terraform.tfvars ou TF_VAR_aws_region antes do plan."
    }
    else {
        Write-Host "Região configurada: $configuredRegion"
    }
}
catch {
    Write-Error $_.Exception.Message
    exit 1
}
