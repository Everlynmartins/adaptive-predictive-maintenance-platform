# Test the controller with a Docker stub; no engine or containers are accessed.
$ErrorActionPreference = "Stop"
$TestProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$StackScript = Join-Path $TestProjectRoot "scripts/local_stack.ps1"
$global:Stage2DockerCalls = New-Object 'System.Collections.Generic.List[object]'
function global:docker {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$DockerArguments)
    $global:Stage2DockerCalls.Add([PSCustomObject]@{
        Arguments = $DockerArguments
        Directory = (Get-Location).Path
    })
    $global:LASTEXITCODE = 0
}
try {
    Push-Location ([System.IO.Path]::GetTempPath())
    try {
        foreach ($action in @("start", "stop", "restart", "status", "logs", "rebuild")) {
            & $StackScript $action
        }
    }
    finally { Pop-Location }
    $composeCalls = @($global:Stage2DockerCalls | Where-Object { $_.Arguments[0] -eq "compose" })
    if ($composeCalls.Count -ne 10) { throw "unexpected number of Compose calls" }
    foreach ($call in $composeCalls) {
        $args = $call.Arguments
        if ($args[1] -ne "-f" -or $args[2] -ne (Join-Path $TestProjectRoot "docker-compose.yml") -or
            $args[3] -ne "--project-directory" -or $args[4] -ne $TestProjectRoot -or
            $call.Directory -ne $TestProjectRoot) { throw "incorrect Compose path" }
        if ($args -contains "-v") { throw "volume deletion flag detected" }
    }
    $firstUp = $composeCalls[0].Arguments
    if ($firstUp -contains "--build") { throw "normal start unexpectedly builds" }
    if ($composeCalls[-2].Arguments -notcontains "--build") { throw "rebuild flag missing" }
    Write-Output "local_stack stub test: PASS (6 commands, no Docker access)"
}
finally {
    Remove-Item Function:\docker
    Remove-Variable Stage2DockerCalls -Scope Global
}
