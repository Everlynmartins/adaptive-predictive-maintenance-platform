param(
    [Parameter(Mandatory)]
    [ValidatePattern("^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")]
    [string]$VersionTag
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
    if ([string]::IsNullOrWhiteSpace($region)) {
        throw "Defina AWS_REGION, AWS_DEFAULT_REGION ou uma região no perfil AWS."
    }
    return $region
}

function Get-TerraformOutput {
    param([string]$Name)

    $value = & terraform "-chdir=$TerraformRoot" output -raw $Name
    if ($LASTEXITCODE -ne 0) {
        throw "Não foi possível ler o output Terraform '$Name'. Execute apply aprovado antes do push."
    }
    return ($value | Out-String).Trim()
}

try {
    Require-Command aws
    Require-Command docker
    Require-Command terraform

    $identity = & aws sts get-caller-identity --output json | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw "aws sts get-caller-identity falhou." }
    $region = Get-AwsRegion
    $profileDisplay = if ($env:AWS_PROFILE) { $env:AWS_PROFILE } else { "perfil padrão" }

    & docker info *> $null
    if ($LASTEXITCODE -ne 0) { throw "Docker Engine não está disponível." }

    $repositoryName = Get-TerraformOutput -Name "ecr_repository_name"
    $repositoryUri = (& aws ecr describe-repositories --repository-names $repositoryName --region $region --query "repositories[0].repositoryUri" --output text).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($repositoryUri) -or $repositoryUri -eq "None") {
        throw "Repositório ECR '$repositoryName' não foi encontrado na região $region."
    }
    $registry = $repositoryUri.Split("/")[0]

    Write-Host "Conta AWS: $($identity.Account); perfil: $profileDisplay; região: $region"
    Write-Host "Autenticando Docker no ECR..."
    # Windows PowerShell can corrupt the native stdout pipe between AWS CLI and
    # Docker. Let cmd.exe own the native pipeline; the password is never printed
    # or written to a file and is consumed directly by --password-stdin.
    $loginCommand = "aws ecr get-login-password --region `"$region`""
    if (-not [string]::IsNullOrWhiteSpace($env:AWS_PROFILE)) {
        $loginCommand += " --profile `"$($env:AWS_PROFILE)`""
    }
    $loginCommand += " | docker login --username AWS --password-stdin `"$registry`""
    & cmd.exe /d /s /c $loginCommand
    if ($LASTEXITCODE -ne 0) { throw "docker login no ECR falhou." }

    $localImage = "adaptive-predictive-maintenance:$VersionTag"
    $versionedImage = "${repositoryUri}:${VersionTag}"
    $latestImage = "${repositoryUri}:latest"

    Write-Host "Construindo imagem Linux x86_64..."
    & docker build --platform linux/amd64 --tag $localImage $ProjectRoot
    if ($LASTEXITCODE -ne 0) { throw "docker build falhou." }

    foreach ($targetImage in @($versionedImage, $latestImage)) {
        & docker tag $localImage $targetImage
        if ($LASTEXITCODE -ne 0) { throw "docker tag falhou para $targetImage." }
        & docker push $targetImage
        if ($LASTEXITCODE -ne 0) { throw "docker push falhou para $targetImage." }
    }

    $digest = (& aws ecr describe-images --repository-name $repositoryName --image-ids "imageTag=$VersionTag" --region $region --query "imageDetails[0].imageDigest" --output text).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($digest) -or $digest -eq "None") {
        throw "A imagem enviada não pôde ser confirmada pelo ECR."
    }
    Write-Host "Publicada: $versionedImage"
    Write-Host "Digest: $digest"
}
catch {
    Write-Error $_.Exception.Message
    exit 1
}
