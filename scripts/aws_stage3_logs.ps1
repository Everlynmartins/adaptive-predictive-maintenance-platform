param(
    [Parameter(Position = 0)][ValidateSet("api", "dashboard", "both")][string]$Component = "both",
    [ValidateRange(1, 1440)][int]$Minutes = 15,
    [ValidateRange(1, 100)][int]$Limit = 40
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "aws_ecs_common.ps1")

function Protect-LogMessage {
    param([string]$Message)
    # Defense in depth: runtime must never log secrets. Never query secret values.
    $text = [regex]::Replace($Message, '(?i)postgres(?:ql)?(?:\+\w+)?://[^\s]+', '[DATABASE URL REDACTED]')
    $pattern = '(?i)(aws_access_key_id|aws_secret_access_key|aws_session_token|db_password|password|authorization|token|secret_value|database_url)["'']?\s*[:=]\s*(?:"[^"]*"|''[^'']*''|[^\s,;]+)'
    $text = [regex]::Replace($text, $pattern, '$1=[REDACTED]')
    $text = [regex]::Replace($text, '(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._+/=-]+', '$1 [REDACTED]')
    return [regex]::Replace($text, '\b(?:AKIA|ASIA)[A-Z0-9]{16}\b', '[AWS KEY REDACTED]')
}

try {
    Initialize-LabRead
    $names = (Invoke-LabNative terraform @("-chdir=$TerraformRoot", "output", "-json", "cloudwatch_log_group_names")) | ConvertFrom-Json
    $components = if ($Component -eq "both") { @("api", "dashboard") } else { @($Component) }
    $start = [DateTimeOffset]::UtcNow.AddMinutes(-$Minutes).ToUnixTimeMilliseconds()
    foreach ($name in $components) {
        $group = $names.PSObject.Properties[$name].Value
        if ([string]::IsNullOrWhiteSpace($group)) { throw "CloudWatch log group output missing for ${name}." }
        $response = Invoke-LabAws @("logs", "filter-log-events", "--log-group-name", $group,
            "--start-time", [string]$start, "--limit", [string]$Limit, "--no-paginate")
        Write-Host "${name}: ${group}; last ${Minutes} minutes (one bounded page)"
        foreach ($event in @($response.events)) {
            $timestamp = [DateTimeOffset]::FromUnixTimeMilliseconds([long]$event.timestamp).ToString("u")
            Write-Host "${timestamp} $(Protect-LogMessage $event.message)"
        }
        if (-not @($response.events).Count) { Write-Host "No recent events in this page." }
        if ($response.nextToken) { Write-Host "More events may exist; this command intentionally limits output." }
    }
}
catch {
    Write-Error $_.Exception.Message -ErrorAction Continue
    exit 1
}
