"""PowerShell contract tests with function mocks; no AWS/Terraform CLI is run."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
pytestmark = pytest.mark.skipif(not POWERSHELL, reason="PowerShell is not installed")


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def run_script(tmp_path, name, data, argument=""):
    source = tmp_path / "responses.json"
    source.write_text(json.dumps(data), encoding="utf-8")
    calls = tmp_path / "calls.txt"
    driver = tmp_path / "driver.ps1"
    driver.write_text(
        f"$mock = Get-Content -Raw {quote(source)} | ConvertFrom-Json\n"
        f"$callFile = {quote(calls)}\n"
        "$env:AWS_REGION = 'sa-east-1'\n"
        "function aws {\n"
        "  $global:LASTEXITCODE = 0\n"
        "  $key = $args[0] + ' ' + $args[1]\n"
        "  $reply = $mock.aws.PSObject.Properties[$key].Value\n"
        "  if ($null -eq $reply) { throw 'Unexpected AWS mock call' }\n"
        "  $reply | ConvertTo-Json -Depth 100 -Compress\n"
        "}\n"
        "function terraform {\n"
        "  $global:LASTEXITCODE = 0\n"
        "  $verb = $args[1]\n"
        "  Add-Content -LiteralPath $callFile -Value $verb\n"
        "  if ($verb -eq 'output') {\n"
        "    $reply = $mock.outputs.PSObject.Properties[$args[3]].Value\n"
        "    if ($args[2] -eq '-json') { $reply | ConvertTo-Json -Compress } else { $reply }\n"
        "  } elseif ($verb -eq 'plan') {\n"
        "    Write-Error 'Simulated stderr warning, exit code remains zero'\n"
        "    $global:LASTEXITCODE = 2\n"
        "    'Mock plan'\n"
        "  } elseif ($verb -eq 'show') { $mock.plan | ConvertTo-Json -Depth 100 -Compress\n"
        "  } elseif ($verb -eq 'apply') { 'Mock apply'\n"
        "  } else { throw 'Unexpected Terraform mock call' }\n"
        "}\n"
        f"& {quote(ROOT / 'scripts' / name)} {argument}\n"
        "exit $LASTEXITCODE\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(driver)],
        capture_output=True, text=True, timeout=30,
    )
    return result, calls.read_text(encoding="utf-8-sig").splitlines()


def responses(count):
    image = "example.invalid/lab:stage3-lab-v1"
    secret = "arn:aws:secretsmanager:sa-east-1:000000000000:secret:test"
    containers = [
        {"name": "api", "image": image, "environment": [{"name": "DB_HOST", "value": "db.internal"}],
         "secrets": [{"name": "DB_USERNAME", "valueFrom": secret + ":username::"},
                     {"name": "DB_PASSWORD", "valueFrom": secret + ":password::"}]},
        {"name": "dashboard", "image": image, "environment": [
            {"name": "APP_BACKEND", "value": "api"},
            {"name": "PREDICTIVE_MAINTENANCE_API_URL", "value": "http://127.0.0.1:8000"}]},
    ]
    for container in containers:
        container["healthCheck"] = {"command": ["CMD", "python"]}
        container["logConfiguration"] = {"logDriver": "awslogs", "options": {
            "awslogs-group": "/lab/" + container["name"], "awslogs-region": "sa-east-1"}}
    task = {"lastStatus": "RUNNING", "launchType": "FARGATE", "taskDefinitionArn": "task:1",
            "containers": [{"name": name, "lastStatus": "RUNNING", "healthStatus": "HEALTHY", "image": image}
                           for name in ("api", "dashboard")],
            "attachments": [{"type": "ElasticNetworkInterface", "details": [
                {"name": "networkInterfaceId", "value": "eni-test"}]}]}
    return {"outputs": {"ecs_cluster_name": "lab", "ecs_service_name": "lab",
                        "ecs_task_definition_arn": "task:1", "ecs_desired_count": count,
                        "ecr_repository_url": "example.invalid/lab", "rds_endpoint": "db.internal",
                        "rds_master_secret_arn": secret,
                        "cloudwatch_log_group_names": {"api": "/lab/api", "dashboard": "/lab/dashboard"}},
            "aws": {
                "ecs describe-clusters": {"clusters": [{"status": "ACTIVE"}], "failures": []},
                "ecs describe-services": {"services": [{"status": "ACTIVE", "launchType": "FARGATE",
                    "desiredCount": count, "runningCount": count, "pendingCount": 0, "taskDefinition": "task:1"}], "failures": []},
                "ecs describe-task-definition": {"taskDefinition": {"networkMode": "awsvpc",
                    "requiresCompatibilities": ["FARGATE"], "cpu": "1024", "memory": "4096", "containerDefinitions": containers}},
                "ecs list-tasks": {"taskArns": ["task-running"] if count else []},
                "ecs describe-tasks": {"tasks": [task], "failures": []},
                "ec2 describe-network-interfaces": {"NetworkInterfaces": [{"Association": {"PublicIp": "192.0.2.10"}}]},
            }}


@pytest.mark.parametrize("count,expected", [(0, "READY / NOT RUNNING"), (1, "Resultado: PASS")])
def test_check_zero_is_ready_and_one_requires_healthy(tmp_path, count, expected):
    result, _ = run_script(tmp_path, "aws_ecs_check.ps1", responses(count))
    assert result.returncode == 0, result.stdout + result.stderr
    assert expected in result.stdout


def test_check_unhealthy_container_fails(tmp_path):
    data = responses(1)
    data["aws"]["ecs describe-tasks"]["tasks"][0]["containers"][0]["healthStatus"] = "UNHEALTHY"
    result, _ = run_script(tmp_path, "aws_ecs_check.ps1", data)
    assert result.returncode != 0
    assert "Resultado: FAIL" in result.stdout


def test_endpoint_reads_dynamic_public_ip(tmp_path):
    result, _ = run_script(tmp_path, "aws_ecs_endpoint.ps1", responses(1))
    assert result.returncode == 0, result.stderr
    assert "http://192.0.2.10:8000" in result.stdout
    assert "http://192.0.2.10:8501" in result.stdout


@pytest.mark.parametrize("allowed", [True, False])
@pytest.mark.parametrize("action,target", [("start", 1), ("stop", 0)])
def test_controller_applies_only_count_change_and_accepts_stderr_warning(tmp_path, allowed, action, target):
    data = responses(1 - target)
    data["plan"] = {"resource_changes": [{"mode": "managed", "address": "aws_ecs_service.lab",
        "change": {"actions": ["update"], "before": {"desired_count": 1 - target, "name": "lab"},
                   "after": {"desired_count": target, "name": "lab" if allowed else "changed"}}}]}
    result, calls = run_script(tmp_path, "aws_lab.ps1", data, action)
    assert (result.returncode == 0) is allowed, result.stdout + result.stderr
    assert ("apply" in calls) is allowed
    assert "Simulated stderr warning" in result.stderr
