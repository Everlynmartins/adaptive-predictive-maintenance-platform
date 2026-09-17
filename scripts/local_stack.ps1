param(
    [Parameter(Position = 0)]
    [ValidateSet("start", "stop", "restart", "status", "logs", "rebuild")]
    [string]$Command = "status"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ComposeFile = @("docker-compose.yml", "compose.yaml") |
    ForEach-Object { Join-Path $ProjectRoot $_ } |
    Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
    Select-Object -First 1
if (-not $ComposeFile) {
    throw "arquivo Compose não encontrado na raiz do projeto: $ProjectRoot"
}

function Assert-DockerAvailable {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "docker não encontrado no PATH."
    }
}

function Ensure-DockerEngine {
    & docker info *> $null
    if ($LASTEXITCODE -eq 0) {
        return
    }

    Write-Host "Docker Desktop não está pronto; iniciando..."
    & docker desktop start --timeout 60
    if ($LASTEXITCODE -ne 0) {
        throw "não foi possível iniciar o Docker Desktop."
    }

    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        & docker info *> $null
        if ($LASTEXITCODE -eq 0) {
            return
        }
        Start-Sleep -Seconds 2
    }
    throw "Docker Engine não respondeu no tempo esperado."
}

function Invoke-Compose {
    param([string[]]$Arguments)

    & docker compose -f $ComposeFile --project-directory $ProjectRoot @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose falhou: $($Arguments -join ' ')"
    }
}

function Start-Stack {
    Ensure-DockerEngine
    Invoke-Compose @("up", "-d")
    Invoke-Compose @("ps")
    Write-Host "Dashboard: http://localhost:8501"
    Write-Host "API: http://localhost:8000/docs"
}

function Stop-Stack {
    Ensure-DockerEngine
    Invoke-Compose @("down")
}

function Show-StackStatus {
    Ensure-DockerEngine
    Invoke-Compose @("ps")
}

function Show-StackLogs {
    Ensure-DockerEngine
    try {
        & docker compose -f $ComposeFile --project-directory $ProjectRoot logs -f
        if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne 130) {
            throw "docker compose logs falhou."
        }
    }
    catch [System.Management.Automation.PipelineStoppedException] {
        Write-Host "Logs interrompidos; containers permanecem ativos."
    }
}

function Rebuild-Stack {
    Ensure-DockerEngine
    Invoke-Compose @("up", "--build", "-d")
    Invoke-Compose @("ps")
}

try {
    Assert-DockerAvailable
    Push-Location $ProjectRoot
    try {
        switch ($Command) {
            "start"   { Start-Stack }
            "stop"    { Stop-Stack }
            "restart" { Stop-Stack; Start-Stack }
            "status"  { Show-StackStatus }
            "logs"    { Show-StackLogs }
            "rebuild" { Rebuild-Stack }
        }
    }
    finally {
        Pop-Location
    }
}
catch {
    Write-Error $_.Exception.Message
    exit 1
}
