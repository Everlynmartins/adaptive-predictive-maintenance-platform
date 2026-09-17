"""Small SQLAlchemy Core persistence layer for simulated API traffic."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    create_engine,
    func,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import StaticPool


class PersistenceError(RuntimeError):
    """Persistence is configured but cannot fulfill the requested operation."""


metadata = MetaData()

telemetry_events = Table(
    "telemetry_events", metadata,
    Column("id", Integer, primary_key=True),
    Column("unit_id", Integer, nullable=False),
    Column("cycle", Integer, nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("telemetry_policy", String(64), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("input_validity", String(32), nullable=False),
    UniqueConstraint("unit_id", "cycle", "telemetry_policy", name="uq_telemetry_event"),
)

predictions = Table(
    "predictions", metadata,
    Column("id", Integer, primary_key=True),
    Column("unit_id", Integer, nullable=False),
    Column("cycle", Integer, nullable=False),
    Column("horizon", Integer, nullable=False),
    Column("model_name", String(128), nullable=False),
    Column("model_version", String(128), nullable=False),
    Column("telemetry_policy", String(64), nullable=False),
    Column("cadence", String(64), nullable=False),
    Column("risk_score", Float, nullable=True),
    Column("survival_score", Float, nullable=True),
    Column("health_score", Float, nullable=True),
    Column("prediction_status", String(32), nullable=False),
    Column("input_validity", String(32), nullable=False),
    Column("telemetry_stale", Boolean, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint(
        "unit_id", "cycle", "horizon", "model_name", "model_version",
        "telemetry_policy", "cadence", name="uq_prediction_identity",
    ),
)

alerts = Table(
    "alerts", metadata,
    Column("id", Integer, primary_key=True),
    Column("unit_id", Integer, nullable=False),
    Column("cycle", Integer, nullable=False),
    Column("horizon", Integer, nullable=False),
    Column("alert_level", String(32), nullable=False),
    Column("risk_score", Float, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("unit_id", "cycle", "horizon", "alert_level", name="uq_alert_identity"),
)


class PersistenceRepository:
    """Initialize and query the small schema without model or telemetry logic."""

    def __init__(self, database_url: str) -> None:
        try:
            options: dict[str, Any] = {"future": True}
            if database_url.startswith("sqlite"):
                options["connect_args"] = {"check_same_thread": False}
                if database_url in {"sqlite://", "sqlite:///:memory:"}:
                    options["poolclass"] = StaticPool
            self.engine: Engine = create_engine(database_url, **options)
            metadata.create_all(self.engine)
        except SQLAlchemyError as exc:
            raise PersistenceError("database initialization failed") from exc

    @staticmethod
    def _exists(connection: Any, table: Table, criteria: dict[str, Any]) -> bool:
        statement = select(table.c.id).filter_by(**criteria).limit(1)
        return connection.execute(statement).first() is not None

    def persist_prediction(self, request: Any, prediction: Any) -> None:
        """Persist one simulation message and its real API result atomically."""

        telemetry_key = {
            "unit_id": request.unit_id,
            "cycle": request.cycle,
            "telemetry_policy": request.telemetry_policy,
        }
        prediction_values = {
            "unit_id": prediction.unit_id,
            "cycle": prediction.cycle,
            "horizon": prediction.horizon,
            "model_name": prediction.model_name,
            "model_version": prediction.model_version,
            "telemetry_policy": request.telemetry_policy,
            "cadence": request.cadence,
            "risk_score": prediction.risk_score,
            "survival_score": prediction.survival_score,
            "health_score": prediction.health_score,
            "prediction_status": prediction.prediction_status,
            "input_validity": prediction.input_validity,
            "telemetry_stale": prediction.telemetry_stale,
        }
        prediction_key = {
            key: prediction_values[key] for key in (
                "unit_id", "cycle", "horizon", "model_name", "model_version",
                "telemetry_policy", "cadence",
            )
        }
        try:
            with self.engine.begin() as connection:
                if not self._exists(connection, telemetry_events, telemetry_key):
                    connection.execute(telemetry_events.insert().values(
                        **telemetry_key,
                        payload=request.model_dump(),
                        input_validity=prediction.input_validity,
                    ))
                if not self._exists(connection, predictions, prediction_key):
                    connection.execute(predictions.insert().values(**prediction_values))
                if prediction.alert_level in {"atenção", "alerta", "crítico"}:
                    alert_values = {
                        "unit_id": prediction.unit_id,
                        "cycle": prediction.cycle,
                        "horizon": prediction.horizon,
                        "alert_level": prediction.alert_level,
                        "risk_score": prediction.risk_score,
                    }
                    if not self._exists(connection, alerts, {
                        key: alert_values[key] for key in ("unit_id", "cycle", "horizon", "alert_level")
                    }):
                        connection.execute(alerts.insert().values(**alert_values))
        except SQLAlchemyError as exc:
            raise PersistenceError("database write failed") from exc

    def check_health(self) -> None:
        try:
            with self.engine.connect() as connection:
                connection.execute(select(1)).scalar_one()
        except SQLAlchemyError as exc:
            raise PersistenceError("database health check failed") from exc

    def list_predictions(
        self, unit_id: int | None = None, horizon: int | None = None, limit: int = 100,
    ) -> list[dict[str, Any]]:
        statement = select(predictions)
        if unit_id is not None:
            statement = statement.where(predictions.c.unit_id == unit_id)
        if horizon is not None:
            statement = statement.where(predictions.c.horizon == horizon)
        statement = statement.order_by(predictions.c.unit_id, predictions.c.cycle, predictions.c.created_at).limit(limit)
        return self._rows(statement)

    def list_alerts(
        self, unit_id: int | None = None, horizon: int | None = None, limit: int = 100,
    ) -> list[dict[str, Any]]:
        statement = select(alerts)
        if unit_id is not None:
            statement = statement.where(alerts.c.unit_id == unit_id)
        if horizon is not None:
            statement = statement.where(alerts.c.horizon == horizon)
        statement = statement.order_by(alerts.c.unit_id, alerts.c.cycle, alerts.c.created_at).limit(limit)
        return self._rows(statement)

    def _rows(self, statement: Any) -> list[dict[str, Any]]:
        try:
            with self.engine.connect() as connection:
                return [dict(row._mapping) for row in connection.execute(statement)]
        except SQLAlchemyError as exc:
            raise PersistenceError("database query failed") from exc
