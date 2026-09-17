param(
    [Parameter(Mandatory)]
    [ValidatePattern("^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")]
    [string]$ExpectedTag
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$TerraformRoot = Join-Path $ProjectRoot "infra\aws"

function Require-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name não encontrado no PATH."
    }
}

function Get-AwsRegion {
    $region = $env:AWS_REGION
    if ([string]::IsNullOrWhiteSpace($region)) { $region = $env:AWS_DEFAULT_REGION }
    if ([string]::IsNullOrWhiteSpace($region)) {
        $region = (& aws configure get region).Trim()
        if ($LASTEXITCODE -ne 0) { throw "Não foi possível obter a região do perfil AWS." }
    }
    if ([string]::IsNullOrWhiteSpace($region)) { throw "Defina uma região AWS." }
    return $region
}

function Get-TerraformOutput {
    param([string]$Name)
    $value = & terraform "-chdir=$TerraformRoot" output -raw $Name
    if ($LASTEXITCODE -ne 0) { throw "Não foi possível ler o output Terraform '$Name'." }
    return ($value | Out-String).Trim()
}

try {
    Require-Command aws
    Require-Command docker
    Require-Command terraform

    $identity = & aws sts get-caller-identity --output json | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw "aws sts get-caller-identity falhou." }
    $region = Get-AwsRegion
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) { throw "Docker Engine não está disponível." }

    $repositoryName = Get-TerraformOutput -Name "ecr_repository_name"
    $repositoryUri = (& aws ecr describe-repositories --repository-names $repositoryName --region $region --query "repositories[0].repositoryUri" --output text).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($repositoryUri) -or $repositoryUri -eq "None") {
        throw "Repositório ECR '$repositoryName' não foi encontrado na região $region."
    }

    Write-Host "Repositório encontrado: $repositoryUri"
    # Keep the native password pipe outside Windows PowerShell, as in the push
    # script. No token is returned to PowerShell, printed or written to a file.
    $registry = $repositoryUri.Split("/")[0]
    $loginCommand = "aws ecr get-login-password --region `"$region`""
    if (-not [string]::IsNullOrWhiteSpace($env:AWS_PROFILE)) {
        $loginCommand += " --profile `"$($env:AWS_PROFILE)`""
    }
    $loginCommand += " | docker login --username AWS --password-stdin `"$registry`""
    $savedPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & cmd.exe /d /s /c $loginCommand
        $loginExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $savedPreference
    }
    if ($loginExitCode -ne 0) { throw "docker login no ECR falhou (exit code $loginExitCode)." }

    $digest = (& aws ecr describe-images --repository-name $repositoryName --image-ids "imageTag=$ExpectedTag" --region $region --query "imageDetails[0].imageDigest" --output text).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($digest) -or $digest -eq "None") {
        throw "A tag esperada '$ExpectedTag' não está publicada no ECR."
    }
    Write-Host "Conta AWS: $($identity.Account); região: $region"
    Write-Host "Tag confirmada: $ExpectedTag"
    Write-Host "Digest: $digest"
}
catch {
    Write-Error $_.Exception.Message
    exit 1
}
