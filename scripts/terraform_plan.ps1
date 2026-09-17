$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$TerraformRoot = Join-Path $ProjectRoot "infra\aws"
$TfvarsFile = Join-Path $TerraformRoot "terraform.tfvars"

function Require-Command {
    param([string]$Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name não encontrado no PATH."
    }
}

function Invoke-Terraform {
    param([string[]]$Arguments)

    & terraform @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "terraform $($Arguments -join ' ') falhou com exit code $LASTEXITCODE."
    }
}

try {
    Require-Command terraform
    if (-not (Test-Path -LiteralPath $TerraformRoot)) {
        throw "Diretório Terraform não encontrado: $TerraformRoot"
    }
    if (-not (Test-Path -LiteralPath $TfvarsFile) -and [string]::IsNullOrWhiteSpace($env:TF_VAR_aws_region)) {
        throw "Defina TF_VAR_aws_region ou crie infra/aws/terraform.tfvars a partir do exemplo antes do plan."
    }
    if (Test-Path -LiteralPath $TfvarsFile) {
        $tfvarsContent = Get-Content -Raw -LiteralPath $TfvarsFile
        if ($tfvarsContent -match 'aws_region\s*=\s*"replace-with-your-aws-region"') {
            throw "Substitua o placeholder aws_region em infra/aws/terraform.tfvars antes do plan."
        }
    }

    Push-Location $TerraformRoot
    try {
        Invoke-Terraform -Arguments @("init", "-input=false")
        Invoke-Terraform -Arguments @("fmt", "-recursive")
        Invoke-Terraform -Arguments @("validate")
        Invoke-Terraform -Arguments @("plan", "-input=false", "-lock-timeout=0s")
    }
    finally {
        Pop-Location
    }
}
catch {
    Write-Error $_.Exception.Message
    exit 1
}
