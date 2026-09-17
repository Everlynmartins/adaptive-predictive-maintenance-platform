"""Cloud replay contracts with mocked AWS/HTTP/simulator; no external calls."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
pytestmark = pytest.mark.skipif(not POWERSHELL, reason="PowerShell not installed")


def quoted(value):
    return "'" + str(value).replace("'", "''") + "'"


def run_script(tmp_path, filename, data, arguments=""):
    fixture = tmp_path / "responses.json"
    fixture.write_text(json.dumps(data), encoding="utf-8")
    calls = tmp_path / "calls.txt"
    script = (ROOT / "scripts" / filename).read_text(encoding="utf-8")
    script = script.replace(
        '. (Join-Path $PSScriptRoot "aws_ecs_common.ps1")',
        f". {quoted(ROOT / 'scripts/aws_ecs_common.ps1')}",
    )
    if filename == "aws_stage3_e2e_test.ps1":
        # Replace only simulator transport at its call boundary; never run the
        # project console executable, API, science or any AWS executable.
        script = script.replace(
            '$cloudApi = "not discovered"',
            "function Invoke-ExistingSimulator { param([string]$BaseUrl, [int]$FirstCycle)\n"
            "  Add-Content -LiteralPath $callFile -Value ('simulator ' + $BaseUrl)\n"
            "  if ($mock.simulator_fail) { throw 'Mock simulator exit code 1' }\n"
            "  return $mock.stdout\n}\n$cloudApi = \"not discovered\"",
        )
    target = tmp_path / "target.ps1"
    target.write_text(script, encoding="utf-8")
    driver = tmp_path / "driver.ps1"
    driver.write_text(
        f"$mock = Get-Content -Raw -Encoding UTF8 {quoted(fixture)} | ConvertFrom-Json\n"
        f"$callFile = {quoted(calls)}\n"
        "$env:AWS_REGION = 'sa-east-1'\n"
        "$httpReadCounts = @{}\n"
        "$global:mockStopped = $false\n"
        "function Start-Sleep { param([int]$Milliseconds) Add-Content -LiteralPath $callFile -Value ('sleep ' + $Milliseconds) }\n"
        "function aws {\n"
        "  $global:LASTEXITCODE = 0\n"
        "  $key = $args[0] + ' ' + $args[1]\n"
        "  Add-Content -LiteralPath $callFile -Value ('aws ' + $key)\n"
        "  if ($mock.trace_arguments) { Add-Content -LiteralPath $callFile -Value ('awsargs ' + ($args -join ' ')) }\n"
        "  $reply = $mock.aws.PSObject.Properties[$key].Value\n"
        "  if ($key -eq 'ecs stop-task') {\n"
        "    $target = $args[[array]::IndexOf($args, '--task') + 1]\n"
        "    if ($mock.expected_original_arn -and $target -ne $mock.expected_original_arn) { throw 'Wrong task stopped' }\n"
        "    if ($mock.stop_error) { $global:LASTEXITCODE = 1; return }\n"
        "    if ($mock.stop_warning) { Write-Error 'Simulated stop warning, successful exit code' }\n"
        "    $global:mockStopped = $true\n"
        "  }\n"
        "  if ($global:mockStopped -and $mock.aws_after_stop) {\n"
        "    $replacement = $mock.aws_after_stop.PSObject.Properties[$key]\n"
        "    if ($replacement) { $reply = $replacement.Value }\n"
        "  }\n"
        "  if ($key -eq 'ecs describe-tasks' -and $global:mockStopped -and $mock.tasks_after_stop) {\n"
        "    $target = $args[[array]::IndexOf($args, '--tasks') + 1]\n"
        "    $reply = $mock.tasks_after_stop.PSObject.Properties[$target].Value\n"
        "  }\n"
        "  if ($null -eq $reply) { throw 'Unexpected AWS mock request' }\n"
        "  ConvertTo-Json -InputObject $reply -Depth 100 -Compress\n"
        "}\n"
        "function terraform {\n"
        "  $global:LASTEXITCODE = 0\n"
        "  if ($args[1] -ne 'output') { throw 'Mutable Terraform call prohibited' }\n"
        "  $reply = $mock.outputs.PSObject.Properties[$args[3]].Value\n"
        "  if ($args[2] -eq '-json') { ConvertTo-Json -InputObject $reply -Compress } else { $reply }\n"
        "}\n"
        "function Invoke-WebRequest {\n"
        "  [CmdletBinding()] param([switch]$UseBasicParsing, [string]$Method, [string]$Uri, [int]$TimeoutSec)\n"
        "  Add-Content -LiteralPath $callFile -Value ($Method + ' ' + $Uri)\n"
        "  $path = ([uri]$Uri).AbsolutePath\n"
        "  if ($mock.fail_path -eq $path) { throw 'Mock cloud API unavailable' }\n"
        "  $reply = $mock.http.PSObject.Properties[$path].Value\n"
        "  if ($global:mockStopped -and $mock.http_after_stop) {\n"
        "    $replacement = $mock.http_after_stop.PSObject.Properties[$path]\n"
        "    if ($replacement) { $reply = $replacement.Value }\n"
        "  }\n"
        "  $readIndex = 0\n"
        "  if ($httpReadCounts.ContainsKey($path)) { $readIndex = $httpReadCounts[$path] }\n"
        "  $httpReadCounts[$path] = $readIndex + 1\n"
        "  if ($mock.http_sequences) {\n"
        "    $sequence = $mock.http_sequences.PSObject.Properties[$path].Value\n"
        "    if ($sequence) { $reply = $sequence[[math]::Min($readIndex, $sequence.Count - 1)] }\n"
        "  }\n"
        "  if ($null -eq $reply) { throw 'Unexpected HTTP mock request' }\n"
        "  [PSCustomObject]@{ StatusCode=200; Content=(ConvertTo-Json -InputObject $reply -Depth 100 -Compress) }\n"
        "}\n"
        f"& {quoted(target)} {arguments}\nexit $LASTEXITCODE\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(driver)],
        capture_output=True, text=True, timeout=30,
    )
    return result, calls.read_text(encoding="utf-8-sig") if calls.exists() else ""


def fixture_data():
    secret = "arn:aws:secretsmanager:sa-east-1:000000000000:secret:test"
    risks = [None, 0.2, 0.7, 0.8]
    statuses = ["unavailable", "degraded", "valid", "valid"]
    predictions = [{"id": cycle, "unit_id": 1, "cycle": cycle, "horizon": 30,
        "model_name": "fusion", "model_version": "test-v1", "telemetry_policy": "full",
        "cadence": "each_cycle", "risk_score": risks[cycle - 1],
        "prediction_status": statuses[cycle - 1], "input_validity": "valid",
        "created_at": "2026-09-17T10:00:00Z"} for cycle in range(1, 5)]
    # Legitimate different model, not a duplicate or a scenario match.
    predictions.append({**predictions[1], "id": 99, "model_name": "xgboost"})
    return {
        "outputs": {"ecs_cluster_name": "lab", "ecs_service_name": "lab",
            "ecs_task_definition_arn": "task:1", "rds_endpoint": "db.internal",
            "rds_port": "5432", "rds_database_name": "predictive_maintenance",
            "rds_master_secret_arn": secret,
            "cloudwatch_log_group_names": {"api": "/lab/api", "dashboard": "/lab/dashboard"}},
        "aws": {
            "ecs describe-services": {"services": [{"status": "ACTIVE", "launchType": "FARGATE", "desiredCount": 1}], "failures": []},
            "ecs list-tasks": {"taskArns": ["task-running"]},
            "ecs describe-tasks": {"tasks": [{"lastStatus": "RUNNING", "taskDefinitionArn": "task:1",
                "containers": [{"name": name, "lastStatus": "RUNNING", "healthStatus": "HEALTHY"} for name in ("api", "dashboard")],
                "attachments": [{"type": "ElasticNetworkInterface", "details": [{"name": "networkInterfaceId", "value": "eni-test"}]}]}], "failures": []},
            "ecs describe-task-definition": {"taskDefinition": {"containerDefinitions": [{"name": "api",
                "environment": [{"name": "DB_HOST", "value": "db.internal"}, {"name": "DB_PORT", "value": "5432"},
                    {"name": "DB_NAME", "value": "predictive_maintenance"}],
                "secrets": [{"name": "DB_USERNAME", "valueFrom": secret + ":username::"},
                    {"name": "DB_PASSWORD", "valueFrom": secret + ":password::"}]}]}},
            "ec2 describe-network-interfaces": {"NetworkInterfaces": [{"Association": {"PublicIp": "192.0.2.10"}}]},
            "logs filter-log-events": {"events": [{"timestamp": 1789639200000,
                "message": 'Uvicorn ready password=test-secret token="test-token" postgresql+psycopg://user:test-password@db/name'}]},
        },
        "http": {
            "/health": {"status": "available"},
            "/api/v1/options": {"unit_ids": [1], "horizons": [15, 30], "models": ["fusion"], "telemetry_policies": ["full"], "cadences": ["each_cycle"]},
            "/api/v1/units/1": {"unit_id": 1, "first_cycle": 1, "last_cycle": 200},
            "/api/v1/predictions": predictions,
            "/api/v1/alerts": [{"id": cycle, "unit_id": 1, "cycle": cycle, "horizon": 30, "alert_level": "alerta", "risk_score": risks[cycle - 1]} for cycle in (3, 4)],
        },
        "stdout": "\n".join(f"cycle={cycle} risk_score={'unavailable' if risks[cycle-1] is None else format(risks[cycle-1], '.4f')} "
            f"alert_level={'None' if cycle == 1 else 'normal' if cycle == 2 else 'alerta'} prediction_status={statuses[cycle-1]}" for cycle in range(1, 5)),
    }


def test_e2e_cloud_history_preserves_status_and_idempotent_records(tmp_path):
    result, calls = run_script(tmp_path, "aws_stage3_e2e_test.ps1", fixture_data(), "-Cycles 4")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Result: PASS" in result.stdout
    assert "predictions found: 4; alerts found: 2" in result.stdout
    assert "unavailable=1" in result.stdout and "degraded=1" in result.stdout
    assert "New prediction records: 0" in result.stdout
    assert "simulator http://192.0.2.10:8000" in calls
    assert "localhost" not in calls and "127.0.0.1" not in calls
    assert "model=fusion" not in next(line for line in calls.splitlines() if "/predictions?" in line)


@pytest.mark.parametrize("failure", ["no_task", "unhealthy", "cloud_down", "missing_prediction", "missing_alert", "duplicate", "loopback", "simulator_error"])
def test_e2e_controlled_failure_never_passes(tmp_path, failure):
    data = fixture_data()
    if failure == "no_task":
        data["aws"]["ecs list-tasks"]["taskArns"] = []
    elif failure == "unhealthy":
        data["aws"]["ecs describe-tasks"]["tasks"][0]["containers"][0]["healthStatus"] = "UNHEALTHY"
    elif failure == "cloud_down":
        data["fail_path"] = "/health"
    elif failure == "missing_prediction":
        data["http"]["/api/v1/predictions"].pop(2)
    elif failure == "missing_alert":
        data["http"]["/api/v1/alerts"] = []
    elif failure == "duplicate":
        data["http"]["/api/v1/predictions"].append({**data["http"]["/api/v1/predictions"][0], "id": 100})
    elif failure == "loopback":
        data["aws"]["ec2 describe-network-interfaces"]["NetworkInterfaces"][0]["Association"]["PublicIp"] = "127.0.0.1"
    elif failure == "simulator_error":
        data["simulator_fail"] = True
    result, calls = run_script(tmp_path, "aws_stage3_e2e_test.ps1", data, "-Cycles 4")
    assert result.returncode != 0
    assert "Result: FAIL" in result.stdout
    assert "localhost" not in calls and "127.0.0.1" not in calls
    if failure == "cloud_down":
        assert "GET http://192.0.2.10:8000/health; HTTP NO RESPONSE" in re.sub(r"\s+", " ", result.stderr)


def test_logs_read_only_and_redact_known_credentials(tmp_path):
    result, calls = run_script(tmp_path, "aws_stage3_logs.ps1", fixture_data(), "both")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Uvicorn ready" in result.stdout and "REDACTED" in result.stdout
    assert not any(secret in result.stdout for secret in ("test-secret", "test-token", "test-password"))
    assert calls.splitlines() == ["aws logs filter-log-events", "aws logs filter-log-events"]


def test_replay_without_alert_does_not_invent_alerts(tmp_path):
    data = fixture_data()
    data["stdout"] = data["stdout"].replace("alert_level=alerta", "alert_level=normal")
    # Existing alerts from other scenarios are not attributed to this replay.
    result, _ = run_script(tmp_path, "aws_stage3_e2e_test.ps1", data, "-Cycles 4")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Result: PASS" in result.stdout and "alerts found: 0" in result.stdout


def test_out_of_order_simulator_acknowledgements_fail(tmp_path):
    data = fixture_data()
    lines = data["stdout"].splitlines()
    lines[1], lines[2] = lines[2], lines[1]
    data["stdout"] = "\n".join(lines)
    result, _ = run_script(tmp_path, "aws_stage3_e2e_test.ps1", data, "-Cycles 4")
    assert result.returncode != 0 and "Result: FAIL" in result.stdout


def test_localized_mojibake_level_is_not_an_alert_identity(tmp_path):
    data = fixture_data()
    actual_risks = {3: 0.012584497359253911, 4: 0.011913986339899938}
    for record in data["http"]["/api/v1/predictions"]:
        if record["cycle"] in actual_risks:
            record["risk_score"] = actual_risks[record["cycle"]]
    for alert in data["http"]["/api/v1/alerts"]:
        # Exactly the historical alert fields: no model/policy/cadence.
        alert["alert_level"] = "atenção"
        alert["risk_score"] = actual_risks[alert["cycle"]]
    data["stdout"] = data["stdout"].replace("risk_score=0.7000", "risk_score=0.0126").replace(
        "risk_score=0.8000", "risk_score=0.0119").replace("alert_level=alerta", "alert_level=atenÃ§Ã£o")
    result, calls = run_script(tmp_path, "aws_stage3_e2e_test.ps1", data, "-Cycles 4")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "alerts found: 2" in result.stdout and "Result: PASS" in result.stdout
    assert "sleep" not in calls


def test_history_retry_recovers_delayed_predictions_and_alerts(tmp_path):
    data = fixture_data()
    predictions = data["http"]["/api/v1/predictions"]
    alerts = data["http"]["/api/v1/alerts"]
    data["http_sequences"] = {
        "/api/v1/predictions": [predictions, [p for p in predictions if p["cycle"] != 3], predictions],
        "/api/v1/alerts": [[alerts[1]], alerts],
    }
    result, calls = run_script(tmp_path, "aws_stage3_e2e_test.ps1", data, "-Cycles 4")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Result: PASS" in result.stdout
    assert calls.count("sleep 500") == 1
    assert sum("GET " in line and "/alerts?" in line for line in calls.splitlines()) == 2


@pytest.mark.parametrize("problem", ["missing_prediction", "missing_alert", "wrong_risk", "wrong_identity"])
def test_history_retry_exhaustion_never_masks_missing_or_wrong_records(tmp_path, problem):
    data = fixture_data()
    if problem == "missing_prediction":
        data["http"]["/api/v1/predictions"].pop(2)
    elif problem == "missing_alert":
        data["http"]["/api/v1/alerts"] = []
    elif problem == "wrong_risk":
        data["http"]["/api/v1/alerts"][0]["risk_score"] = 0.9
    elif problem == "wrong_identity":
        data["http"]["/api/v1/alerts"][0]["unit_id"] = 2
    result, calls = run_script(tmp_path, "aws_stage3_e2e_test.ps1", data, "-Cycles 4")
    assert result.returncode != 0 and "Result: FAIL" in result.stdout
    assert calls.count("sleep 500") == 2
    assert "retries exhausted (3)" in result.stderr
