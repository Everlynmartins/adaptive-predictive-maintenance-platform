$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "aws_ecs_common.ps1")
try {
    Initialize-LabRead
    $clusters = Invoke-LabAws @("ecs", "describe-clusters", "--clusters", $LabCluster)
    if (@($clusters.failures).Count -gt 0 -or $clusters.clusters[0].status -ne "ACTIVE") { throw "Cluster ECS nao esta ACTIVE." }
    $service = Get-LabService
    if ($service.status -ne "ACTIVE" -or $service.launchType -ne "FARGATE") { throw "Service deve estar ACTIVE em Fargate." }
    if ($service.desiredCount -ne [int](Get-LabOutput "ecs_desired_count")) { throw "Desired count difere do state Terraform; reconcilie antes de validar." }
    $definitionArn = Get-LabOutput "ecs_task_definition_arn"
    if ($service.taskDefinition -ne $definitionArn) { throw "Task definition diferente do state Terraform." }
    $definition = (Invoke-LabAws @("ecs", "describe-task-definition", "--task-definition", $definitionArn)).taskDefinition
    if ($definition.networkMode -ne "awsvpc" -or "FARGATE" -notin $definition.requiresCompatibilities) { throw "Task definition nao e Fargate/awsvpc." }
    $containers = @($definition.containerDefinitions)
    if ($containers.Count -ne 2 -or "api" -notin $containers.name -or "dashboard" -notin $containers.name) { throw "Esperados exatamente api e dashboard." }
    $repository = Get-LabOutput "ecr_repository_url"
    $images = @($containers | ForEach-Object { $_.image } | Select-Object -Unique)
    if ($images.Count -ne 1 -or -not $images[0].StartsWith("${repository}:")) { throw "Os containers devem usar a mesma imagem ECR." }
    if ($images[0] -match ':latest$') { throw "Use uma tag versionada, nao latest." }
    $api = $containers | Where-Object { $_.name -eq "api" }
    $dashboard = $containers | Where-Object { $_.name -eq "dashboard" }
    $expectedHost = (Get-LabOutput "rds_endpoint") -replace ':\d+$', ''
    $configuredHost = @($api.environment | Where-Object { $_.name -eq "DB_HOST" })
    if ($configuredHost.Count -ne 1 -or $configuredHost[0].value -ne $expectedHost) { throw "Endpoint RDS diferente do Terraform." }
    $secretArn = Get-LabOutput "rds_master_secret_arn"
    foreach ($field in @(@("DB_USERNAME", "username"), @("DB_PASSWORD", "password"))) {
        $reference = @($api.secrets | Where-Object { $_.name -eq $field[0] })
        if ($reference.Count -ne 1 -or $reference[0].valueFrom -ne "${secretArn}:$($field[1])::") { throw "Referencia do secret incorreta." }
    }
    if (@($api.environment | Where-Object { $_.name -in @("DB_PASSWORD", "DATABASE_URL") }).Count -gt 0) { throw "Credenciais nao devem aparecer em environment plaintext." }
    if (($dashboard.environment | Where-Object { $_.name -eq "APP_BACKEND" }).value -ne "api" -or
        ($dashboard.environment | Where-Object { $_.name -eq "PREDICTIVE_MAINTENANCE_API_URL" }).value -ne "http://127.0.0.1:8000") { throw "Dashboard deve consumir a API por loopback." }
    $logNames = (Invoke-LabNative terraform @("-chdir=$TerraformRoot", "output", "-json", "cloudwatch_log_group_names")) | ConvertFrom-Json
    foreach ($container in $containers) {
        $expectedLog = $logNames.PSObject.Properties[$container.name].Value
        if ($container.logConfiguration.logDriver -ne "awslogs" -or
            $container.logConfiguration.options.'awslogs-group' -ne $expectedLog -or
            $container.logConfiguration.options.'awslogs-region' -ne $LabRegion) { throw "Logs incorretos para $($container.name)." }
        if (-not $container.healthCheck) { throw "Health check ausente para $($container.name)." }
    }
    Write-Host "Cluster/service: $LabCluster / $LabService"
    Write-Host "Desired: $($service.desiredCount); running: $($service.runningCount); pending: $($service.pendingCount)"
    Write-Host "Task definition: configurada; CPU $($definition.cpu); memoria $($definition.memory) MiB"
    Write-Host "Imagem: $($images[0]); RDS: $($configuredHost[0].value); logs: configurados; secret: referenciado"
    $tasks = @(Get-LabRunningTasks)
    if ($service.desiredCount -eq 0) {
        if ($service.runningCount -ne 0 -or $service.pendingCount -ne 0 -or $tasks.Count -gt 0) { throw "Parada em andamento; aguarde zero tasks running/pending." }
        Write-Host "Resultado: READY / NOT RUNNING"
    }
    elseif ($service.desiredCount -eq 1) {
        if ($service.runningCount -ne 1 -or $service.pendingCount -ne 0 -or $tasks.Count -ne 1) { throw "Esperada uma task em execucao; aguarde estabilizacao." }
        $task = $tasks[0]
        if ($task.lastStatus -ne "RUNNING" -or $task.launchType -ne "FARGATE" -or $task.taskDefinitionArn -ne $definitionArn) { throw "Task nao corresponde ao deployment esperado." }
        if (@($task.containers).Count -ne 2) { throw "Task deve ter dois containers." }
        foreach ($container in $task.containers) {
            Write-Host "$($container.name): $($container.lastStatus) / $($container.healthStatus)"
            if ($container.lastStatus -ne "RUNNING" -or $container.healthStatus -ne "HEALTHY" -or $container.image -ne $images[0]) { throw "Container $($container.name) ainda nao esta saudavel." }
        }
        $publicIp = Get-LabPublicIp $task
        if ([string]::IsNullOrWhiteSpace($publicIp)) { throw "IPv4 publico ausente." }
        Write-Host "API: http://${publicIp}:8000"
        Write-Host "Dashboard: http://${publicIp}:8501"
        Write-Host "Resultado: PASS (metadados ECS; replay/SQL cloud ainda precisam de validacao)."
    }
    else { throw "Desired count fora do LAB (0 ou 1)." }
}
catch {
    Write-Host "Resultado: FAIL"
    Write-Error $_.Exception.Message -ErrorAction Continue
    exit 1
}
