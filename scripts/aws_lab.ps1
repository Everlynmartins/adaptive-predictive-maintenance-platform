param([Parameter(Mandatory = $true, Position = 0)][ValidateSet("start", "stop", "status", "endpoints")][string]$Action)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "aws_ecs_common.ps1")
$planFile = $null
try {
    if ($Action -in @("status", "endpoints")) {
        $scriptName = if ($Action -eq "status") { "aws_ecs_check.ps1" } else { "aws_ecs_endpoint.ps1" }
        & (Join-Path $PSScriptRoot $scriptName)
        if ($LASTEXITCODE -ne 0) { throw "Consulta falhou (exit code $LASTEXITCODE)." }
    }
    else {
        Require-Tool terraform
        $count = if ($Action -eq "start") { 1 } else { 0 }
        $planFile = [System.IO.Path]::GetTempFileName()
        Write-Host "Planejando somente desired_count=$count..."
        $null = Invoke-LabNative terraform @("-chdir=$TerraformRoot", "plan", "-input=false", "-detailed-exitcode", "-var=ecs_desired_count=$count", "-out=$planFile") @(0, 2)
        $plan = (Invoke-LabNative terraform @("-chdir=$TerraformRoot", "show", "-json", $planFile)) | ConvertFrom-Json
        $changes = @($plan.resource_changes | Where-Object { $_.mode -eq "managed" -and ($_.change.actions -join ',') -ne "no-op" })
        foreach ($change in $changes) {
            if ($change.address -ne "aws_ecs_service.lab" -or ($change.change.actions -join ',') -ne "update") { throw "Plan inclui outra alteracao: $($change.address). Revise com terraform_plan.ps1; controle LAB cancelado." }
            $before = $change.change.before | ConvertTo-Json -Depth 100 -Compress | ConvertFrom-Json
            $after = $change.change.after | ConvertTo-Json -Depth 100 -Compress | ConvertFrom-Json
            $before.PSObject.Properties.Remove("desired_count")
            $after.PSObject.Properties.Remove("desired_count")
            if (($before | ConvertTo-Json -Depth 100 -Compress) -ne ($after | ConvertTo-Json -Depth 100 -Compress) -or $change.change.after.desired_count -ne $count) { throw "Service tem alteracoes alem de desired_count; controle LAB cancelado." }
        }
        if ($changes.Count -gt 1) { throw "Esperada no maximo uma alteracao do service." }
        # Executed only by the local operator: apply this inspected saved plan,
        # preserving Terraform state and refusing changes to other resources.
        $result = Invoke-LabNative terraform @("-chdir=$TerraformRoot", "apply", "-input=false", $planFile)
        Write-Host $result
        $env:TF_VAR_ecs_desired_count = [string]$count
        Write-Host "Desired count=$count registrado pelo Terraform. RDS nao foi iniciado/parado."
        Write-Host "Em novas sessoes, mantenha TF_VAR_ecs_desired_count=$count ao executar plan/apply."
        Write-Host "Aguarde estabilizacao e execute .\scripts\aws_lab.ps1 status."
    }
}
catch {
    Write-Error $_.Exception.Message -ErrorAction Continue
    exit 1
}
finally {
    if ($planFile -and (Test-Path -LiteralPath $planFile)) { Remove-Item -LiteralPath $planFile -Force }
}
