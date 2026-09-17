"""Library-neutral records shared by the internal interfaces."""

from dataclasses import dataclass, field
from math import isclose, isfinite
from numbers import Real
from types import MappingProxyType
from typing import Literal, Mapping

from predictive_maintenance.core.causality import validate_feature_names


@dataclass(frozen=True)
class TelemetryRecord:
    """One observation. Sensor names and operating settings belong in values."""

    unit_id: str
    cycle: int
    values: Mapping[str, float]


@dataclass(frozen=True)
class FeatureRecord:
    """One feature vector, identified by the last observable cycle."""

    unit_id: str
    cycle: int
    values: Mapping[str, float]

    def __post_init__(self) -> None:
        values = dict(self.values)
        validate_feature_names(values)
        object.__setattr__(self, "values", MappingProxyType(values))


@dataclass(frozen=True)
class TargetRecord:
    """Named targets, such as future RUL; meaning and units are external metadata."""

    unit_id: str
    cycle: int
    values: Mapping[str, float]


@dataclass(frozen=True, kw_only=True)
class RiskPrediction:
    """Horizon-conditioned probability; see docs/prediction_contract.md.

    Scores are absent when prediction is unavailable or the unit is terminal.
    Validity is explicitly supplied by the input adapter, not inferred here.
    """

    unit_id: str
    cycle: int
    horizon: int
    risk_score: float | None
    model_name: str
    model_version: str
    prediction_status: Literal["available", "unavailable", "not_operational"]
    input_validity: Literal["valid", "invalid", "stale", "unknown"]
    health_score: float | None = None
    survival_score: float | None = field(init=False)
    uncertainty: Mapping[str, float] | None = None
    anomaly_score: float | None = None
    explanation: str | None = None
    disagreement: float | None = None

    def __post_init__(self) -> None:
        for name in ("unit_id", "model_name", "model_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        for name in ("cycle", "horizon"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.prediction_status not in {"available", "unavailable", "not_operational"}:
            raise ValueError("unknown prediction_status")
        if self.input_validity not in {"valid", "invalid", "stale", "unknown"}:
            raise ValueError("unknown input_validity")
        if self.prediction_status == "available":
            if self.input_validity != "valid":
                raise ValueError("available prediction requires valid input")
            _finite_score("risk_score", self.risk_score, bounded=True)
            survival = 1.0 - self.risk_score
            health = 100.0 * survival
            if self.health_score is not None:
                _finite_score("health_score", self.health_score)
                if not isclose(self.health_score, health, rel_tol=0, abs_tol=1e-10):
                    raise ValueError("health_score must equal 100 * (1 - risk_score)")
        else:
            if self.risk_score is not None or self.health_score is not None:
                raise ValueError("non-available prediction must not carry probability or health")
            if not isinstance(self.explanation, str) or not self.explanation.strip():
                raise ValueError("non-available prediction requires an explanation")
            survival = health = None
        object.__setattr__(self, "survival_score", survival)
        object.__setattr__(self, "health_score", health)
        for name in ("anomaly_score", "disagreement"):
            value = getattr(self, name)
            if value is not None:
                _finite_score(name, value, bounded=name == "disagreement")


@dataclass(frozen=True, kw_only=True)
class FusionPrediction:
    """Probability produced by a fusion layer with explicit service status.

    ``degraded`` means that a declared fallback produced a probability from a
    valid input while one or more components were unavailable. ``unavailable``
    never carries an implicit zero-risk value.
    """

    unit_id: str
    cycle: int
    horizon: int
    risk_score: float | None
    model_name: str
    model_version: str
    prediction_status: Literal["valid", "degraded", "unavailable"]
    input_validity: Literal["valid", "invalid", "stale", "unknown"]
    component_status: Mapping[str, str]
    disagreement: float | None = None
    anomaly_score: float | None = None
    explanation: str | None = None
    health_score: float | None = None
    survival_score: float | None = field(init=False)

    def __post_init__(self) -> None:
        for name in ("unit_id", "model_name", "model_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        for name in ("cycle", "horizon"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.prediction_status not in {"valid", "degraded", "unavailable"}:
            raise ValueError("unknown fusion prediction_status")
        if self.input_validity not in {"valid", "invalid", "stale", "unknown"}:
            raise ValueError("unknown input_validity")
        statuses = dict(self.component_status)
        if not statuses or any(not str(name).strip() or not str(value).strip()
                               for name, value in statuses.items()):
            raise ValueError("component_status must identify every declared component")
        object.__setattr__(self, "component_status", MappingProxyType(statuses))
        if self.prediction_status in {"valid", "degraded"}:
            if self.input_validity != "valid":
                raise ValueError("a fusion probability requires valid input")
            _finite_score("risk_score", self.risk_score, bounded=True)
            survival = 1.0 - self.risk_score
            health = 100.0 * survival
            if self.health_score is not None:
                _finite_score("health_score", self.health_score)
                if not isclose(self.health_score, health, rel_tol=0, abs_tol=1e-10):
                    raise ValueError("health_score must equal 100 * (1 - risk_score)")
        else:
            if self.risk_score is not None or self.health_score is not None:
                raise ValueError("unavailable fusion must not carry probability or health")
            if not isinstance(self.explanation, str) or not self.explanation.strip():
                raise ValueError("unavailable fusion requires an explanation")
            survival = health = None
        object.__setattr__(self, "survival_score", survival)
        object.__setattr__(self, "health_score", health)
        if self.disagreement is not None:
            _finite_score("disagreement", self.disagreement, bounded=True)
        if self.anomaly_score is not None:
            _finite_score("anomaly_score", self.anomaly_score)


def _finite_score(name: str, value: object, *, bounded: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value):
        raise ValueError(f"{name} must be a finite real number")
    if bounded and not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be within [0, 1]")


@dataclass(frozen=True)
class AnomalyPrediction:
    """Detector output; its score scale must be declared by the implementation."""

    unit_id: str
    cycle: int
    anomaly_score: float | None
    model_name: str
    model_version: str
    prediction_status: Literal["available", "unavailable"] = "available"
    input_validity: Literal["valid", "invalid", "stale", "unknown"] = "valid"
    explanation: str | None = None

    def __post_init__(self) -> None:
        for name in ("unit_id", "model_name", "model_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if type(self.cycle) is not int or self.cycle <= 0:
            raise ValueError("cycle must be a positive integer")
        if self.prediction_status not in {"available", "unavailable"}:
            raise ValueError("unknown anomaly prediction_status")
        if self.input_validity not in {"valid", "invalid", "stale", "unknown"}:
            raise ValueError("unknown anomaly input_validity")
        if self.prediction_status == "available":
            if self.input_validity != "valid":
                raise ValueError("available anomaly prediction requires valid input")
            _finite_score("anomaly_score", self.anomaly_score)
        else:
            if self.anomaly_score is not None:
                raise ValueError("unavailable anomaly prediction must not carry a score")
            if not isinstance(self.explanation, str) or not self.explanation.strip():
                raise ValueError("unavailable anomaly prediction requires an explanation")
