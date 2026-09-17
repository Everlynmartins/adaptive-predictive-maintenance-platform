from __future__ import annotations

from io import StringIO
import os
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
import streamlit as st
from streamlit.testing.v1 import AppTest

from predictive_maintenance.api.main import app, get_repository
from predictive_maintenance.api.persistence import PersistenceRepository
from predictive_maintenance.application.local_service import ApplicationSelection
from predictive_maintenance.simulator.telemetry_producer import (
    SimulationConfig,
    TelemetrySimulator,
)
from predictive_maintenance.ui.api_client import APIApplicationService, APIClientError


class _OpenTestClient:
    """Keep the shared TestClient open when the simulator finishes."""

    def __init__(self, client: TestClient) -> None:
        self.client = client

    def get(self, url: str, **kwargs: object):
        return self.client.get(url, **kwargs)

    def post(self, url: str, **kwargs: object):
        return self.client.post(url, **kwargs)

    def close(self) -> None:
        return None

    def request(self, method: str, url: str, **kwargs: object):
        return self.client.request(method, url, **kwargs)


def test_short_stage2_flow_is_sequential_persisted_and_dashboard_reachable() -> None:
    repository = PersistenceRepository("sqlite://")
    app.dependency_overrides[get_repository] = lambda: repository
    try:
        with TestClient(app) as client:
            transport = _OpenTestClient(client)
            health = client.get("/health")
            unit = client.get("/api/v1/units/1").json()
            start_cycle = int(unit["last_cycle"]) - 2
            result = TelemetrySimulator(
                SimulationConfig(
                    api_base_url="http://testserver",
                    unit_id=1,
                    horizon=30,
                    model="fusion",
                    telemetry_policy="full",
                    cadence="each_cycle",
                    mode="fast",
                    start_cycle=start_cycle,
                    max_cycles=3,
                ),
                transport=transport,
                output=StringIO(),
            ).run()
            predictions = client.get(
                "/api/v1/predictions", params={"unit_id": 1, "horizon": 30}
            )
            alerts = client.get(
                "/api/v1/alerts", params={"unit_id": 1, "horizon": 30}
            )
            dashboard_service = APIApplicationService(
                base_url="http://testserver", client=transport
            )
            dashboard_result = dashboard_service.run(ApplicationSelection(
                unit_id=1,
                horizon=30,
                model="fusion",
                telemetry_policy="full",
                inference_cadence="each_cycle",
            ))
            st.cache_resource.clear()
            with patch.dict(os.environ, {"APP_BACKEND": "api"}), patch(
                "predictive_maintenance.ui.api_client.APIApplicationService",
                return_value=dashboard_service,
            ):
                dashboard = AppTest.from_file(str(
                    Path(__file__).parents[1]
                    / "src/predictive_maintenance/ui/streamlit_app.py"
                )).run(timeout=60)
                st.cache_resource.clear()
                with patch.dict(os.environ, {"APP_BACKEND": "api"}), patch(
                    "predictive_maintenance.ui.api_client.APIApplicationService",
                    return_value=dashboard_service,
                ), patch.object(
                    dashboard_service,
                    "historical_predictions",
                    side_effect=APIClientError("controlled history outage"),
                ):
                    dashboard_history_outage = AppTest.from_file(str(
                        Path(__file__).parents[1]
                        / "src/predictive_maintenance/ui/streamlit_app.py"
                    )).run(timeout=60)
                st.cache_resource.clear()

        expected_cycles = tuple(range(start_cycle, start_cycle + 3))
        assert health.status_code == 200
        assert result.cycles_sent == expected_cycles
        assert [row["cycle"] for row in predictions.json()] == list(expected_cycles)
        assert predictions.status_code == 200
        assert alerts.status_code == 200
        assert alerts.json()
        assert [row["cycle"] for row in alerts.json()] == sorted(
            row["cycle"] for row in alerts.json()
        )
        assert dashboard_service.available_units
        assert list(dashboard.exception) == []
        assert any(item.label == "Risk score" for item in dashboard.metric)
        assert any("Persisted predictions" in item.value for item in dashboard.markdown)
        assert list(dashboard_history_outage.exception) == []
        assert any(item.label == "Risk score" for item in dashboard_history_outage.metric)
        assert any("Operational history unavailable" in item.value for item in dashboard_history_outage.error)
        assert not dashboard_result.trajectory.empty
        assert {"prediction_status", "input_validity"} <= set(
            dashboard_result.trajectory.columns
        )
    finally:
        app.dependency_overrides.clear()
