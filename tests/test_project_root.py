from __future__ import annotations

from pathlib import Path

from predictive_maintenance.api.main import _resolve_project_root
from predictive_maintenance.application.local_service import (
    ConfigurationUnavailableError,
    LocalApplicationService,
)


def test_explicit_project_root_is_used(monkeypatch, tmp_path: Path) -> None:
    explicit = tmp_path / "configured-root"
    monkeypatch.setenv("PREDICTIVE_MAINTENANCE_PROJECT_ROOT", str(explicit))

    assert _resolve_project_root() == explicit.resolve()


def test_local_checkout_root_is_discovered(monkeypatch) -> None:
    monkeypatch.delenv("PREDICTIVE_MAINTENANCE_PROJECT_ROOT", raising=False)

    root = _resolve_project_root()

    assert (root / "configs" / "local_app.toml").is_file()
    assert LocalApplicationService(project_root=root).config_path == (
        root / "configs" / "local_app.toml"
    ).resolve()


def test_missing_configuration_is_reported(tmp_path: Path) -> None:
    try:
        LocalApplicationService(project_root=tmp_path)
    except ConfigurationUnavailableError as exc:
        assert "application configuration is missing" in str(exc)
    else:
        raise AssertionError("missing configuration must be explicit")
