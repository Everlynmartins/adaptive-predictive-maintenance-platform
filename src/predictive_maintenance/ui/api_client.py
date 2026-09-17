"""Thin dashboard adapter for the FastAPI application backend."""

from __future__ import annotations

import os
from typing import Any

import httpx
import pandas as pd

from predictive_maintenance.application.local_service import ApplicationResult, ApplicationSelection


class APIClientError(RuntimeError):
    """The API backend is unavailable or violates the dashboard contract."""


class APIApplicationService:
    """Expose the application-service interface through HTTP."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float = 30.0,
        client: Any | None = None,
    ) -> None:
        self.base_url = (
            base_url or os.environ.get("PREDICTIVE_MAINTENANCE_API_URL", "http://127.0.0.1:8000")
        ).rstrip("/")
        self.client = client or httpx.Client(timeout=timeout_seconds)
        health = self._request("GET", "/health")
        if health.get("status") != "available":
            raise APIClientError("API health contract is unavailable")
        options = self._request("GET", "/api/v1/options")
        try:
            self.available_units = tuple(int(value) for value in options["unit_ids"])
            self.horizons = tuple(int(value) for value in options["horizons"])
            self.models = tuple(str(value) for value in options["models"])
            self.policies = tuple(str(value) for value in options["telemetry_policies"])
            self.inference_cadences = tuple(str(value) for value in options["cadences"])
        except (KeyError, TypeError, ValueError) as exc:
            raise APIClientError("API options contract is invalid") from exc

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self.client.request(method, f"{self.base_url}{path}", **kwargs)
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise APIClientError("API request timed out") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise APIClientError("API request failed") from exc
        if not isinstance(payload, dict):
            raise APIClientError("API response must be an object")
        return payload

    def _request_collection(self, method: str, path: str, **kwargs: Any) -> list[dict[str, Any]]:
        """Request persisted history without treating it as a local fallback."""

        try:
            response = self.client.request(method, f"{self.base_url}{path}", **kwargs)
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise APIClientError("API request timed out") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise APIClientError("API request failed") from exc
        if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
            raise APIClientError("API history response must be a list of objects")
        return payload

    def historical_predictions(
        self,
        *,
        unit_id: int,
        horizon: int,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return persisted prediction records through the FastAPI contract."""

        return self._request_collection(
            "GET",
            "/api/v1/predictions",
            params={"unit_id": unit_id, "horizon": horizon, "limit": limit},
        )

    def historical_alerts(
        self,
        *,
        unit_id: int,
        horizon: int,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return persisted alert records through the FastAPI contract."""

        return self._request_collection(
            "GET",
            "/api/v1/alerts",
            params={"unit_id": unit_id, "horizon": horizon, "limit": limit},
        )

    def run(self, selection: ApplicationSelection) -> ApplicationResult:
        payload = self._request("POST", "/api/v1/scenario", json={
            "unit_id": selection.unit_id,
            "horizon": selection.horizon,
            "model": selection.model,
            "telemetry_policy": selection.telemetry_policy,
            "cadence": selection.inference_cadence,
            "retrospective": selection.retrospective,
        })
        try:
            trajectory = pd.DataFrame(payload["trajectory"])
            required = {
                "unit_id", "cycle", "horizon", "risk_score",
                "prediction_status", "input_validity",
            }
            if not required <= set(trajectory.columns):
                raise APIClientError("API trajectory contract is incomplete")
            return ApplicationResult(
                selection=selection,
                trajectory=trajectory,
                summary=dict(payload["summary"]),
                assurance=dict(payload["assurance"]),
                model_comparison=pd.DataFrame(payload["model_comparison"]),
                telemetry_comparison=pd.DataFrame(payload["telemetry_comparison"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise APIClientError("API scenario contract is invalid") from exc
