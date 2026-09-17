param(
    [int]$PreferredUnitId = 1,
    [int]$RequestedCycles = 40
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ComposeFile = @("docker-compose.yml", "compose.yaml") |
    ForEach-Object { Join-Path $ProjectRoot $_ } |
    Where-Object { Test-Path -LiteralPath $_ } |
    Select-Object -First 1
$ApiBaseUrl = "http://localhost:8000"

if (-not $ComposeFile) {
    throw "arquivo Compose não encontrado na raiz do projeto: $ProjectRoot"
}

function Assert-CommandAvailable {
    param([string]$Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name não encontrado no PATH."
    }
}

function Get-PreferredValue {
    param(
        [object[]]$Available,
        [object]$Preferred,
        [string]$Name
    )

    if (-not $Available -or $Available.Count -eq 0) {
        throw "A API não retornou opções para $Name."
    }
    if ($Available -contains $Preferred) {
        return $Preferred
    }
    Write-Host "$Name preferido indisponível; usando $($Available[0])."
    return $Available[0]
}

function Invoke-Compose {
    param([string[]]$Arguments)

    & docker compose -f $ComposeFile --project-directory $ProjectRoot @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose falhou: $($Arguments -join ' ')"
    }
}

function Invoke-ApiJson {
    param(
        [ValidateSet("GET", "POST")]
        [string]$Method,
        [string]$Uri
    )

    try {
        $response = Invoke-WebRequest -Method $Method -Uri $Uri -UseBasicParsing
        if ($response.StatusCode -ne 200) {
            throw "unexpected status"
        }
        return ($response.Content | ConvertFrom-Json)
    }
    catch {
        $errorResponse = $_.Exception.Response
        $status = "unknown"
        $body = $_.Exception.Message
        if ($errorResponse) {
            $status = [int]$errorResponse.StatusCode
            try {
                $reader = New-Object System.IO.StreamReader($errorResponse.GetResponseStream())
                $body = $reader.ReadToEnd()
                $reader.Dispose()
            }
            catch {
                $body = $_.Exception.Message
            }
        }
        throw "$Method $Uri | HTTP $status | response body: $body"
    }
}

try {
    Assert-CommandAvailable docker
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Engine não respondeu."
    }

    Push-Location $ProjectRoot
    try {
        Invoke-Compose @("ps")

        $health = Invoke-ApiJson -Method GET -Uri "${ApiBaseUrl}/health"

        $options = Invoke-ApiJson -Method GET -Uri "${ApiBaseUrl}/api/v1/options"
        $unitId = [int](Get-PreferredValue $options.unit_ids $PreferredUnitId "unit_id")
        $horizon = [int](Get-PreferredValue $options.horizons 30 "horizon")
        $model = [string](Get-PreferredValue $options.models "fusion" "model")
        $policy = [string](Get-PreferredValue $options.telemetry_policies "full" "telemetry_policy")
        $cadence = [string](Get-PreferredValue $options.cadences "each_cycle" "cadence")

        $python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
        if (-not (Test-Path -LiteralPath $python)) {
            $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
            if (-not $pythonCommand) {
                throw "Python não encontrado; crie .venv ou disponibilize python no PATH."
            }
            $python = $pythonCommand.Source
        }

        $unitMetadataUri = "${ApiBaseUrl}/api/v1/units/${unitId}?horizon=${horizon}&model=${model}" +
            "&telemetry_policy=${policy}&cadence=${cadence}"
        $unitMetadata = Invoke-ApiJson -Method GET -Uri $unitMetadataUri
        $expectedCycles = [Math]::Min($RequestedCycles, [int]$unitMetadata.last_cycle)
        if ($expectedCycles -le 0) {
            throw "A unidade $unitId não possui ciclos disponíveis."
        }

        Write-Host "Replay: unit_id=$unitId cycles=$expectedCycles horizon=$horizon model=$model policy=$policy cadence=$cadence"
        $simulatorArguments = "-m predictive_maintenance.simulator.telemetry_producer --api-base-url `"$ApiBaseUrl`" --unit-id $unitId --horizon $horizon --model $model --telemetry-policy $policy --cadence $cadence --mode fast --max-cycles $expectedCycles"
        $simulatorCommand = "`"$python`" $simulatorArguments"
        $processInfo = New-Object System.Diagnostics.ProcessStartInfo
        $processInfo.FileName = $python
        $processInfo.Arguments = $simulatorArguments
        $processInfo.UseShellExecute = $false
        $processInfo.CreateNoWindow = $true
        $processInfo.RedirectStandardOutput = $true
        $processInfo.RedirectStandardError = $true
        $process = New-Object System.Diagnostics.Process
        $process.StartInfo = $processInfo
        try {
            if (-not $process.Start()) {
                throw "não foi possível iniciar o simulador"
            }
            $simulatorStdout = $process.StandardOutput.ReadToEnd()
            $simulatorStderr = $process.StandardError.ReadToEnd()
            $process.WaitForExit()
            $simulatorExitCode = $process.ExitCode
        }
        finally {
            $process.Dispose()
        }
        if ($simulatorStdout) { Write-Host $simulatorStdout.TrimEnd() }
        if ($simulatorStderr) { Write-Host "simulador stderr:`n$($simulatorStderr.TrimEnd())" }
        if ($simulatorExitCode -ne 0) {
            throw "comando: $simulatorCommand`nexit code: $simulatorExitCode`nstdout relevante: $simulatorStdout`nstderr relevante: $simulatorStderr"
        }
        $cyclesSent = @($simulatorStdout -split "`r?`n" | Where-Object { "$_" -match "^cycle=" }).Count
        if ($cyclesSent -ne $expectedCycles) {
            throw "Replay incompleto: enviados=$cyclesSent esperados=$expectedCycles."
        }

        $predictionsUri = "${ApiBaseUrl}/api/v1/predictions?unit_id=${unitId}&horizon=${horizon}&limit=200"
        $alertsUri = "${ApiBaseUrl}/api/v1/alerts?unit_id=${unitId}&horizon=${horizon}&limit=200"
        $predictions = @(Invoke-ApiJson -Method GET -Uri $predictionsUri)
        $alerts = @(Invoke-ApiJson -Method GET -Uri $alertsUri)
        if ($predictions.Count -eq 0) {
            throw "Nenhuma previsão persistida foi encontrada."
        }

        Write-Host "unit_id: $unitId"
        Write-Host "cycles enviados: $cyclesSent"
        Write-Host "health status: $($health.status)"
        Write-Host "predictions encontradas: $($predictions.Count)"
        Write-Host "alerts encontradas: $($alerts.Count)"
        Write-Host "resultado: PASS"
        exit 0
    }
    finally {
        Pop-Location
    }
}
catch {
    Write-Error $_.Exception.Message
    Write-Host "resultado: FAIL"
    exit 1
}
