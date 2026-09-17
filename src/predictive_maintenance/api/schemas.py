"""Pydantic contracts for the local REST API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PredictRequest(BaseModel):
    """Selection of one already available local prediction."""

    unit_id: int = Field(gt=0)
    cycle: int = Field(gt=0)
    horizon: int
    model: str = Field(min_length=1)
    telemetry_policy: str = Field(min_length=1)
    cadence: str = Field(min_length=1)


class ScenarioRequest(BaseModel):
    unit_id: int = Field(gt=0)
    horizon: int
    model: str = Field(min_length=1)
    telemetry_policy: str = Field(min_length=1)
    cadence: str = Field(min_length=1)
    retrospective: bool = False


class PredictionResponse(BaseModel):
    """Per-cycle response preserving the established prediction contract."""

    unit_id: int
    cycle: int
    horizon: int
    risk_score: float | None
    survival_score: float | None
    health_score: float | None
    alert_level: str | None
    prediction_status: str
    input_validity: str
    telemetry_stale: bool
    model_name: str
    model_version: str
    anomaly_score: float | None = None
    disagreement: float | None = None


class OptionsResponse(BaseModel):
    """Selections currently supported by frozen local artifacts."""

    unit_ids: list[int]
    horizons: list[int]
    models: list[str]
    telemetry_policies: list[str]
    cadences: list[str]


class HealthResponse(BaseModel):
    status: str


class UnitResponse(BaseModel):
    unit_id: int
    first_cycle: int
    last_cycle: int
    prediction_cycles: int


class TrajectoryResponse(BaseModel):
    unit_id: int
    horizon: int
    model: str
    telemetry_policy: str
    cadence: str
    predictions: list[PredictionResponse]


class ScenarioResponse(BaseModel):
    trajectory: list[dict[str, Any]]
    summary: dict[str, Any]
    assurance: dict[str, Any]
    model_comparison: list[dict[str, Any]]
    telemetry_comparison: list[dict[str, Any]]


class StoredPredictionResponse(BaseModel):
    id: int
    unit_id: int
    cycle: int
    horizon: int
    model_name: str
    model_version: str
    telemetry_policy: str
    cadence: str
    risk_score: float | None
    survival_score: float | None
    health_score: float | None
    prediction_status: str
    input_validity: str
    telemetry_stale: bool
    created_at: datetime


class AlertResponse(BaseModel):
    id: int
    unit_id: int
    cycle: int
    horizon: int
    alert_level: str
    risk_score: float | None
    created_at: datetime
