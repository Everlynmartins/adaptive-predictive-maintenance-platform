param(
    [int]$UnitId = 1,
    [int]$Horizon = 30,
    [string]$Model = "fusion",
    [int]$ExpectedPredictions = 40,
    [int]$ExpectedAlerts = 3
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ComposeFile = @("docker-compose.yml", "compose.yaml") |
    ForEach-Object { Join-Path $ProjectRoot $_ } |
    Where-Object { Test-Path -LiteralPath $_ } |
    Select-Object -First 1
$ApiBaseUrl = "http://localhost:8000"
$ComposePrefix = "-f `"$ComposeFile`" --project-directory `"$ProjectRoot`""

if (-not $ComposeFile) {
    throw "arquivo Compose não encontrado na raiz do projeto: $ProjectRoot"
}

function Invoke-Native {
    param(
        [string]$FileName,
        [string]$Arguments
    )

    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $FileName
    $startInfo.Arguments = $Arguments
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) {
            throw "não foi possível iniciar $FileName"
        }
        $stdout = $process.StandardOutput.ReadToEnd()
        $stderr = $process.StandardError.ReadToEnd()
        $process.WaitForExit()
        return [PSCustomObject]@{
            ExitCode = $process.ExitCode
            Stdout = $stdout
            Stderr = $stderr
        }
    }
    finally {
        $process.Dispose()
    }
}

function Assert-NativeSuccess {
    param(
        [object]$Result,
        [string]$Command
    )

    if ($Result.ExitCode -ne 0) {
        throw "comando: $Command`nexit code: $($Result.ExitCode)`nstdout relevante: $($Result.Stdout)`nstderr relevante: $($Result.Stderr)"
    }
}

function Invoke-Compose {
    param([string]$Arguments)

    $command = "docker compose $ComposePrefix $Arguments"
    $result = Invoke-Native -FileName "docker" -Arguments "compose $ComposePrefix $Arguments"
    Assert-NativeSuccess -Result $result -Command $command
    if ($result.Stderr) {
        Write-Host "docker stderr:`n$($result.Stderr.TrimEnd())"
    }
    return $result.Stdout
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

function Invoke-DbQuery {
    param([string]$Sql)

    $quotedSql = '"' + $Sql.Replace('"', '\"') + '"'
    $arguments = "$ComposePrefix exec -T db psql -U pm_development -d predictive_maintenance -At -F `"|`" -c $quotedSql"
    $result = Invoke-Native -FileName "docker" -Arguments "compose $arguments"
    Assert-NativeSuccess -Result $result -Command "docker compose $arguments"
    if ($result.Stderr) {
        Write-Host "psql stderr:`n$($result.Stderr.TrimEnd())"
    }
    return $result.Stdout.Trim()
}

function Assert-Fields {
    param([object]$Record, [string[]]$Fields)

    foreach ($field in $Fields) {
        if (-not ($Record.PSObject.Properties.Name -contains $field)) {
            throw "campo obrigatório ausente na resposta: $field"
        }
    }
}

try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "docker não encontrado no PATH."
    }
    $dockerInfo = Invoke-Native -FileName "docker" -Arguments "info"
    Assert-NativeSuccess -Result $dockerInfo -Command "docker info"

    $composeStatus = Invoke-Compose -Arguments "ps"
    if ($composeStatus -notmatch "(?i)db" -or $composeStatus -notmatch "(?i)api" -or
        ([regex]::Matches($composeStatus, "(?i)healthy").Count -lt 2)) {
        throw "db e api não aparecem como saudáveis em docker compose ps."
    }

    $health = Invoke-ApiJson -Method GET -Uri "${ApiBaseUrl}/health"
    if ($health.status -ne "available") {
        throw "GET /health não confirmou status available."
    }

    $predictionUri = "${ApiBaseUrl}/api/v1/predictions?unit_id=${UnitId}&horizon=${Horizon}&limit=200"
    $alertUri = "${ApiBaseUrl}/api/v1/alerts?unit_id=${UnitId}&horizon=${Horizon}&limit=200"
    $allPredictions = @(Invoke-ApiJson -Method GET -Uri $predictionUri)
    $predictions = @($allPredictions | Where-Object {
        [int]$_.unit_id -eq $UnitId -and [int]$_.horizon -eq $Horizon -and
        [string]$_.model_name -eq $Model
    } | Sort-Object cycle)
    if ($predictions.Count -lt $ExpectedPredictions) {
        throw "predictions insuficientes: encontradas=$($predictions.Count) esperadas=$ExpectedPredictions"
    }
    $requiredPredictionFields = @("unit_id", "cycle", "horizon", "model_name", "risk_score", "prediction_status")
    $predictions | ForEach-Object { Assert-Fields -Record $_ -Fields $requiredPredictionFields }
    $replayCycles = @(1..$ExpectedPredictions)
    $cycles = @($predictions | Select-Object -First $ExpectedPredictions | ForEach-Object { [int]$_.cycle })
    $missingCycles = @($replayCycles | Where-Object { $_ -notin $cycles })
    if ($missingCycles.Count -gt 0) {
        throw "ciclos ausentes no replay: $($missingCycles -join ', ')"
    }
    $identityKeys = @($predictions | ForEach-Object {
        "$($_.unit_id)|$($_.cycle)|$($_.horizon)|$($_.model_name)|$($_.model_version)|$($_.telemetry_policy)|$($_.cadence)"
    })
    $duplicateKeys = @($identityKeys | Group-Object | Where-Object Count -gt 1)
    if ($duplicateKeys.Count -gt 0) {
        throw "duplicações inesperadas detectadas: $($duplicateKeys.Name -join ', ')"
    }

    $alerts = @(
        Invoke-ApiJson -Method GET -Uri $alertUri |
            Where-Object { [int]$_.unit_id -eq $UnitId -and [int]$_.horizon -eq $Horizon -and [int]$_.cycle -in $replayCycles } |
            Sort-Object cycle
    )
    if ($alerts.Count -lt $ExpectedAlerts) {
        throw "alerts insuficientes no intervalo do replay: encontradas=$($alerts.Count) esperadas=$ExpectedAlerts"
    }

    $dbPredictionCount = [int](Invoke-DbQuery -Sql "SELECT COUNT(*) FROM predictions WHERE unit_id=$UnitId AND cycle BETWEEN 1 AND $ExpectedPredictions AND horizon=$Horizon AND model_name='$Model';")
    $dbAlertCount = [int](Invoke-DbQuery -Sql "SELECT COUNT(*) FROM alerts WHERE unit_id=$UnitId AND cycle BETWEEN 1 AND $ExpectedPredictions AND horizon=$Horizon;")
    if ($dbPredictionCount -lt $ExpectedPredictions) {
        throw "predictions insuficientes no PostgreSQL: $dbPredictionCount"
    }
    if ($dbAlertCount -lt $ExpectedAlerts) {
        throw "alerts insuficientes no PostgreSQL: $dbAlertCount"
    }

    $sampleText = Invoke-DbQuery -Sql "SELECT unit_id,cycle,horizon,model_name,risk_score,prediction_status FROM predictions WHERE unit_id=$UnitId AND cycle IN (1,40) AND horizon=$Horizon AND model_name='$Model' ORDER BY cycle;"
    $dbSample = @($sampleText -split "`r?`n" | Where-Object { $_ } | ForEach-Object {
        $parts = $_ -split "\|", 6
        [PSCustomObject]@{
            unit_id = [int]$parts[0]; cycle = [int]$parts[1]; horizon = [int]$parts[2]
            model_name = $parts[3]; risk_score = [double]$parts[4]; prediction_status = $parts[5]
        }
    })
    foreach ($dbRow in $dbSample) {
        $apiRow = $predictions | Where-Object { [int]$_.cycle -eq $dbRow.cycle } | Select-Object -First 1
        if (-not $apiRow -or [int]$apiRow.unit_id -ne $dbRow.unit_id -or
            [string]$apiRow.model_name -ne $dbRow.model_name -or
            [string]$apiRow.prediction_status -ne $dbRow.prediction_status -or
            [Math]::Abs([double]$apiRow.risk_score - $dbRow.risk_score) -gt 1e-9) {
            throw "amostra API/PostgreSQL divergente no cycle=$($dbRow.cycle)"
        }
    }

    Invoke-Compose -Arguments "restart api dashboard" | Out-Null
    $restartHealthy = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 2
        try {
            $afterRestartHealth = Invoke-ApiJson -Method GET -Uri "${ApiBaseUrl}/health"
            if ($afterRestartHealth.status -eq "available") {
                $restartHealthy = $true
                break
            }
        }
        catch {
            # A transient connection error is expected while Uvicorn restarts.
        }
    }
    if (-not $restartHealthy) {
        throw "API não voltou a ficar saudável após restart."
    }
    $afterRestart = @(Invoke-ApiJson -Method GET -Uri $predictionUri | Where-Object {
        [int]$_.unit_id -eq $UnitId -and [int]$_.horizon -eq $Horizon -and [string]$_.model_name -eq $Model
    })
    if ($afterRestart.Count -lt $ExpectedPredictions) {
        throw "predictions não sobreviveram ao restart: $($afterRestart.Count)"
    }

    Write-Host "predictions API: $($predictions.Count)"
    Write-Host "predictions DB: $dbPredictionCount"
    Write-Host "alerts API: $($alerts.Count)"
    Write-Host "alerts DB: $dbAlertCount"
    Write-Host "cycles verificados: 1-$ExpectedPredictions"
    Write-Host "persistência após restart: PASS"
    Write-Host "duplicações inesperadas: 0"
    Write-Host "resultado: PASS"
    exit 0
}
catch {
    Write-Error $_.Exception.Message
    Write-Host "resultado: FAIL"
    exit 1
}
