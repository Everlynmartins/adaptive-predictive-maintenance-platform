param(
    [ValidateRange(1, 2147483647)][int]$UnitId = 1,
    [ValidateSet(15, 30)][int]$Horizon = 30,
    [ValidatePattern('^[A-Za-z0-9_-]+$')][string]$Model = "fusion",
    [ValidatePattern('^[A-Za-z0-9_-]+$')][string]$TelemetryPolicy = "full",
    [ValidatePattern('^[A-Za-z0-9_-]+$')][string]$Cadence = "each_cycle",
    [ValidateRange(1, 100)][int]$Cycles = 40
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "aws_ecs_common.ps1")

function Invoke-CloudGet {
    param([string]$Endpoint, [int]$TimeoutSeconds = 180)
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Method GET -Uri $Endpoint -TimeoutSec $TimeoutSeconds -ErrorAction Stop
        if ([int]$response.StatusCode -ne 200) { throw "Expected HTTP 200, received $($response.StatusCode)." }
        # Assignment then return enumerates JSON collections correctly in PS 5.1.
        $payload = $response.Content | ConvertFrom-Json
        return $payload
    }
    catch {
        $status = "NO RESPONSE"
        $body = $_.ErrorDetails.Message
        if ($_.Exception.Response) {
            $status = [int]$_.Exception.Response.StatusCode
            if ([string]::IsNullOrWhiteSpace($body)) {
                try {
                    $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
                    try { $body = $reader.ReadToEnd() } finally { $reader.Dispose() }
                } catch { $body = "Response body could not be read." }
            }
        }
        if ([string]::IsNullOrWhiteSpace($body)) { $body = $_.Exception.Message }
        throw "GET ${Endpoint}; HTTP ${status}; response body: ${body}"
    }
}

function Invoke-ExistingSimulator {
    param([string]$BaseUrl, [int]$FirstCycle)
    $executable = Join-Path $ProjectRoot ".venv\Scripts\predictive-maintenance-simulator.exe"
    $arguments = @()
    if (-not (Test-Path -LiteralPath $executable)) {
        $executable = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
        $arguments = @("-m", "predictive_maintenance.simulator.telemetry_producer")
    }
    if (-not (Test-Path -LiteralPath $executable)) { throw "Project .venv simulator/Python missing. Prepare the existing project environment first." }
    # All argument atoms are validated selections, numbers, or an ECS IPv4 URL;
    # no shell, credentials, scientific backend, or local API fallback is used.
    $arguments += @("--api-base-url", $BaseUrl, "--unit-id", [string]$UnitId,
        "--horizon", [string]$Horizon, "--model", $Model, "--telemetry-policy", $TelemetryPolicy,
        "--cadence", $Cadence, "--mode", "fast", "--interval", "0",
        "--start-cycle", [string]$FirstCycle, "--max-cycles", [string]$Cycles)
    Write-Host "Simulator: `"${executable}`" $($arguments -join ' ')"
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $executable
    $info.Arguments = $arguments -join ' '
    $info.WorkingDirectory = $ProjectRoot
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $info.StandardErrorEncoding = [System.Text.Encoding]::UTF8
    $info.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8"
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $info
    try {
        $null = $process.Start()
        # Drain both pipes asynchronously to avoid deadlock on native stderr.
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $finished = $process.WaitForExit(600000)
        if (-not $finished) { $process.Kill(); $process.WaitForExit() }
        $stdout = $stdoutTask.GetAwaiter().GetResult()
        $stderr = $stderrTask.GetAwaiter().GetResult()
        if ($stdout) { Write-Host $stdout.TrimEnd() }
        if ($stderr) { Write-Host "Simulator stderr: $($stderr.TrimEnd())" }
        if (-not $finished) { throw "Simulator timed out after 600 seconds; command shown above." }
        if ($process.ExitCode -ne 0) { throw "Simulator failed; command shown above; exit code $($process.ExitCode); stdout/stderr shown above." }
        return $stdout
    }
    finally { $process.Dispose() }
}

$cloudApi = "not discovered"
$ecsStatus = "not checked"
$healthStatus = "not checked"
$persistenceStatus = "NOT CONFIRMED"
$cyclesSent = 0
$matchedPredictions = @()
$matchedAlerts = @()
$statuses = "none"
$passed = $false
try {
    Initialize-LabRead
    $service = Get-LabService
    if ($service.status -ne "ACTIVE" -or $service.launchType -ne "FARGATE" -or $service.desiredCount -ne 1) { throw "Expected an active Fargate service with desired count 1. This test does not start it." }
    $tasks = @(Get-LabRunningTasks)
    if ($tasks.Count -ne 1 -or $tasks[0].lastStatus -ne "RUNNING") { throw "Expected exactly one RUNNING task." }
    $task = $tasks[0]
    if ($task.taskDefinitionArn -ne (Get-LabOutput "ecs_task_definition_arn")) { throw "Running task differs from the Terraform task definition output." }
    foreach ($name in @("api", "dashboard")) {
        $container = @($task.containers | Where-Object { $_.name -eq $name })
        if ($container.Count -ne 1 -or $container[0].lastStatus -ne "RUNNING" -or $container[0].healthStatus -ne "HEALTHY") { throw "Container ${name} must be RUNNING / HEALTHY." }
    }
    $ecsStatus = "RUNNING; api HEALTHY; dashboard HEALTHY"
    # Check configuration provenance without reading any secret value or SQL.
    $definition = (Invoke-LabAws @("ecs", "describe-task-definition", "--task-definition", $task.taskDefinitionArn)).taskDefinition
    $apiDefinition = @($definition.containerDefinitions | Where-Object { $_.name -eq "api" })
    if ($apiDefinition.Count -ne 1) { throw "API definition missing." }
    if (@($apiDefinition[0].environment | Where-Object { $_.name -in @("DATABASE_URL", "DB_PASSWORD") }).Count) { throw "Expected RDS bootstrap/secret injection, not a plaintext connection override." }
    foreach ($pair in @(@("DB_HOST", "rds_endpoint"), @("DB_PORT", "rds_port"), @("DB_NAME", "rds_database_name"))) {
        $expected = Get-LabOutput $pair[1]
        $configured = @($apiDefinition[0].environment | Where-Object { $_.name -eq $pair[0] })
        if ($configured.Count -ne 1 -or $configured[0].value -ne $expected) { throw "API $($pair[0]) does not match the Terraform RDS output." }
    }
    $secretArn = Get-LabOutput "rds_master_secret_arn"
    foreach ($pair in @(@("DB_USERNAME", "username"), @("DB_PASSWORD", "password"))) {
        $reference = @($apiDefinition[0].secrets | Where-Object { $_.name -eq $pair[0] })
        if ($reference.Count -ne 1 -or $reference[0].valueFrom -ne "${secretArn}:$($pair[1])::") { throw "RDS secret reference missing or inconsistent." }
    }
    $publicIp = Get-LabPublicIp $task
    $address = $null
    if (-not [System.Net.IPAddress]::TryParse($publicIp, [ref]$address) -or
        $address.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork -or
        [System.Net.IPAddress]::IsLoopback($address) -or $publicIp -eq "0.0.0.0") { throw "A non-loopback ECS public IPv4 is required. No localhost fallback." }
    $cloudApi = "http://${publicIp}:8000"
    Write-Host "Cloud API: $cloudApi"
    $health = Invoke-CloudGet "${cloudApi}/health"
    if ($health.status -ne "available") { throw "HTTP 200 but API health is not available." }
    $healthStatus = "HTTP 200 / available"
    $options = Invoke-CloudGet "${cloudApi}/api/v1/options"
    foreach ($pair in @(@("unit_ids", $UnitId), @("horizons", $Horizon), @("models", $Model),
                        @("telemetry_policies", $TelemetryPolicy), @("cadences", $Cadence))) {
        if ($pair[1] -notin @($options.PSObject.Properties[$pair[0]].Value)) { throw "Unsupported selection $($pair[0])=$($pair[1]); choose an option actually returned by the cloud API." }
    }
    $scenarioQuery = "horizon=${Horizon}&model=${Model}&telemetry_policy=${TelemetryPolicy}&cadence=${Cadence}"
    $unit = Invoke-CloudGet "${cloudApi}/api/v1/units/${UnitId}?${scenarioQuery}"
    $first = [int]$unit.first_cycle
    if ($unit.unit_id -ne $UnitId -or $first -lt 1 -or ([int]$unit.last_cycle - $first + 1) -lt $Cycles) { throw "Unit does not have the requested cycle interval." }
    $historyQuery = "unit_id=${UnitId}&horizon=${Horizon}&limit=200"
    $before = @(Invoke-CloudGet "${cloudApi}/api/v1/predictions?${historyQuery}")
    $stdout = Invoke-ExistingSimulator -BaseUrl $cloudApi -FirstCycle $first
    $observations = @($stdout -split '\r?\n' | ForEach-Object {
        if ($_ -match '^cycle=(?<cycle>\d+)\s+risk_score=(?<risk>\S+)\s+alert_level=(?<alert>.*?)\s+prediction_status=(?<status>\S+)\s*$') {
            [PSCustomObject]@{ cycle = [int]$Matches.cycle; risk = $Matches.risk; alert = $Matches.alert; status = $Matches.status }
        }
    })
    $cyclesSent = $observations.Count
    if ($cyclesSent -ne $Cycles) { throw "Expected ${Cycles} acknowledged cycles; found ${cyclesSent}." }
    for ($i = 0; $i -lt $Cycles; $i++) {
        if ($observations[$i].cycle -ne $first + $i) { throw "Simulator cycles are not strictly sequential." }
    }
    $statuses = ($observations | Group-Object status | ForEach-Object { "$($_.Name)=$($_.Count)" }) -join ", "
    $last = $first + $Cycles - 1
    # Retry only incomplete history. HTTP/configuration/contract errors still fail
    # explicitly. At most three reads, two 500 ms waits; each HTTP read is <= 5 s.
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        $predictions = @(Invoke-CloudGet "${cloudApi}/api/v1/predictions?${historyQuery}" -TimeoutSeconds 5)
        $alerts = @(Invoke-CloudGet "${cloudApi}/api/v1/alerts?${historyQuery}" -TimeoutSeconds 5)
        $pending = @()
        $matchedAlerts = @()
        # Model/policy/cadence are NOT server-side filters in the historical contract.
        $matchedPredictions = @($predictions | Where-Object { $_.unit_id -eq $UnitId -and $_.horizon -eq $Horizon -and
            $_.model_name -eq $Model -and $_.telemetry_policy -eq $TelemetryPolicy -and $_.cadence -eq $Cadence -and
            $_.cycle -ge $first -and $_.cycle -le $last })
        $duplicates = @($matchedPredictions | Group-Object unit_id, cycle, horizon, model_name, model_version, telemetry_policy, cadence | Where-Object { $_.Count -gt 1 })
        if ($duplicates.Count) { throw "Unexpected duplicate prediction identities in cloud history." }
        $available = 0
        foreach ($observation in $observations) {
            $riskMissing = $observation.risk -eq "unavailable"
            $number = if ($riskMissing) { $null } else { [double]::Parse($observation.risk, [System.Globalization.CultureInfo]::InvariantCulture) }
            $candidates = @($matchedPredictions | Where-Object { $_.cycle -eq $observation.cycle -and $_.prediction_status -eq $observation.status })
            $consistent = @($candidates | Where-Object {
                if ($riskMissing) { $null -eq $_.risk_score }
                else {
                    $null -ne $_.risk_score -and [double]$_.risk_score -ge 0 -and [double]$_.risk_score -le 1 -and
                        [math]::Abs([double]$_.risk_score - $number) -le 0.000051
                }
            })
            if (-not $consistent.Count) {
                $pending += "No persisted cloud prediction matches cycle $($observation.cycle), status and displayed risk."
                continue
            }
            if (@($consistent | Where-Object { [string]::IsNullOrWhiteSpace($_.model_version) -or [string]::IsNullOrWhiteSpace($_.input_validity) -or [string]::IsNullOrWhiteSpace($_.created_at) }).Count) { throw "Incomplete persisted prediction contract." }
            if ($observation.status -in @("valid", "degraded") -and $observation.risk -ne "unavailable") { $available++ }
            elseif ($observation.status -ne "unavailable") { throw "Unexpected prediction status/score combination at cycle $($observation.cycle)." }
            elseif ($observation.risk -ne "unavailable") { throw "Unavailable prediction has a non-null risk at cycle $($observation.cycle)." }
            # Non-alert protocol sentinels are ASCII. A localized alert description
            # (correct or mojibake) is never an identity key or a comparison field.
            # Alert schema has no model/policy/version: compare only unit/cycle/horizon
            # and the score within stdout's four-decimal rounding tolerance.
            if ($observation.alert -notin @("normal", "None", "n/a", "unavailable", "")) {
                $matchingAlerts = @($alerts | Where-Object { $_.unit_id -eq $UnitId -and $_.horizon -eq $Horizon -and
                    $_.cycle -eq $observation.cycle } | Where-Object {
                    if ($riskMissing) { $null -eq $_.risk_score }
                    else { $null -ne $_.risk_score -and [double]$_.risk_score -ge 0 -and [double]$_.risk_score -le 1 -and
                        [math]::Abs([double]$_.risk_score - $number) -le 0.000051 }
                })
                if (-not $matchingAlerts.Count) { $pending += "Expected persisted alert missing or risk mismatch at cycle $($observation.cycle)." }
                else { $matchedAlerts += $matchingAlerts }
            }
        }
        if (-not $pending.Count) { break }
        if ($attempt -eq 3) { throw "$($pending -join ' ') History read retries exhausted (3); endpoint limit is 200 rows, without pagination." }
        Write-Host "History not complete; retry $($attempt + 1)/3 in 500 ms."
        Start-Sleep -Milliseconds 500
    }
    if (-not $available) { throw "Replay persisted but all predictions are unavailable; no usable inference was demonstrated." }
    $existingIds = @($before | ForEach-Object { $_.id })
    $newCount = @($matchedPredictions | Where-Object { $_.id -notin $existingIds }).Count
    Write-Host "New prediction records: ${newCount}; repeated identities may legitimately reuse persisted rows."
    Write-Host "Alerts match unit/cycle/horizon and numeric risk; localized level is not an identity key. Schema has no model/policy."
    Write-Host "Operational history data: cloud predictions/alerts endpoints available; Streamlit pixels not tested."
    $persistenceStatus = "PASS (cloud API recovery + RDS task configuration; no direct SQL)"
    $passed = $true
}
catch { Write-Error $_.Exception.Message -ErrorAction Continue }
finally {
    Write-Host "Cloud API: $cloudApi"
    Write-Host "unit_id: $UnitId; horizon: $Horizon; model: $Model; policy: $TelemetryPolicy; cadence: $Cadence"
    Write-Host "Cycles sent: $cyclesSent; predictions found: $($matchedPredictions.Count); alerts found: $($matchedAlerts.Count)"
    Write-Host "Prediction statuses: $statuses"
    Write-Host "ECS: $ecsStatus; API health: $healthStatus"
    Write-Host "Persistence through cloud API: $persistenceStatus"
    if ($passed) { Write-Host "Result: PASS" } else { Write-Host "Result: FAIL" }
}
if (-not $passed) { exit 1 }
exit 0
