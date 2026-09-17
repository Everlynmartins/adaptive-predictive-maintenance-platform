"""Frozen-origin logistic landmark hazard; outcomes never enter covariates."""
from dataclasses import dataclass, asdict
from pathlib import Path
import re

import joblib
import numpy as np
from scipy.optimize import minimize
from scipy.special import expit
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from predictive_maintenance.core.causality import validate_feature_names
from predictive_maintenance.core.records import RiskPrediction
from predictive_maintenance.models.interfaces import RiskModel


@dataclass(frozen=True)
class HazardConfig:
    max_horizon: int = 30
    regularization: float = 1.0
    max_iterations: int = 1500
    tolerance: float = 1e-8
    model_version: str = "1.0.0"

    def __post_init__(self):
        for v in (self.max_horizon, self.max_iterations):
            if type(v) is not int or v < 1:
                raise ValueError("positive integer configuration required")
        if not np.isfinite([self.regularization, self.tolerance]).all() or min(self.regularization, self.tolerance) <= 0:
            raise ValueError("positive finite regularization and tolerance required")
        if not self.model_version.strip():
            raise ValueError("model version required")


def landmark_masks(features, targets, max_horizon):
    """Inclusive event/censor endpoint, with unknown/post-event steps masked out.

    Targets carry observed_end and event_observed, aligned to each origin key.
    Repeated endpoints for a unit must agree. A censor endpoint gives known
    non-events through C; an event endpoint gives one positive at T-t.
    """
    if type(max_horizon) is not int or max_horizon < 1:
        raise ValueError("max_horizon must be positive integer")
    if not features or targets is None or len(features) != len(targets):
        raise ValueError("aligned nonempty origins and outcomes required")
    keys, outcomes, remaining, events = set(), {}, [], []
    for f, y in zip(features, targets, strict=True):
        key = (f.unit_id, f.cycle)
        if key in keys or key != (y.unit_id, y.cycle):
            raise ValueError("duplicate or misaligned origin")
        keys.add(key)
        if set(y.values) != {"observed_end", "event_observed"}:
            raise ValueError("outcome schema mismatch")
        end, event = y.values["observed_end"], y.values["event_observed"]
        if not np.isfinite([end, event]).all() or end != int(end) or event not in (0, 1):
            raise ValueError("invalid outcome endpoint or event flag")
        if end < f.cycle or (event and end == f.cycle):
            raise ValueError("origin must precede event and not exceed followup")
        outcome = (int(end), bool(event))
        if f.unit_id in outcomes and outcomes[f.unit_id] != outcome:
            raise ValueError("inconsistent outcome within unit")
        outcomes[f.unit_id] = outcome
        remaining.append(end - f.cycle)
        events.append(event)
    k = np.arange(1, max_horizon + 1)
    remaining = np.asarray(remaining)[:, None]
    at_risk = k <= remaining
    labels = (k == remaining) & np.asarray(events, dtype=bool)[:, None]
    return at_risk, labels


def logistic_objective(theta, z, k, at_risk, labels, regularization):
    """Exact expanded Bernoulli loss/gradient without repeating 324 covariates.

    Equal weight per observed landmark-step. Correlated landmarks form a
    composite likelihood; no independence-based standard errors are reported.
    """
    logits = (z @ theta[:-2] + theta[-1])[:, None] + k * theta[-2]
    residual = (expit(logits) - labels) * at_risk
    loss = ((np.logaddexp(0, logits) - labels * logits) * at_risk).sum()
    loss += 0.5 * regularization * np.dot(theta[:-1], theta[:-1])
    gradient = np.concatenate((z.T @ residual.sum(axis=1),
                               [np.sum(residual * k), residual.sum()]))
    gradient[:-1] += regularization * theta[:-1]
    return float(loss), gradient


class DiscreteHazardRiskModel(RiskModel):
    model_name = "discrete_hazard_logistic"
    artifact_schema = "discrete-hazard/v1"

    def __init__(self, feature_names, config=None):
        self.config = config or HazardConfig()
        self.feature_names = tuple(feature_names)
        validate_feature_names(self.feature_names)
        # Strict causal-generator vocabulary; arbitrary aliases are not accepted.
        pattern = r"(?:sensor_\d+|setting_\d+)__(?:current|delta|relative_delta|cumulative_abs_change|(?:mean|std|min|max|slope)_w\d+)"
        if len(set(self.feature_names)) != len(self.feature_names) or any(
            n != "age_cycle" and not re.fullmatch(pattern, n) for n in self.feature_names
        ):
            raise ValueError("features must use reviewed causal-generator vocabulary")
        if "age_cycle" not in self.feature_names:
            raise ValueError("age_cycle is required")
        self.scaler = StandardScaler()
        self.theta = None

    def _row(self, record):
        if not isinstance(record.unit_id, str) or not record.unit_id.strip() or type(record.cycle) is not int or record.cycle < 1:
            raise ValueError("invalid origin identity")
        if set(record.values) != set(self.feature_names):
            raise ValueError("feature schema mismatch")
        values = np.asarray([record.values[n] for n in self.feature_names], dtype=float)
        if not np.isfinite(values).all() or record.values["age_cycle"] != record.cycle:
            raise ValueError("nonfinite input or age inconsistent with origin")
        return values

    def fit(self, features, targets=None):
        self.theta = None  # A failed refit must not expose old weights with a new scaler.
        at_risk, labels = landmark_masks(features, targets, self.config.max_horizon)
        matrix = np.asarray([self._row(f) for f in features])
        eligible = at_risk.any(axis=1)
        if not labels.any() or np.sum(at_risk) == np.sum(labels):
            raise ValueError("observed risk sets require events and non-events")
        z = self.scaler.fit_transform(matrix[eligible])
        a, y = at_risk[eligible], labels[eligible]
        k = np.arange(1, self.config.max_horizon + 1) / self.config.max_horizon
        initial = np.zeros(z.shape[1] + 2)
        rate = y.sum() / a.sum()
        initial[-1] = np.log(rate / (1-rate))
        with threadpool_limits(limits=2):
            result = minimize(logistic_objective, initial, args=(z, k, a, y, self.config.regularization),
                              jac=True, method="L-BFGS-B", options={"maxiter": self.config.max_iterations,
                              "ftol": self.config.tolerance, "gtol": self.config.tolerance})
        if not result.success or not np.isfinite(result.x).all():
            raise RuntimeError(f"hazard fit failed convergence: {result.message}")
        self.theta = result.x
        self.training_summary = {"origins": int(eligible.sum()), "landmark_steps": int(a.sum()),
            "event_steps": int(y.sum()), "units": len({f.unit_id for f in features}),
            "iterations": int(result.nit), "converged": bool(result.success),
            "objective": float(result.fun), "optimizer_message": str(result.message),
            "weighting": "equal observed landmark-step; no class balancing or resampling"}
        return self

    def predict_hazards(self, features, *, horizon):
        if self.theta is None:
            raise RuntimeError("model not fitted")
        if type(horizon) is not int or not 1 <= horizon <= self.config.max_horizon:
            raise ValueError("horizon outside trained support")
        if not features:
            return np.empty((0, horizon))
        z = self.scaler.transform(np.asarray([self._row(f) for f in features]))
        k = np.arange(1, horizon + 1) / self.config.max_horizon
        logits = (z @ self.theta[:-2] + self.theta[-1])[:, None] + k * self.theta[-2]
        hazards = expit(logits)
        if not np.isfinite(hazards).all() or ((hazards < 0) | (hazards > 1)).any():
            raise ValueError("invalid numerical hazard")
        return hazards

    def predict_risk(self, features, *, horizon):
        if self.theta is None:
            raise RuntimeError("model not fitted")
        # A malformed key/horizon cannot be represented by RiskPrediction: reject.
        if type(horizon) is not int or horizon < 1:
            raise ValueError("positive integer horizon required")
        output = []
        for f in features:
            try:
                hazards = self.predict_hazards([f], horizon=horizon)[0]
                risk = float(1 - np.prod(1-hazards))
                status, validity, reason = "available", "valid", None
            except (ValueError, TypeError, OverflowError) as exc:
                risk, status, validity, reason = None, "unavailable", "invalid", str(exc)
            output.append(RiskPrediction(unit_id=f.unit_id, cycle=f.cycle, horizon=horizon,
                risk_score=risk, model_name=self.model_name, model_version=self.config.model_version,
                prediction_status=status, input_validity=validity, explanation=reason))
        return output

    def save(self, path):
        if self.theta is None:
            raise RuntimeError("model not fitted")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"schema": self.artifact_schema, "configuration": asdict(self.config),
                     "feature_names": self.feature_names, "scaler": self.scaler,
                     "theta": self.theta, "training_summary": self.training_summary}, path)

    @classmethod
    def load(cls, path):
        payload = joblib.load(path)  # Trusted local files only (pickle format).
        if payload.get("schema") != cls.artifact_schema:
            raise ValueError("incompatible hazard artifact")
        model = cls(payload["feature_names"], HazardConfig(**payload["configuration"]))
        model.theta, model.scaler = payload["theta"], payload["scaler"]
        if model.theta.shape != (len(model.feature_names)+2,) or not np.isfinite(model.theta).all():
            raise ValueError("invalid coefficients")
        if model.scaler.n_features_in_ != len(model.feature_names):
            raise ValueError("incompatible scaler")
        if (not np.isfinite(model.scaler.mean_).all()
                or not np.isfinite(model.scaler.scale_).all()
                or (model.scaler.scale_ <= 0).any()):
            raise ValueError("invalid scaler state")
        model.training_summary = payload["training_summary"]
        return model
