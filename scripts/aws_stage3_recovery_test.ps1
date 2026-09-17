param(
    [ValidateRange(1, 2147483647)][int]$UnitId = 1,
    [ValidateSet(15, 30)][int]$Horizon = 30,
    [ValidateRange(1, 900)][int]$InitialTimeoutSeconds = 180,
    [ValidateRange(1, 1800)][int]$RecoveryTimeoutSeconds = 600,
    [ValidateRange(1, 30)][int]$PollSeconds = 5
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "aws_ecs_common.ps1")

# Bound CLI I/O for this script while reusing the existing region/profile helpers.
$script:RecoveryAwsReader = (Get-Command Invoke-LabAws).ScriptBlock
function Invoke-LabAws {
    param([string[]]$Arguments)
    return (& $script:RecoveryAwsReader -Arguments ($Arguments + @("--cli-connect-timeout", "5", "--cli-read-timeout", "10")))
}

function Protect-RecoveryMessage {
    param([string]$Message)
    $text = [regex]::Replace($Message, '(?<=:)\d{12}(?=:)', '[account]')
    $text = [regex]::Replace($text, '(?i)postgres(?:ql)?(?:\+\w+)?://[^\s]+', '[database URL redacted]')
    $text = [regex]::Replace($text, '(?i)\b[A-Za-z0-9.-]+\.rds\.amazonaws\.com\b', '[RDS endpoint]')
    return [regex]::Replace($text, '(?i)(password|db_password|secret_value|aws_access_key_id|aws_secret_access_key|aws_session_token|token)\s*[:=]\s*\S+', '$1=[redacted]')
}

function Invoke-RecoveryGet {
    param([string]$Endpoint)
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Method GET -Uri $Endpoint -TimeoutSec 5 -ErrorAction Stop
        if ([int]$response.StatusCode -ne 200) { throw "Expected HTTP 200; received $($response.StatusCode)." }
        $payload = $response.Content | ConvertFrom-Json
        return $payload
    }
    catch {
        $status = "NO RESPONSE"
        if ($_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode }
        $body = $_.ErrorDetails.Message
        if ([string]::IsNullOrWhiteSpace($body)) { $body = $_.Exception.Message }
        throw "GET ${Endpoint}; HTTP ${status}; response body: $(Protect-RecoveryMessage $body)"
    }
}

function Assert-DesiredOne {
    $service = Get-LabService
    if ($service.status -ne "ACTIVE" -or $service.launchType -ne "FARGATE" -or $service.desiredCount -ne 1) {
        throw "Expected ACTIVE Fargate service with desired count 1; this test never changes it."
    }
}

function Wait-RecoveryState {
    param([string]$Description, [scriptblock]$Probe, [int]$TimeoutSeconds)
    $clock = [System.Diagnostics.Stopwatch]::StartNew()
    $attemptLimit = [int][math]::Ceiling($TimeoutSeconds / [double]$PollSeconds) + 1
    $script:LastWaitReason = "Not yet ready."
    for ($attempt = 1; $attempt -le $attemptLimit; $attempt++) {
        if ($attempt -gt 1 -and $clock.Elapsed.TotalSeconds -ge $TimeoutSeconds) { break }
        $state = & $Probe
        if ($state) { return $state }
        if ($attempt -lt $attemptLimit -and $clock.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
            $remaining = $TimeoutSeconds - $clock.Elapsed.TotalSeconds
            Start-Sleep -Milliseconds ([int][math]::Min($PollSeconds * 1000, $remaining * 1000))
        }
    }
    throw "Timeout waiting for ${Description} (${TimeoutSeconds}s): $(Protect-RecoveryMessage $script:LastWaitReason)"
}

function Get-HealthyCloudState {
    param([string]$ExcludedTaskArn = "")
    Assert-DesiredOne
    $tasks = @(Get-LabRunningTasks | Where-Object { $_.taskArn -ne $ExcludedTaskArn })
    if ($tasks.Count -ne 1) { $script:LastWaitReason = "Expected exactly one replacement/initial task."; return }
    $task = $tasks[0]
    if ($task.lastStatus -ne "RUNNING" -or $task.healthStatus -ne "HEALTHY") {
        $script:LastWaitReason = "Task is not RUNNING / HEALTHY."; return
    }
    foreach ($name in @("api", "dashboard")) {
        $container = @($task.containers | Where-Object { $_.name -eq $name })
        if ($container.Count -ne 1 -or $container[0].lastStatus -ne "RUNNING" -or $container[0].healthStatus -ne "HEALTHY") {
            $script:LastWaitReason = "Container ${name} is not RUNNING / HEALTHY."; return
        }
    }
    # Resolve the current task's ENI every time; never cache the old endpoint.
    $publicIp = Get-LabPublicIp $task
    $address = $null
    if ([string]::IsNullOrWhiteSpace($publicIp)) { $script:LastWaitReason = "Public IPv4 is not available yet."; return }
    if (-not [System.Net.IPAddress]::TryParse($publicIp, [ref]$address) -or
        $address.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork -or
        [System.Net.IPAddress]::IsLoopback($address) -or $publicIp -eq "0.0.0.0") { throw "Invalid ECS public IPv4; no localhost fallback." }
    $baseUrl = "http://${publicIp}:8000"
    try {
        $health = Invoke-RecoveryGet "${baseUrl}/health"
        if ($health.status -ne "available") { $script:LastWaitReason = "API health is not available."; return }
    }
    catch { $script:LastWaitReason = $_.Exception.Message; return }
    return [PSCustomObject]@{ Task = $task; BaseUrl = $baseUrl }
}

function Get-RecoverySnapshot {
    param([string]$BaseUrl)
    $query = "unit_id=${UnitId}&horizon=${Horizon}&limit=200"
    $predictions = @(Invoke-RecoveryGet "${BaseUrl}/api/v1/predictions?${query}")
    $alerts = @(Invoke-RecoveryGet "${BaseUrl}/api/v1/alerts?${query}")
    foreach ($record in @($predictions) + @($alerts)) {
        foreach ($field in @("unit_id", "cycle", "horizon", "risk_score")) {
            if (-not $record.PSObject.Properties[$field]) { throw "Historical record missing ${field}." }
        }
        if ($record.unit_id -ne $UnitId -or $record.horizon -ne $Horizon -or $record.cycle -lt 1) { throw "Historical response does not match requested unit/horizon/cycle." }
    }
    if (@($predictions | Where-Object { [string]::IsNullOrWhiteSpace($_.prediction_status) }).Count) { throw "Historical prediction_status missing." }
    if ($predictions.Count -eq 200 -or $alerts.Count -eq 200) {
        Write-Host "History limit reached: preservation covers the returned 200-row window; API has no pagination."
    }
    return [PSCustomObject]@{ Predictions = $predictions; Alerts = $alerts }
}

function Test-PreservedRisk {
    param($Before, $After)
    if ($null -eq $Before -or $null -eq $After) { return ($null -eq $Before -and $null -eq $After) }
    $first = [double]$Before
    $second = [double]$After
    if ([double]::IsNaN($first) -or [double]::IsInfinity($first) -or
        [double]::IsNaN($second) -or [double]::IsInfinity($second) -or
        $first -lt 0 -or $first -gt 1 -or $second -lt 0 -or $second -gt 1) { return $false }
    # Both values come from JSON API records, not rounded console output.
    return [math]::Abs($first - $second) -le 1e-10
}

function Assert-PreservedRecords {
    param([object[]]$Before, [object[]]$After, [switch]$Predictions)
    foreach ($record in $Before) {
        $candidates = @($After | Where-Object { $_.unit_id -eq $record.unit_id -and $_.cycle -eq $record.cycle -and $_.horizon -eq $record.horizon })
        # Compare stable persisted IDs when supplied, as well as logical fields.
        if ($record.PSObject.Properties['id']) { $candidates = @($candidates | Where-Object { $_.id -eq $record.id }) }
        if ($Predictions) {
            foreach ($field in @("prediction_status", "model_name", "model_version", "telemetry_policy", "cadence")) {
                if ($record.PSObject.Properties[$field]) { $candidates = @($candidates | Where-Object { $_.PSObject.Properties[$field].Value -eq $record.PSObject.Properties[$field].Value }) }
            }
        }
        $matches = @($candidates | Where-Object { Test-PreservedRisk $record.risk_score $_.risk_score })
        if (-not $matches.Count) {
            $kind = if ($Predictions) { "prediction" } else { "alert" }
            throw "Persistent ${kind} missing or changed at unit $($record.unit_id), cycle $($record.cycle), horizon $($record.horizon)."
        }
    }
}

$before = $null
$after = $null
$originalStatus = "NOT CONFIRMED"
$replacementStatus = "NOT CONFIRMED"
$apiStatus = "NOT CONFIRMED"
$dashboardStatus = "NOT CONFIRMED"
$endpointStatus = "NOT CONFIRMED"
$recordsStatus = "NOT CONFIRMED"
$passed = $false
$savedAwsAttempts = $env:AWS_MAX_ATTEMPTS
try {
    $env:AWS_MAX_ATTEMPTS = "1"
    Initialize-LabRead
    Assert-DesiredOne
    $initial = Wait-RecoveryState -Description "initial healthy task/API" -TimeoutSeconds $InitialTimeoutSeconds -Probe { Get-HealthyCloudState }
    $originalArn = $initial.Task.taskArn
    if ([string]::IsNullOrWhiteSpace($originalArn)) { throw "Original task ARN missing." }
    $shortId = ($originalArn -split '/')[-1]
    Write-Host "Original task ID: $($shortId.Substring(0, [math]::Min(8, $shortId.Length)))..."
    $before = Get-RecoverySnapshot $initial.BaseUrl
    if (-not $before.Predictions.Count) { throw "No baseline predictions: recovery/preservation cannot be demonstrated. No task was stopped." }
    $cycles = (@($before.Predictions | ForEach-Object { $_.cycle } | Sort-Object -Unique)) -join ", "
    $statuses = ($before.Predictions | Group-Object prediction_status | ForEach-Object { "$($_.Name)=$($_.Count)" }) -join ", "
    Write-Host "Before: predictions=$($before.Predictions.Count); alerts=$($before.Alerts.Count); cycles=$cycles; statuses=$statuses"
    Write-Host "Stopping only the current task; desired count remains 1. Scheduler will replace it."
    # The only mutating AWS call in this script. Run only by the local operator.
    $stop = Invoke-LabAws @("ecs", "stop-task", "--cluster", $LabCluster, "--task", $originalArn,
        "--reason", "stage3 controlled recovery validation")
    if ($stop.task.taskArn -ne $originalArn) { throw "Stop-task did not acknowledge the original task." }
    $originalStatus = "STOP REQUESTED"
    $stopped = Wait-RecoveryState -Description "original task STOPPED" -TimeoutSeconds ([math]::Min(120, $RecoveryTimeoutSeconds)) -Probe {
        Assert-DesiredOne
        $response = Invoke-LabAws @("ecs", "describe-tasks", "--cluster", $LabCluster, "--tasks", $originalArn)
        $old = @($response.tasks | Where-Object { $_.taskArn -eq $originalArn })
        if (@($response.failures).Count -gt 0 -or $old.Count -ne 1) { throw "Cannot confirm original task state." }
        if ($old[0].lastStatus -eq "STOPPED") { return $old[0] }
        $script:LastWaitReason = "Original task still $($old[0].lastStatus)."
    }
    $originalStatus = "STOPPED"
    if ($stopped.stoppedReason) { Write-Host "Stop reason: $(Protect-RecoveryMessage $stopped.stoppedReason)" }
    $replacement = Wait-RecoveryState -Description "different healthy replacement task/API" -TimeoutSeconds $RecoveryTimeoutSeconds -Probe { Get-HealthyCloudState -ExcludedTaskArn $originalArn }
    if ($replacement.Task.taskArn -eq $originalArn) { throw "Replacement task must differ from original." }
    $replacementStatus = "RUNNING"
    $apiStatus = "HEALTHY / HTTP 200"
    $dashboardStatus = "HEALTHY"
    $endpointStatus = "PASS"
    Write-Host "Rediscovered cloud API: $($replacement.BaseUrl)"
    $after = Get-RecoverySnapshot $replacement.BaseUrl
    Assert-PreservedRecords -Before $before.Predictions -After $after.Predictions -Predictions
    Assert-PreservedRecords -Before $before.Alerts -After $after.Alerts
    Assert-DesiredOne
    $recordsStatus = "PASS"
    $passed = $true
}
catch {
    Write-Error (Protect-RecoveryMessage $_.Exception.Message) -ErrorAction Continue
    Write-Host "Diagnostics: .\scripts\aws_stage3_logs.ps1 both (or choose api/dashboard)."
}
finally {
    if ($null -eq $savedAwsAttempts) { Remove-Item Env:AWS_MAX_ATTEMPTS -ErrorAction SilentlyContinue }
    else { $env:AWS_MAX_ATTEMPTS = $savedAwsAttempts }
    Write-Host "Original task: $originalStatus"
    Write-Host "Replacement task: $replacementStatus"
    Write-Host "API: $apiStatus"
    Write-Host "Dashboard: $dashboardStatus"
    Write-Host "Endpoint rediscovered: $endpointStatus"
    $predictionsBefore = if ($before) { $before.Predictions.Count } else { 0 }
    $predictionsAfter = if ($after) { $after.Predictions.Count } else { 0 }
    $alertsBefore = if ($before) { $before.Alerts.Count } else { 0 }
    $alertsAfter = if ($after) { $after.Alerts.Count } else { 0 }
    Write-Host "Predictions before: $predictionsBefore"
    Write-Host "Predictions after: $predictionsAfter"
    Write-Host "Alerts before: $alertsBefore"
    Write-Host "Alerts after: $alertsAfter"
    Write-Host "Persistent records preserved: $recordsStatus"
    if ($passed) { Write-Host "Recovery: PASS"; Write-Host "Result: PASS" }
    else { Write-Host "Recovery: FAIL"; Write-Host "Result: FAIL" }
}
if (-not $passed) { exit 1 }
exit 0
