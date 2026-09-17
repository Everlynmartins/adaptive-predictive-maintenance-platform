from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from predictive_maintenance.api.main import app, get_repository, get_service
from predictive_maintenance.api.persistence import (
    PersistenceError,
    PersistenceRepository,
    telemetry_events,
)


class _Service:
    available_units = (1, 2)
    horizons = (15, 30)
    models = ("fusion",)
    policies = ("full",)
    inference_cadences = ("each_cycle",)

    def run(self, selection: object) -> SimpleNamespace:
        unit_id = selection.unit_id
        frame = pd.DataFrame([
            {
                "unit_id": unit_id, "cycle": 1, "horizon": selection.horizon,
                "risk_score": 0.2, "survival_score": 0.8, "health_score": 80.0,
                "alert_level": "normal", "prediction_status": "valid",
                "input_validity": "valid", "telemetry_stale": False,
                "model": selection.model, "anomaly_score": 0.3, "disagreement": 0.1,
            },
            {
                "unit_id": unit_id, "cycle": 2, "horizon": selection.horizon,
                "risk_score": 0.8, "survival_score": 0.2, "health_score": 20.0,
                "alert_level": "alerta", "prediction_status": "valid",
                "input_validity": "valid", "telemetry_stale": False,
                "model": selection.model, "anomaly_score": 0.5, "disagreement": 0.2,
            },
        ])
        return SimpleNamespace(trajectory=frame, assurance={"model_version": "test-v1"})


@pytest.fixture(autouse=True)
def _reset_dependencies() -> None:
    app.dependency_overrides[get_service] = lambda: _Service()
    yield
    app.dependency_overrides.clear()


def _client(repository: object) -> TestClient:
    app.dependency_overrides[get_repository] = lambda: repository
    return TestClient(app)


def _request(unit_id: int = 1, cycle: int = 1) -> dict[str, object]:
    return {
        "unit_id": unit_id, "cycle": cycle, "horizon": 30,
        "model": "fusion", "telemetry_policy": "full", "cadence": "each_cycle",
    }


def test_prediction_and_alert_are_persisted_in_sqlite_memory() -> None:
    repository = PersistenceRepository("sqlite://")
    with _client(repository) as client:
        prediction = client.post("/api/v1/predict", json=_request(cycle=1))
        alert_prediction = client.post("/api/v1/predict", json=_request(cycle=2))
        predictions = client.get("/api/v1/predictions", params={"unit_id": 1})
        alerts = client.get("/api/v1/alerts", params={"unit_id": 1})

    assert prediction.status_code == 200
    assert alert_prediction.status_code == 200
    assert [row["cycle"] for row in predictions.json()] == [1, 2]
    assert alerts.status_code == 200
    assert alerts.json()[0]["alert_level"] == "alerta"
    with repository.engine.connect() as connection:
        assert connection.execute(select(telemetry_events.c.id)).all()


def test_history_filters_by_unit_and_keeps_temporal_order() -> None:
    repository = PersistenceRepository("sqlite://")
    with _client(repository) as client:
        client.post("/api/v1/predict", json=_request(unit_id=1, cycle=2))
        client.post("/api/v1/predict", json=_request(unit_id=1, cycle=1))
        client.post("/api/v1/predict", json=_request(unit_id=2, cycle=1))
        response = client.get("/api/v1/predictions", params={"unit_id": 1, "limit": 10})

    assert response.status_code == 200
    assert [row["unit_id"] for row in response.json()] == [1, 1]
    assert [row["cycle"] for row in response.json()] == [1, 2]


def test_database_failure_is_explicit_and_does_not_return_a_fabricated_score() -> None:
    class _BrokenRepository:
        def persist_prediction(self, request: object, prediction: object) -> None:
            raise PersistenceError("controlled failure")

    with _client(_BrokenRepository()) as client:
        response = client.post("/api/v1/predict", json=_request())

    assert response.status_code == 503
    assert response.json()["detail"] == "prediction persistence is unavailable"


def test_database_health_failure_is_explicit() -> None:
    class _BrokenRepository:
        def check_health(self) -> None:
            raise PersistenceError("controlled failure")

    with _client(_BrokenRepository()) as client:
        response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["detail"] == "local application is unavailable"


def test_prediction_remains_available_when_persistence_is_disabled() -> None:
    with _client(None) as client:
        response = client.post("/api/v1/predict", json=_request())

    assert response.status_code == 200
    assert response.json()["risk_score"] == 0.2


def test_database_outage_then_recovery_preserves_existing_history() -> None:
    repository = PersistenceRepository("sqlite://")

    class _TemporaryOutage:
        def persist_prediction(self, request: object, prediction: object) -> None:
            raise PersistenceError("controlled outage")

    with _client(repository) as client:
        assert client.post("/api/v1/predict", json=_request()).status_code == 200
        app.dependency_overrides[get_repository] = lambda: _TemporaryOutage()
        failed = client.post("/api/v1/predict", json=_request(cycle=2))
        assert failed.status_code == 503
        assert "risk_score" not in failed.json()
        app.dependency_overrides[get_repository] = lambda: repository
        assert client.post("/api/v1/predict", json=_request(cycle=2)).status_code == 200
        history = client.get("/api/v1/predictions", params={"unit_id": 1}).json()
    assert [row["cycle"] for row in history] == [1, 2]


def test_repeated_request_is_idempotent_and_other_horizon_is_legitimate() -> None:
    repository = PersistenceRepository("sqlite://")
    with _client(repository) as client:
        for _ in range(2):
            assert client.post("/api/v1/predict", json=_request(cycle=2)).status_code == 200
        assert client.post(
            "/api/v1/predict", json={**_request(cycle=2), "horizon": 15}
        ).status_code == 200
        history = client.get("/api/v1/predictions", params={"unit_id": 1}).json()
        alert_history = client.get("/api/v1/alerts", params={"unit_id": 1}).json()
    assert len(history) == 2
    assert {row["horizon"] for row in history} == {15, 30}
    assert len(alert_history) == 2


def test_persistence_source_has_no_hardcoded_credentials() -> None:
    source = (Path(__file__).parents[1] / "src/predictive_maintenance/api/persistence.py").read_text(
        encoding="utf-8"
    )
    assert "postgresql://" not in source
    assert "password=" not in source
