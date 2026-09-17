from __future__ import annotations

from fastapi.testclient import TestClient

from predictive_maintenance.api.main import app, get_service
from predictive_maintenance.application.local_service import LocalApplicationService


def _client() -> TestClient:
    app.dependency_overrides[get_service] = lambda: LocalApplicationService()
    return TestClient(app)


def _valid_request(unit_id: int = 1) -> dict[str, object]:
    return {
        "unit_id": unit_id,
        "cycle": 1,
        "horizon": 30,
        "model": "fusion",
        "telemetry_policy": "full",
        "cadence": "each_cycle",
    }


def test_health_and_options_expose_local_service_contract() -> None:
    with _client() as client:
        health = client.get("/health")
        options = client.get("/api/v1/options")

    assert health.status_code == 200
    assert health.json() == {"status": "available"}
    assert options.status_code == 200
    assert 1 in options.json()["unit_ids"]
    assert options.json()["horizons"] == [15, 30]


def test_predict_returns_contract_for_valid_request() -> None:
    with _client() as client:
        response = client.post("/api/v1/predict", json=_valid_request())

    assert response.status_code == 200
    payload = response.json()
    assert payload["unit_id"] == 1
    assert payload["cycle"] == 1
    assert payload["horizon"] == 30
    assert 0.0 <= payload["risk_score"] <= 1.0
    assert payload["health_score"] == 100.0 * payload["survival_score"]


def test_invalid_unit_and_horizon_return_client_errors() -> None:
    with _client() as client:
        unknown_unit = client.post("/api/v1/predict", json=_valid_request(unit_id=999999))
        invalid_horizon = client.post(
            "/api/v1/predict", json={**_valid_request(), "horizon": 16},
        )

    assert unknown_unit.status_code == 404
    assert invalid_horizon.status_code == 422


def test_invalid_model_and_incomplete_payload_return_client_errors() -> None:
    with _client() as client:
        invalid_model = client.post(
            "/api/v1/predict", json={**_valid_request(), "model": "unknown"},
        )
        incomplete = client.post(
            "/api/v1/predict", json={"unit_id": 1, "cycle": 1, "horizon": 30},
        )

    assert invalid_model.status_code == 422
    assert incomplete.status_code == 422


def test_unavailable_prediction_status_is_preserved() -> None:
    request = {
        **_valid_request(),
        "model": "tcn",
        "telemetry_policy": "fixed_k5",
    }
    with _client() as client:
        response = client.post("/api/v1/predict", json=request)

    assert response.status_code == 200
    payload = response.json()
    assert payload["prediction_status"] == "unavailable"
    assert payload["risk_score"] is None


def test_unit_and_trajectory_endpoints_use_the_same_service() -> None:
    with _client() as client:
        unit = client.get("/api/v1/units/1")
        trajectory = client.get("/api/v1/units/1/trajectory")

    assert unit.status_code == 200
    assert unit.json()["prediction_cycles"] > 0
    assert trajectory.status_code == 200
    assert trajectory.json()["predictions"][0]["unit_id"] == 1
