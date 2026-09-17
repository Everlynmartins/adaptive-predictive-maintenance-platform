"""Auditable two-parameter population Weibull baseline.

The model uses age only at prediction time. Sensors are deliberately rejected.
Its likelihood accepts right-censoring indicators for future datasets, although
the FD001 internal training execution contains observed events only.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from math import exp, expm1, isfinite, log
from pathlib import Path
from typing import Mapping, Self, Sequence

import numpy as np

from predictive_maintenance.core.records import FeatureRecord, RiskPrediction, TargetRecord
from predictive_maintenance.models.interfaces import RiskModel


ARTIFACT_SCHEMA = "predictive-maintenance.weibull-2p.v1"


@dataclass(frozen=True)
class WeibullFitConfig:
    model_name: str = "weibull_2p_population_age"
    model_version: str = "1.0.0"

    def __post_init__(self) -> None:
        for name in ("model_name", "model_version"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} must be a non-empty string")


class Weibull2Parameter(RiskModel):
    """Two-parameter Weibull MLE with a fixed zero location."""

    def __init__(self, config: WeibullFitConfig | None = None) -> None:
        self.config = config or WeibullFitConfig()
        self.beta: float | None = None
        self.eta: float | None = None
        self.n_observations = 0
        self.n_events = 0
        self.log_likelihood: float | None = None
        self.training_data_manifest: dict[str, object] = {}

    @property
    def is_fitted(self) -> bool:
        return self.beta is not None and self.eta is not None

    def fit(
        self,
        features: Sequence[FeatureRecord],
        targets: Sequence[TargetRecord] | None = None,
    ) -> Self:
        """Fit one lifetime target per unit using no feature values.

        Target values must contain ``event_time`` and may contain
        ``event_observed`` (default 1). Feature records are identity carriers;
        any value, including a sensor, is rejected.
        """
        if targets is None or not targets or len(features) != len(targets):
            raise ValueError("fit requires aligned non-empty lifetime targets")
        durations: list[float] = []
        events: list[bool] = []
        unit_ids: list[str] = []
        for feature, target in zip(features, targets, strict=True):
            self._validate_age_input(feature)
            if (feature.unit_id, feature.cycle) != (target.unit_id, target.cycle):
                raise ValueError("features and lifetime targets must align by key")
            if "event_time" not in target.values:
                raise ValueError("lifetime target requires event_time")
            extra = set(target.values) - {"event_time", "event_observed"}
            if extra:
                raise ValueError(f"unsupported lifetime target fields: {sorted(extra)}")
            durations.append(float(target.values["event_time"]))
            events.append(_event_flag(target.values.get("event_observed", 1)))
            unit_ids.append(target.unit_id)
        return self.fit_lifetimes(durations, events, unit_ids=unit_ids)

    def fit_lifetimes(
        self,
        durations: Sequence[float],
        event_observed: Sequence[bool | int] | None = None,
        *,
        unit_ids: Sequence[str] | None = None,
        training_data_manifest: Mapping[str, object] | None = None,
    ) -> Self:
        times, events = _validated_lifetimes(durations, event_observed)
        if unit_ids is not None:
            if len(unit_ids) != len(times) or len(set(unit_ids)) != len(unit_ids):
                raise ValueError("unit_ids must be unique and align with lifetimes")
            if any(not isinstance(value, str) or not value.strip() for value in unit_ids):
                raise ValueError("unit_ids must be non-empty strings")
        beta, eta = maximum_likelihood_estimate(times, events)
        self.beta = beta
        self.eta = eta
        self.n_observations = int(len(times))
        self.n_events = int(events.sum())
        self.log_likelihood = weibull_log_likelihood(times, events, beta, eta)
        self.training_data_manifest = dict(training_data_manifest or {})
        return self

    def density(self, time: float | Sequence[float]) -> float | np.ndarray:
        beta, eta = self._parameters()
        values, scalar = _validated_time(time)
        out = np.empty_like(values)
        positive = values > 0
        if beta > 1:
            out[~positive] = 0.0
        elif beta == 1:
            out[~positive] = 1.0 / eta
        else:
            out[~positive] = np.inf
        with np.errstate(over="ignore", under="ignore", invalid="ignore"):
            z = values[positive] / eta
            log_density = log(beta / eta) + (beta - 1.0) * np.log(z) - np.power(z, beta)
            out[positive] = np.exp(log_density)
        return _restore(out, scalar)

    def cumulative_distribution(self, time: float | Sequence[float]) -> float | np.ndarray:
        cumulative_hazard = np.asarray(self.cumulative_hazard(time), dtype=float)
        out = -np.expm1(-cumulative_hazard)
        return _restore(out, np.asarray(time).ndim == 0)

    def survival(self, time: float | Sequence[float]) -> float | np.ndarray:
        cumulative_hazard = np.asarray(self.cumulative_hazard(time), dtype=float)
        out = np.exp(-cumulative_hazard)
        return _restore(out, np.asarray(time).ndim == 0)

    def hazard(self, time: float | Sequence[float]) -> float | np.ndarray:
        beta, eta = self._parameters()
        values, scalar = _validated_time(time)
        out = np.empty_like(values)
        positive = values > 0
        if beta > 1:
            out[~positive] = 0.0
        elif beta == 1:
            out[~positive] = 1.0 / eta
        else:
            out[~positive] = np.inf
        with np.errstate(over="ignore", under="ignore"):
            out[positive] = (beta / eta) * np.power(values[positive] / eta, beta - 1.0)
        return _restore(out, scalar)

    def cumulative_hazard(self, time: float | Sequence[float]) -> float | np.ndarray:
        beta, eta = self._parameters()
        values, scalar = _validated_time(time)
        with np.errstate(over="ignore"):
            out = np.power(values / eta, beta)
        return _restore(out, scalar)

    def conditional_risk(self, age: float, horizon: float) -> float:
        """Return 1-S(age+horizon)/S(age), evaluated stably."""
        beta, eta = self._parameters()
        if isinstance(age, bool) or not isinstance(age, (int, float)) or not isfinite(age) or age < 0:
            raise ValueError("age must be a finite non-negative number")
        if (isinstance(horizon, bool) or not isinstance(horizon, (int, float))
                or not isfinite(horizon) or horizon < 0):
            raise ValueError("horizon must be a finite non-negative number")
        delta = ((age + horizon) / eta) ** beta - (age / eta) ** beta
        return min(1.0, max(0.0, -expm1(-delta)))

    def predict_risk(
        self, features: Sequence[FeatureRecord], *, horizon: int,
    ) -> list[RiskPrediction]:
        self._parameters()
        if type(horizon) is not int or horizon <= 0:
            raise ValueError("prediction horizon must be a positive integer cycle count")
        output = []
        for feature in features:
            self._validate_age_input(feature)
            output.append(RiskPrediction(
                unit_id=feature.unit_id,
                cycle=feature.cycle,
                horizon=horizon,
                risk_score=self.conditional_risk(feature.cycle, horizon),
                model_name=self.config.model_name,
                model_version=self.config.model_version,
                prediction_status="available",
                input_validity="valid",
                explanation="Population age-only Weibull 2P baseline; no sensors used.",
            ))
        return output

    def save(self, path: Path) -> None:
        beta, eta = self._parameters()
        payload = {
            "artifact_schema": ARTIFACT_SCHEMA,
            "model_name": self.config.model_name,
            "model_version": self.config.model_version,
            "parameters": {"beta": beta, "eta": eta},
            "fit": {
                "n_observations": self.n_observations,
                "n_events": self.n_events,
                "log_likelihood": self.log_likelihood,
                "location": 0.0,
                "estimation": "maximum_likelihood",
            },
            "training_data_manifest": self.training_data_manifest,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False,
                                   allow_nan=False) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Self:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("artifact_schema") != ARTIFACT_SCHEMA:
            raise ValueError("unsupported Weibull artifact schema")
        expected = {"artifact_schema", "model_name", "model_version", "parameters",
                    "fit", "training_data_manifest"}
        if set(payload) != expected:
            raise ValueError("unexpected or missing Weibull artifact fields")
        model = cls(WeibullFitConfig(payload["model_name"], payload["model_version"]))
        parameters = payload["parameters"]
        if set(parameters) != {"beta", "eta"}:
            raise ValueError("Weibull artifact must contain beta and eta only")
        beta, eta = float(parameters["beta"]), float(parameters["eta"])
        if not isfinite(beta) or not isfinite(eta) or beta <= 0 or eta <= 0:
            raise ValueError("invalid Weibull parameters in artifact")
        fit = payload["fit"]
        if fit.get("location") != 0.0 or fit.get("estimation") != "maximum_likelihood":
            raise ValueError("artifact is not a two-parameter maximum-likelihood Weibull")
        model.beta, model.eta = beta, eta
        model.n_observations = int(fit["n_observations"])
        model.n_events = int(fit["n_events"])
        model.log_likelihood = float(fit["log_likelihood"])
        if not 0 < model.n_events <= model.n_observations:
            raise ValueError("invalid event counts in artifact")
        model.training_data_manifest = dict(payload["training_data_manifest"])
        return model

    @staticmethod
    def artifact_hash(path: Path) -> str:
        return sha256(path.read_bytes()).hexdigest()

    def _parameters(self) -> tuple[float, float]:
        if not self.is_fitted:
            raise RuntimeError("Weibull model must be fitted or loaded first")
        return float(self.beta), float(self.eta)

    @staticmethod
    def _validate_age_input(feature: FeatureRecord) -> None:
        if not isinstance(feature, FeatureRecord):
            raise TypeError("Weibull input must be a FeatureRecord")
        if not isinstance(feature.unit_id, str) or not feature.unit_id.strip():
            raise ValueError("unit_id must be a non-empty string")
        if type(feature.cycle) is not int or feature.cycle <= 0:
            raise ValueError("cycle must be a positive integer age")
        if feature.values:
            raise ValueError("age-only Weibull input must not contain feature or sensor values")


def maximum_likelihood_estimate(
    durations: Sequence[float] | np.ndarray,
    event_observed: Sequence[bool | int] | np.ndarray | None = None,
) -> tuple[float, float]:
    """Return beta and eta for 2P Weibull under independent right censoring."""
    times, events = _validated_lifetimes(durations, event_observed)
    logs = np.log(times)
    event_logs = float(logs[events].sum())
    d = int(events.sum())

    def score(beta: float) -> float:
        scaled = beta * logs
        peak = float(scaled.max())
        weights = np.exp(scaled - peak)
        weighted_log = float(np.dot(weights, logs) / weights.sum())
        return d / beta + event_logs - d * weighted_log

    low, high = 1e-6, 1.0
    while score(high) > 0 and high < 1e6:
        high *= 2.0
    if score(low) <= 0 or score(high) >= 0:
        raise RuntimeError("could not bracket Weibull shape MLE")
    for _ in range(160):
        middle = (low + high) / 2.0
        if score(middle) > 0:
            low = middle
        else:
            high = middle
    beta = (low + high) / 2.0
    scaled = beta * logs
    peak = float(scaled.max())
    log_sum = peak + log(float(np.exp(scaled - peak).sum()))
    eta = exp((log_sum - log(d)) / beta)
    return float(beta), float(eta)


def weibull_log_likelihood(
    durations: Sequence[float] | np.ndarray,
    event_observed: Sequence[bool | int] | np.ndarray,
    beta: float,
    eta: float,
) -> float:
    times, events = _validated_lifetimes(durations, event_observed)
    if not isfinite(beta) or not isfinite(eta) or beta <= 0 or eta <= 0:
        raise ValueError("beta and eta must be finite and positive")
    logs = np.log(times)
    d = int(events.sum())
    with np.errstate(over="ignore"):
        cumulative = np.power(times / eta, beta)
    value = d * log(beta) - d * beta * log(eta)
    value += (beta - 1.0) * float(logs[events].sum()) - float(cumulative.sum())
    return float(value)


def _validated_lifetimes(
    durations: Sequence[float] | np.ndarray,
    event_observed: Sequence[bool | int] | np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray]:
    times = np.asarray(durations, dtype=float)
    if times.ndim != 1 or len(times) < 2 or not np.isfinite(times).all() or (times <= 0).any():
        raise ValueError("durations must contain at least two finite positive values")
    if event_observed is None:
        events = np.ones(len(times), dtype=bool)
    else:
        raw = list(event_observed)
        if len(raw) != len(times):
            raise ValueError("event indicators must align with durations")
        events = np.asarray([_event_flag(value) for value in raw], dtype=bool)
    if not events.any():
        raise ValueError("at least one observed event is required")
    return times, events


def _event_flag(value: object) -> bool:
    if value is True or value == 1:
        return True
    if value is False or value == 0:
        return False
    raise ValueError("event_observed must contain only boolean or 0/1 values")


def _validated_time(time: float | Sequence[float]) -> tuple[np.ndarray, bool]:
    values = np.atleast_1d(np.asarray(time, dtype=float))
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("time must be finite and non-negative")
    return values, np.asarray(time).ndim == 0


def _restore(values: np.ndarray, scalar: bool) -> float | np.ndarray:
    return float(values.reshape(-1)[0]) if scalar else values
