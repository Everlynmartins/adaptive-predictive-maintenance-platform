"""FastAPI adapter over the read-only local application service."""

from __future__ import annotations

from functools import lru_cache
import json
import math
import os
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query

from predictive_maintenance.api.schemas import (
    HealthResponse,
    AlertResponse,
    OptionsResponse,
    PredictionResponse,
    PredictRequest,
    ScenarioRequest,
    ScenarioResponse,
    TrajectoryResponse,
    UnitResponse,
    StoredPredictionResponse,
)
from predictive_maintenance.api.persistence import PersistenceError, PersistenceRepository
from predictive_maintenance.application.local_service import (
    ApplicationResult,
    ApplicationSelection,
    LocalApplicationError,
    LocalApplicationService,
)


def _resolve_project_root() -> Path:
    """Resolve the application root for both a checkout and an installed image."""

    configured = os.environ.get("PREDICTIVE_MAINTENANCE_PROJECT_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()

    package_root = Path(__file__).resolve().parents[3]
    for candidate in (Path.cwd(), package_root):
        if (candidate / "configs" / "local_app.toml").is_file():
            return candidate.resolve()
    # Let LocalApplicationService report the missing configuration explicitly.
    return Path.cwd().resolve()

app = FastAPI(
    title="Adaptive Predictive Maintenance Platform API",
    version="0.16.0",
    description="Read-only local API over frozen FD001 application artifacts.",
)


@lru_cache(maxsize=1)
def get_service() -> LocalApplicationService:
    """Create the existing application facade once; endpoints never load models."""

    return LocalApplicationService(project_root=_resolve_project_root())


@lru_cache(maxsize=4)
def _repository_for_url(database_url: str) -> PersistenceRepository:
    return PersistenceRepository(database_url)


def get_repository() -> PersistenceRepository | None:
    """Enable persistence only when DATABASE_URL is explicitly configured."""

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        return None
    try:
        return _repository_for_url(database_url)
    except PersistenceError as exc:
        raise HTTPException(status_code=503, detail="persistence is unavailable") from exc


def _unsupported(detail: str) -> HTTPException:
    return HTTPException(status_code=422, detail=detail)


def _validate_request_options(service: LocalApplicationService, request: Any) -> None:
    if request.unit_id not in service.available_units:
        raise HTTPException(status_code=404, detail="unit_id was not found in validation artifacts")
    if request.horizon not in service.horizons:
        raise _unsupported(f"horizon must be one of {list(service.horizons)}")
    if request.model not in service.models:
        raise _unsupported(f"model must be one of {list(service.models)}")
    if request.telemetry_policy not in service.policies:
        raise _unsupported(f"telemetry_policy must be one of {list(service.policies)}")
    if request.cadence not in service.inference_cadences:
        raise _unsupported(f"cadence must be one of {list(service.inference_cadences)}")


def _run(service: LocalApplicationService, request: Any) -> ApplicationResult:
    _validate_request_options(service, request)
    try:
        return service.run(ApplicationSelection(
            unit_id=request.unit_id,
            horizon=request.horizon,
            model=request.model,
            telemetry_policy=request.telemetry_policy,
            inference_cadence=request.cadence,
            retrospective=bool(getattr(request, "retrospective", False)),
        ))
    except ValueError as exc:
        raise _unsupported(str(exc)) from exc
    except LocalApplicationError as exc:
        raise HTTPException(status_code=503, detail="local prediction service is unavailable") from exc


def _optional_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _prediction_from_row(row: Any, result: ApplicationResult) -> PredictionResponse:
    return PredictionResponse(
        unit_id=int(row.unit_id),
        cycle=int(row.cycle),
        horizon=int(row.horizon),
        risk_score=_optional_float(row.risk_score),
        survival_score=_optional_float(row.survival_score),
        health_score=_optional_float(row.health_score),
        alert_level=str(row.alert_level) if row.alert_level is not None else None,
        prediction_status=str(row.prediction_status),
        input_validity=str(row.input_validity),
        telemetry_stale=bool(row.telemetry_stale),
        model_name=str(row.model),
        model_version=str(result.assurance["model_version"]),
        anomaly_score=_optional_float(row.anomaly_score),
        disagreement=_optional_float(row.disagreement),
    )


@app.get("/health", response_model=HealthResponse)
def health(
    service: LocalApplicationService = Depends(get_service),
    repository: PersistenceRepository | None = Depends(get_repository),
) -> HealthResponse:
    """Confirm that the read-only local application layer is available."""

    try:
        _ = service.available_units
        if repository is not None:
            repository.check_health()
    except (LocalApplicationError, PersistenceError) as exc:
        raise HTTPException(status_code=503, detail="local application is unavailable") from exc
    return HealthResponse(status="available")


@app.get("/api/v1/options", response_model=OptionsResponse)
def options(service: LocalApplicationService = Depends(get_service)) -> OptionsResponse:
    return OptionsResponse(
        unit_ids=list(service.available_units),
        horizons=list(service.horizons),
        models=list(service.models),
        telemetry_policies=list(service.policies),
        cadences=list(service.inference_cadences),
    )


@app.post("/api/v1/predict", response_model=PredictionResponse)
def predict(
    request: PredictRequest,
    service: LocalApplicationService = Depends(get_service),
    repository: PersistenceRepository | None = Depends(get_repository),
) -> PredictionResponse:
    """Return one frozen per-cycle prediction, including explicit unavailable states."""

    result = _run(service, request)
    rows = result.trajectory.loc[result.trajectory.cycle.eq(request.cycle)]
    if rows.empty:
        raise _unsupported("cycle is outside the available trajectory for this unit")
    prediction = _prediction_from_row(rows.iloc[0], result)
    if repository is not None:
        try:
            repository.persist_prediction(request, prediction)
        except PersistenceError as exc:
            raise HTTPException(status_code=503, detail="prediction persistence is unavailable") from exc
    return prediction


def _records(frame: Any) -> list[dict[str, Any]]:
    return json.loads(frame.to_json(orient="records"))


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(
        value,
        default=lambda item: item.item() if hasattr(item, "item") else str(item),
        allow_nan=False,
    ))


@app.post("/api/v1/scenario", response_model=ScenarioResponse)
def scenario(
    request: ScenarioRequest,
    service: LocalApplicationService = Depends(get_service),
) -> ScenarioResponse:
    result = _run(service, request)
    return ScenarioResponse(
        trajectory=_records(result.trajectory),
        summary=_json_safe(result.summary),
        assurance=_json_safe(result.assurance),
        model_comparison=_records(result.model_comparison),
        telemetry_comparison=_records(result.telemetry_comparison),
    )


def _persistence_or_503(repository: PersistenceRepository | None) -> PersistenceRepository:
    if repository is None:
        raise HTTPException(status_code=503, detail="persistence is disabled")
    return repository


@app.get("/api/v1/predictions", response_model=list[StoredPredictionResponse])
def historical_predictions(
    unit_id: int | None = Query(None, gt=0),
    horizon: int | None = Query(None, gt=0),
    limit: int = Query(100, ge=1, le=200),
    repository: PersistenceRepository | None = Depends(get_repository),
) -> list[dict[str, Any]]:
    try:
        return _persistence_or_503(repository).list_predictions(unit_id, horizon, limit)
    except PersistenceError as exc:
        raise HTTPException(status_code=503, detail="prediction history is unavailable") from exc


@app.get("/api/v1/alerts", response_model=list[AlertResponse])
def historical_alerts(
    unit_id: int | None = Query(None, gt=0),
    horizon: int | None = Query(None, gt=0),
    limit: int = Query(100, ge=1, le=200),
    repository: PersistenceRepository | None = Depends(get_repository),
) -> list[dict[str, Any]]:
    try:
        return _persistence_or_503(repository).list_alerts(unit_id, horizon, limit)
    except PersistenceError as exc:
        raise HTTPException(status_code=503, detail="alert history is unavailable") from exc


@app.get("/api/v1/units/{unit_id}", response_model=UnitResponse)
def unit(
    unit_id: int,
    horizon: int = Query(30),
    model: str = Query("fusion"),
    telemetry_policy: str = Query("full"),
    cadence: str = Query("each_cycle"),
    service: LocalApplicationService = Depends(get_service),
) -> UnitResponse:
    request = PredictRequest(
        unit_id=unit_id, cycle=1, horizon=horizon, model=model,
        telemetry_policy=telemetry_policy, cadence=cadence,
    )
    result = _run(service, request)
    trajectory = result.trajectory
    return UnitResponse(
        unit_id=unit_id,
        first_cycle=int(trajectory.cycle.min()),
        last_cycle=int(trajectory.cycle.max()),
        prediction_cycles=len(trajectory),
    )


@app.get("/api/v1/units/{unit_id}/trajectory", response_model=TrajectoryResponse)
def trajectory(
    unit_id: int,
    horizon: int = Query(30),
    model: str = Query("fusion"),
    telemetry_policy: str = Query("full"),
    cadence: str = Query("each_cycle"),
    service: LocalApplicationService = Depends(get_service),
) -> TrajectoryResponse:
    request = PredictRequest(
        unit_id=unit_id, cycle=1, horizon=horizon, model=model,
        telemetry_policy=telemetry_policy, cadence=cadence,
    )
    result = _run(service, request)
    return TrajectoryResponse(
        unit_id=unit_id,
        horizon=horizon,
        model=model,
        telemetry_policy=telemetry_policy,
        cadence=cadence,
        predictions=[_prediction_from_row(row, result) for row in result.trajectory.itertuples(index=False)],
    )


def main() -> None:
    """Run the API without requiring the console-script entry point."""

    import uvicorn

    uvicorn.run("predictive_maintenance.api.main:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
