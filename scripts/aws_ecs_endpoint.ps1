$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "aws_ecs_common.ps1")
try {
    Initialize-LabRead
    $service = Get-LabService
    $tasks = @(Get-LabRunningTasks | Where-Object { $_.lastStatus -eq "RUNNING" })
    if ($tasks.Count -eq 0) {
        if ($service.desiredCount -eq 0) { Write-Host "READY / NOT RUNNING: nenhum endpoint ativo." }
        else { throw "Task ainda nao esta RUNNING; aguarde e use aws_ecs_check.ps1." }
    }
    else {
        foreach ($task in $tasks) {
            $publicIp = Get-LabPublicIp $task
            if ([string]::IsNullOrWhiteSpace($publicIp)) { throw "Task sem IPv4 publico." }
            Write-Host "API: http://${publicIp}:8000"
            Write-Host "Dashboard: http://${publicIp}:8501"
        }
    }
}
catch {
    Write-Error $_.Exception.Message -ErrorAction Continue
    exit 1
}
