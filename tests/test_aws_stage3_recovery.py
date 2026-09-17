"""Controlled ECS recovery with function mocks only; never runs AWS executables."""

import copy
import re

import pytest

from test_aws_stage3_scripts import POWERSHELL, run_script


pytestmark = pytest.mark.skipif(not POWERSHELL, reason="PowerShell not installed")
SCRIPT = "aws_stage3_recovery_test.ps1"
ARGUMENTS = "-InitialTimeoutSeconds 1 -RecoveryTimeoutSeconds 1 -PollSeconds 1"


def recovery_data():
    # These are synthetic metadata identifiers, not real resources/credentials.
    original = "arn:aws:ecs:sa-east-1:000000000000:task/lab/original123"
    replacement = "arn:aws:ecs:sa-east-1:000000000000:task/lab/replacement456"

    def task(arn, eni):
        return {"taskArn": arn, "lastStatus": "RUNNING", "healthStatus": "HEALTHY",
            "containers": [{"name": name, "lastStatus": "RUNNING", "healthStatus": "HEALTHY"}
                           for name in ("api", "dashboard")],
            "attachments": [{"type": "ElasticNetworkInterface", "details": [
                {"name": "networkInterfaceId", "value": eni}]}]}

    old = task(original, "eni-before")
    new = task(replacement, "eni-after")
    stopped = {**old, "lastStatus": "STOPPED", "stoppedReason": "stage3 controlled recovery validation"}
    predictions = [
        {"id": 1, "unit_id": 1, "cycle": 1, "horizon": 30, "risk_score": None,
         "prediction_status": "unavailable", "model_name": "fusion", "model_version": "test-v1",
         "telemetry_policy": "full", "cadence": "each_cycle"},
        {"id": 2, "unit_id": 1, "cycle": 3, "horizon": 30, "risk_score": 0.012584497359253911,
         "prediction_status": "valid", "model_name": "fusion", "model_version": "test-v1",
         "telemetry_policy": "full", "cadence": "each_cycle"},
    ]
    alerts = [{"id": 1, "unit_id": 1, "cycle": 3, "horizon": 30,
               "risk_score": 0.012584497359253911, "alert_level": "atenção"}]
    return {"trace_arguments": True, "expected_original_arn": original,
        "outputs": {"ecs_cluster_name": "lab", "ecs_service_name": "lab"},
        "aws": {
            "ecs describe-services": {"services": [{"status": "ACTIVE", "launchType": "FARGATE", "desiredCount": 1}], "failures": []},
            "ecs list-tasks": {"taskArns": [original]},
            "ecs describe-tasks": {"tasks": [old], "failures": []},
            "ecs stop-task": {"task": stopped},
            "ec2 describe-network-interfaces": {"NetworkInterfaces": [{"Association": {"PublicIp": "192.0.2.10"}}]},
        },
        "aws_after_stop": {
            "ecs list-tasks": {"taskArns": [replacement]},
            "ec2 describe-network-interfaces": {"NetworkInterfaces": [{"Association": {"PublicIp": "192.0.2.20"}}]},
        },
        "tasks_after_stop": {
            original: {"tasks": [stopped], "failures": []},
            replacement: {"tasks": [new], "failures": []},
        },
        "http": {"/health": {"status": "available"},
                 "/api/v1/predictions": predictions, "/api/v1/alerts": alerts},
    }


def test_recovery_stops_only_original_and_preserves_records_at_new_endpoint(tmp_path):
    data = recovery_data()
    result, calls = run_script(tmp_path, SCRIPT, data, ARGUMENTS)
    assert result.returncode == 0, result.stdout + result.stderr
    for message in ("Original task: STOPPED", "Replacement task: RUNNING", "API: HEALTHY",
                    "Dashboard: HEALTHY", "Endpoint rediscovered: PASS", "Predictions before: 2",
                    "Predictions after: 2", "Alerts before: 1", "Alerts after: 1",
                    "Persistent records preserved: PASS", "Recovery: PASS", "Result: PASS"):
        assert message in result.stdout
    stop_calls = [line for line in calls.splitlines() if line.startswith("awsargs ecs stop-task")]
    assert len(stop_calls) == 1
    assert data["expected_original_arn"] in stop_calls[0]
    assert "--reason stage3 controlled recovery validation" in stop_calls[0]
    assert "--network-interface-ids eni-after" in calls
    assert "GET http://192.0.2.10:8000/api/v1/predictions?" in calls
    assert "GET http://192.0.2.20:8000/api/v1/predictions?" in calls
    assert "GET http://192.0.2.20:8000/health" in calls
    assert "stop-task" in calls and "update-service" not in calls
    assert "simulator" not in calls and "/predict?" not in calls
    assert "000000000000" not in result.stdout


@pytest.mark.parametrize("failure", ["same_task", "unhealthy", "not_running", "not_stopped", "missing_prediction", "missing_alert", "changed_risk", "changed_status", "stop_error", "desired_zero", "empty_baseline"])
def test_recovery_failure_is_explicit_and_bounded(tmp_path, failure):
    data = recovery_data()
    original = data["expected_original_arn"]
    replacement = data["aws_after_stop"]["ecs list-tasks"]["taskArns"][0]
    new = data["tasks_after_stop"][replacement]["tasks"][0]
    if failure == "same_task":
        data["aws_after_stop"]["ecs list-tasks"]["taskArns"] = [original]
    elif failure == "unhealthy":
        new["containers"][1]["healthStatus"] = "UNHEALTHY"
    elif failure == "not_running":
        new["lastStatus"] = "PENDING"
    elif failure == "not_stopped":
        data["tasks_after_stop"][original]["tasks"][0]["lastStatus"] = "STOPPING"
    elif failure in ("missing_prediction", "missing_alert", "changed_risk", "changed_status"):
        data["http_after_stop"] = copy.deepcopy(data["http"])
        if failure == "missing_prediction":
            data["http_after_stop"]["/api/v1/predictions"] = []
        elif failure == "missing_alert":
            data["http_after_stop"]["/api/v1/alerts"] = []
        elif failure == "changed_risk":
            data["http_after_stop"]["/api/v1/alerts"][0]["risk_score"] = 0.9
        elif failure == "changed_status":
            data["http_after_stop"]["/api/v1/predictions"][1]["prediction_status"] = "degraded"
    elif failure == "stop_error":
        data["stop_error"] = True
    elif failure == "desired_zero":
        data["aws"]["ecs describe-services"]["services"][0]["desiredCount"] = 0
    elif failure == "empty_baseline":
        data["http"]["/api/v1/predictions"] = []
    result, calls = run_script(tmp_path, SCRIPT, data, ARGUMENTS)
    assert result.returncode != 0 and "Result: FAIL" in result.stdout
    assert "aws_stage3_logs.ps1" in result.stdout
    assert "update-service" not in calls
    if failure in ("same_task", "unhealthy", "not_running", "not_stopped"):
        assert "Timeout waiting" in re.sub(r"\s+", " ", result.stderr)
        assert calls.count("sleep ") <= 1
    if failure in ("desired_zero", "empty_baseline"):
        assert "aws ecs stop-task" not in calls


def test_recovery_accepts_reused_ip_numeric_tolerance_and_changed_localized_label(tmp_path):
    data = recovery_data()
    data["aws_after_stop"]["ec2 describe-network-interfaces"]["NetworkInterfaces"][0]["Association"]["PublicIp"] = "192.0.2.10"
    data["http_after_stop"] = copy.deepcopy(data["http"])
    data["http_after_stop"]["/api/v1/alerts"][0]["alert_level"] = "atenÃ§Ã£o"
    data["http_after_stop"]["/api/v1/alerts"][0]["risk_score"] += 1e-11
    result, calls = run_script(tmp_path, SCRIPT, data, ARGUMENTS)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Result: PASS" in result.stdout and "--network-interface-ids eni-after" in calls


def test_native_stop_warning_does_not_imply_failure(tmp_path):
    data = recovery_data()
    data["stop_warning"] = True
    result, _ = run_script(tmp_path, SCRIPT, data, ARGUMENTS)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Result: PASS" in result.stdout
    assert "Simulated stop warning" in result.stderr


def test_initial_api_can_stabilize_with_bounded_wait(tmp_path):
    data = recovery_data()
    data["http_sequences"] = {"/health": [{"status": "initializing"}, {"status": "available"}]}
    result, calls = run_script(tmp_path, SCRIPT, data, ARGUMENTS)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Result: PASS" in result.stdout
    assert calls.count("sleep ") == 1


def test_unhealthy_initial_task_times_out_without_stop(tmp_path):
    data = recovery_data()
    data["aws"]["ecs describe-tasks"]["tasks"][0]["healthStatus"] = "UNKNOWN"
    result, calls = run_script(tmp_path, SCRIPT, data, ARGUMENTS)
    assert result.returncode != 0 and "Result: FAIL" in result.stdout
    assert "Timeout waiting" in re.sub(r"\s+", " ", result.stderr)
    assert "aws ecs stop-task" not in calls
