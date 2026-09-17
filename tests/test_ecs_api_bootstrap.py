"""Small configuration tests only; no AWS, model loading or CA network calls."""

import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy.engine import make_url

_source = Path(__file__).resolve().parents[1] / "infra/aws/runtime/api_bootstrap.py"
_spec = importlib.util.spec_from_file_location("ecs_api_bootstrap", _source)
bootstrap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bootstrap)


@pytest.fixture
def configuration():
    return {"DB_HOST": "database.internal", "DB_PORT": "5432", "DB_NAME": "predictive_maintenance",
            "DB_USERNAME": "pm_lab", "DB_PASSWORD": "test-only:@/ ?#%&+", "AWS_REGION": "sa-east-1"}


def test_secret_characters_roundtrip_without_shell(configuration):
    parsed = make_url(bootstrap.database_url(configuration, "/tmp/public-ca.pem"))
    assert parsed.password == configuration["DB_PASSWORD"]
    assert parsed.username == configuration["DB_USERNAME"]
    assert parsed.host == configuration["DB_HOST"]
    assert parsed.query["sslmode"] == "verify-full"
    assert parsed.query["sslrootcert"] == "/tmp/public-ca.pem"


@pytest.mark.parametrize("missing", ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USERNAME", "DB_PASSWORD"])
def test_missing_field_has_no_fallback(configuration, missing):
    configuration.pop(missing)
    with pytest.raises(ValueError):
        bootstrap.database_url(configuration, "/tmp/ca.pem")


def test_unsupported_port(configuration):
    configuration["DB_PORT"] = "5433"
    with pytest.raises(ValueError):
        bootstrap.database_url(configuration, "/tmp/ca.pem")


def test_launch_sets_existing_api_contract(configuration, monkeypatch):
    for name, value in configuration.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(bootstrap, "download_ca", lambda region: "/tmp/test-public-ca.pem")
    executor = Mock()
    monkeypatch.setattr(bootstrap.os, "execvpe", executor)
    bootstrap.main()
    _, arguments, environment = executor.call_args.args
    assert "predictive_maintenance.api.main:app" in arguments
    assert make_url(environment["DATABASE_URL"]).password == configuration["DB_PASSWORD"]
    assert "DB_PASSWORD" not in environment
    assert "DB_USERNAME" not in environment


def test_bootstrap_failure_never_logs_secret(configuration, monkeypatch, capsys):
    for name, value in configuration.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(bootstrap, "download_ca", Mock(side_effect=RuntimeError(configuration["DB_PASSWORD"])))
    executor = Mock()
    monkeypatch.setattr(bootstrap.os, "execvpe", executor)
    assert bootstrap.main() == 1
    assert configuration["DB_PASSWORD"] not in capsys.readouterr().err
    executor.assert_not_called()


def test_invalid_region_never_accesses_network(monkeypatch):
    network = Mock()
    monkeypatch.setattr(bootstrap, "urlopen", network)
    with pytest.raises(ValueError):
        bootstrap.download_ca("../other-host")
    network.assert_not_called()
