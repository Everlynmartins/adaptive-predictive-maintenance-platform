from __future__ import annotations

import httpx
import pytest

from predictive_maintenance.application.local_service import ApplicationSelection
from predictive_maintenance.ui.api_client import APIApplicationService, APIClientError


def _selection() -> ApplicationSelection:
    return ApplicationSelection(
        unit_id=1,
        horizon=30,
        model="fusion",
        telemetry_policy="full",
        inference_cadence="each_cycle",
    )


def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/health":
        return httpx.Response(200, json={"status": "available"})
    if request.url.path == "/api/v1/options":
        return httpx.Response(200, json={
            "unit_ids": [1], "horizons": [15, 30], "models": ["fusion"],
            "telemetry_policies": ["full"], "cadences": ["each_cycle"],
        })
    if request.url.path == "/api/v1/scenario":
        return httpx.Response(200, json={
            "trajectory": [{
                "unit_id": 1, "cycle": 1, "horizon": 30, "risk_score": None,
                "prediction_status": "unavailable", "input_validity": "invalid",
            }],
            "summary": {}, "assurance": {},
            "model_comparison": [], "telemetry_comparison": [],
        })
    return httpx.Response(404)


def test_api_client_preserves_prediction_status_and_input_validity() -> None:
    client = httpx.Client(transport=httpx.MockTransport(_handler))
    service = APIApplicationService(base_url="http://test", client=client)

    result = service.run(_selection())

    assert result.trajectory.iloc[0].prediction_status == "unavailable"
    assert result.trajectory.iloc[0].input_validity == "invalid"


def test_api_client_reports_timeout_without_local_fallback() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("controlled timeout", request=request)

    client = httpx.Client(transport=httpx.MockTransport(timeout))
    with pytest.raises(APIClientError, match="timed out"):
        APIApplicationService(base_url="http://test", client=client)


def test_api_client_reports_http_error_without_local_fallback() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )
    with pytest.raises(APIClientError, match="request failed"):
        APIApplicationService(base_url="http://test", client=client)


def test_api_client_gets_persisted_predictions_and_alerts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in {"/health", "/api/v1/options"}:
            return _handler(request)
        if request.url.path == "/api/v1/predictions":
            assert dict(request.url.params) == {"unit_id": "1", "horizon": "30", "limit": "100"}
            return httpx.Response(200, json=[{
                "unit_id": 1, "cycle": 4, "horizon": 30, "model_name": "fusion",
                "prediction_status": "valid", "risk_score": 0.2,
            }])
        if request.url.path == "/api/v1/alerts":
            assert dict(request.url.params) == {"unit_id": "1", "horizon": "30", "limit": "100"}
            return httpx.Response(200, json=[{
                "unit_id": 1, "cycle": 4, "horizon": 30, "alert_level": "atenção",
            }])
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        service = APIApplicationService(base_url="http://test", client=client)
        predictions = service.historical_predictions(unit_id=1, horizon=30)
        alerts = service.historical_alerts(unit_id=1, horizon=30)

    assert predictions[0]["prediction_status"] == "valid"
    assert alerts[0]["alert_level"] == "atenção"


def test_api_client_reports_history_error_without_local_fallback() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in {"/health", "/api/v1/options"}:
            return _handler(request)
        return httpx.Response(503, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        service = APIApplicationService(base_url="http://test", client=client)
        with pytest.raises(APIClientError, match="request failed"):
            service.historical_predictions(unit_id=1, horizon=30)


def test_running_dashboard_client_reports_outage_and_recovers() -> None:
    unavailable = False

    def handler(request: httpx.Request) -> httpx.Response:
        if unavailable and request.url.path == "/api/v1/scenario":
            return httpx.Response(503)
        return _handler(request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        service = APIApplicationService(base_url="http://test", client=client)
        unavailable = True
        with pytest.raises(APIClientError, match="request failed"):
            service.run(_selection())
        unavailable = False
        result = service.run(_selection())
    assert result.trajectory.iloc[0].prediction_status == "unavailable"
    assert result.trajectory.iloc[0].input_validity == "invalid"
