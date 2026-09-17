"""Local audit regressions: all native AWS/Docker/Terraform calls are mocked."""

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")


def _run(tmp_path, script, arguments="", login_exit=0, region_variable="AWS_REGION", profile_region=None):
    if not POWERSHELL:
        pytest.skip("PowerShell is not installed")
    target = str(ROOT / "scripts" / script).replace("'", "''")
    driver = tmp_path / "driver.ps1"
    region_setup = f"$env:{region_variable} = 'sa-east-1'\n" if region_variable else ""
    region_response = "    'configure get' { 'sa-east-1' }\n" if profile_region else (
        "    'configure get' { $global:LASTEXITCODE = 1; return }\n" if region_variable is None else ""
    )
    driver.write_text(
        "$env:AWS_REGION = ''\n$env:AWS_DEFAULT_REGION = ''\n"
        f"{region_setup}"
        "$env:AWS_PROFILE = 'stage3-lab'\n"
        "function aws {\n"
        "  $global:LASTEXITCODE = 0\n"
        "  switch ($args[0] + ' ' + $args[1]) {\n"
        "    '--version ' { 'Mock AWS CLI' }\n"
        "    'sts get-caller-identity' { '{\"Account\":\"000000000000\"}' }\n"
        "    'ecr describe-repositories' { '000000000000.dkr.ecr.sa-east-1.amazonaws.com/lab' }\n"
        "    'ecr describe-images' { 'sha256:mock-digest' }\n"
        f"{region_response}"
        "    default { throw 'Unexpected AWS call, including region lookup or password retrieval' }\n"
        "  }\n}\n"
        "function terraform {\n"
        "  $global:LASTEXITCODE = 0\n"
        "  if ($args[0] -eq 'version') { 'Mock Terraform'; return }\n"
        "  if ($args[1] -ne 'output' -or $args[3] -ne 'ecr_repository_name') { throw 'Unexpected Terraform call' }\n"
        "  'lab'\n}\n"
        "function docker {\n"
        "  if ($args[0] -ne 'info') { throw 'Unexpected direct Docker call' }\n"
        "  $global:LASTEXITCODE = 0\n}\n"
        "function cmd.exe {\n"
        "  $command = $args[-1]\n"
        "  if ($command -notlike '*aws ecr get-login-password*| docker login*--password-stdin*') { throw 'Native login pipeline missing' }\n"
        "  if (-not $command.Contains('--region \"sa-east-1\"') -or\n"
        "      -not $command.Contains('--profile \"stage3-lab\"') -or\n"
        "      -not $command.Contains('\"000000000000.dkr.ecr.sa-east-1.amazonaws.com\"')) { throw 'Dynamic login arguments missing' }\n"
        "  Write-Error 'Mock stderr warning, not a token'\n"
        f"  $global:LASTEXITCODE = {login_exit}\n"
        "  'Mock native login'\n}\n"
        f"& '{target}' {arguments}\nexit $LASTEXITCODE\n",
        encoding="utf-8",
    )
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(driver)],
        capture_output=True, text=True, timeout=30,
    )


@pytest.mark.parametrize("login_exit", [0, 4])
def test_ecr_check_native_pipeline_uses_exit_code(tmp_path, login_exit):
    result = _run(tmp_path, "aws_ecr_check.ps1", "-ExpectedTag stage3-lab-v1", login_exit)
    assert (result.returncode == 0) is (login_exit == 0), result.stdout + result.stderr
    assert "Mock stderr warning" in result.stderr
    assert ("sha256:mock-digest" in result.stdout) is (login_exit == 0)


@pytest.mark.parametrize("region_variable", ["AWS_REGION", "AWS_DEFAULT_REGION"])
def test_aws_check_honors_environment_without_profile_region_lookup(tmp_path, region_variable):
    result = _run(tmp_path, "aws_check.ps1", region_variable=region_variable)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "sa-east-1" in result.stdout


@pytest.mark.parametrize("profile_region", [True, False])
def test_aws_check_profile_region_fallback_or_explicit_failure(tmp_path, profile_region):
    result = _run(tmp_path, "aws_check.ps1", region_variable=None, profile_region=profile_region)
    assert (result.returncode == 0) is profile_region, result.stdout + result.stderr


def test_docker_context_excludes_local_state_plans_and_environment_files():
    patterns = set((ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines())
    assert {".env", ".env.*", "infra/aws/.terraform", "infra/aws/terraform.tfstate*",
            "infra/aws/*.tfvars", "infra/aws/*.tfplan"} <= patterns
