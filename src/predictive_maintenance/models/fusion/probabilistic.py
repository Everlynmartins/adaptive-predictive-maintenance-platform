"""Leakage-controlled probability fusion, calibration and alert policy tools."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Literal, Mapping, Self, Sequence

import joblib
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from predictive_maintenance.core.records import FusionPrediction, RiskPrediction
from predictive_maintenance.models.fusion.interfaces import ModelFusion


RISK_COMPONENTS = (
    "risk_weibull",
    "risk_random_forest",
    "risk_xgboost",
    "risk_discrete_hazard",
)


@dataclass(frozen=True)
class StackingConfig:
    horizon: int
    model_name: str = "logistic_probability_stacking"
    model_version: str = "1.0.0"
    random_seed: int = 4501
    regularization_c: float = 1.0
    max_iterations: int = 1000
    risk_feature_names: tuple[str, ...] = RISK_COMPONENTS
    anomaly_feature_name: str | None = "anomaly_score"

    def __post_init__(self) -> None:
        if type(self.horizon) is not int or self.horizon <= 0:
            raise ValueError("horizon must be a positive integer")
        if not self.risk_feature_names or len(set(self.risk_feature_names)) != len(self.risk_feature_names):
            raise ValueError("risk_feature_names must be non-empty and unique")
        if not np.isfinite(self.regularization_c) or self.regularization_c <= 0:
            raise ValueError("regularization_c must be positive and finite")
        if type(self.max_iterations) is not int or self.max_iterations < 1:
            raise ValueError("max_iterations must be positive")


class SimpleProbabilityEnsemble(ModelFusion):
    """Arithmetic mean of available comparable probabilities only."""

    def __init__(self, *, minimum_components: int = 2,
                 model_name: str = "simple_probability_ensemble",
                 model_version: str = "1.0.0") -> None:
        if type(minimum_components) is not int or minimum_components < 1:
            raise ValueError("minimum_components must be positive")
        self.minimum_components = minimum_components
        self.model_name = model_name
        self.model_version = model_version

    def fuse(self, predictions: Sequence[Sequence[RiskPrediction]]) -> list[FusionPrediction]:
        if not predictions or any(not batch for batch in predictions):
            raise ValueError("fusion requires non-empty component batches")
        names = [batch[0].model_name for batch in predictions]
        if len(set(names)) != len(names):
            raise ValueError("component model names must be unique")
        maps: list[dict[tuple[str, int, int], RiskPrediction]] = []
        for name, batch in zip(names, predictions, strict=True):
            if any(item.model_name != name for item in batch):
                raise ValueError("one component batch mixes model names")
            mapping = {(item.unit_id, item.cycle, item.horizon): item for item in batch}
            if len(mapping) != len(batch):
                raise ValueError("duplicate prediction key within component")
            maps.append(mapping)
        keys = sorted(set().union(*(set(mapping) for mapping in maps)),
                      key=lambda key: (key[0], key[1], key[2]))
        output: list[FusionPrediction] = []
        for unit_id, cycle, horizon in keys:
            items = [mapping.get((unit_id, cycle, horizon)) for mapping in maps]
            statuses = {name: (item.prediction_status if item else "missing")
                        for name, item in zip(names, items, strict=True)}
            invalid = next((item.input_validity for item in items
                            if item is not None and item.input_validity != "valid"), None)
            available = [float(item.risk_score) for item in items
                         if item is not None and item.prediction_status == "available"
                         and item.input_validity == "valid"]
            if invalid is not None:
                output.append(FusionPrediction(
                    unit_id=unit_id, cycle=cycle, horizon=horizon, risk_score=None,
                    model_name=self.model_name, model_version=self.model_version,
                    prediction_status="unavailable", input_validity=invalid,
                    component_status=statuses,
                    explanation="at least one component reports non-valid input",
                ))
                continue
            if len(available) < self.minimum_components:
                output.append(FusionPrediction(
                    unit_id=unit_id, cycle=cycle, horizon=horizon, risk_score=None,
                    model_name=self.model_name, model_version=self.model_version,
                    prediction_status="unavailable", input_validity="valid",
                    component_status=statuses,
                    explanation="insufficient comparable probability components",
                ))
                continue
            status = "valid" if len(available) == len(items) else "degraded"
            output.append(FusionPrediction(
                unit_id=unit_id, cycle=cycle, horizon=horizon,
                risk_score=float(np.mean(available)), model_name=self.model_name,
                model_version=self.model_version, prediction_status=status,
                input_validity="valid", component_status=statuses,
                disagreement=float(max(available) - min(available)),
                explanation=(None if status == "valid"
                             else "fallback mean uses the available probability components"),
            ))
        return output


class LogisticStackingFusion:
    """Logistic meta-model over base probabilities and optional anomaly covariate."""

    artifact_schema = "predictive-maintenance.logistic-stacking.v1"

    def __init__(self, config: StackingConfig) -> None:
        self.config = config
        self.estimator = LogisticRegression(
            C=config.regularization_c, max_iter=config.max_iterations,
            random_state=config.random_seed, solver="lbfgs",
        )
        self._fitted = False

    @property
    def feature_names(self) -> tuple[str, ...]:
        extra = (() if self.config.anomaly_feature_name is None
                 else (self.config.anomaly_feature_name,))
        return (*self.config.risk_feature_names, *extra)

    def fit_frame(self, frame: pd.DataFrame) -> Self:
        if "partition" not in frame or not frame.partition.eq("train_oof").all():
            raise ValueError("stacking may be fitted only from train_oof predictions")
        matrix, labels = self._validated(frame, require_label=True)
        if len(np.unique(labels)) != 2:
            raise ValueError("stacking fit requires both target classes")
        self.estimator.fit(matrix, labels)
        self._fitted = True
        return self

    def predict_frame(self, frame: pd.DataFrame) -> np.ndarray:
        if not self._fitted:
            raise RuntimeError("stacking model must be fitted")
        matrix, _ = self._validated(frame, require_label=False)
        probability = self.estimator.predict_proba(matrix)[:, 1]
        if not np.isfinite(probability).all() or (probability < 0).any() or (probability > 1).any():
            raise RuntimeError("stacking estimator returned invalid probabilities")
        return probability

    def predict_record(self, *, unit_id: str, cycle: int,
                       base_probabilities: Mapping[str, float | None],
                       anomaly_score: float | None,
                       input_validity: Literal["valid", "invalid", "stale", "unknown"] = "valid",
                       calibrator: ProbabilityCalibrator | None = None) -> FusionPrediction:
        """Return explicit unavailable status when a required component is absent."""
        statuses = {name: ("available" if base_probabilities.get(name) is not None else "unavailable")
                    for name in self.config.risk_feature_names}
        if self.config.anomaly_feature_name is not None:
            statuses[self.config.anomaly_feature_name] = (
                "available" if anomaly_score is not None else "unavailable")
        missing = [name for name, status in statuses.items() if status != "available"]
        if input_validity != "valid" or missing:
            reason = (f"required fusion components unavailable: {missing}" if missing
                      else f"input validity is {input_validity}")
            return FusionPrediction(unit_id=unit_id, cycle=cycle,
                horizon=self.config.horizon, risk_score=None,
                model_name=self.config.model_name, model_version=self.config.model_version,
                prediction_status="unavailable", input_validity=input_validity,
                component_status=statuses, explanation=reason,
                anomaly_score=anomaly_score)
        row = {"unit_id": [int(unit_id)], "cycle": [cycle],
               "horizon": [self.config.horizon],
               **{name: [base_probabilities[name]] for name in self.config.risk_feature_names}}
        if self.config.anomaly_feature_name is not None:
            row[self.config.anomaly_feature_name] = [anomaly_score]
        probability = self.predict_frame(pd.DataFrame(row))
        if calibrator is not None:
            probability = calibrator.predict(probability)
        values = [float(base_probabilities[name]) for name in self.config.risk_feature_names]
        return FusionPrediction(unit_id=unit_id, cycle=cycle,
            horizon=self.config.horizon, risk_score=float(probability[0]),
            model_name=self.config.model_name, model_version=self.config.model_version,
            prediction_status="valid", input_validity="valid", component_status=statuses,
            disagreement=max(values) - min(values), anomaly_score=anomaly_score)

    def _validated(self, frame: pd.DataFrame, *, require_label: bool) -> tuple[np.ndarray, np.ndarray | None]:
        required = {"unit_id", "cycle", "horizon", *self.feature_names}
        if require_label:
            required.add("label")
        if not isinstance(frame, pd.DataFrame) or frame.empty or not required <= set(frame.columns):
            raise ValueError(f"stacking frame requires {sorted(required)}")
        if frame.duplicated(["unit_id", "cycle", "horizon"]).any():
            raise ValueError("stacking keys must be unique")
        if not frame.horizon.eq(self.config.horizon).all():
            raise ValueError("stacking frame horizon differs from model horizon")
        matrix = frame.loc[:, self.feature_names].to_numpy(dtype=float)
        if not np.isfinite(matrix).all():
            raise ValueError("stacking features must be finite")
        risk = frame.loc[:, self.config.risk_feature_names].to_numpy(dtype=float)
        if (risk < 0).any() or (risk > 1).any():
            raise ValueError("base risk features must be probabilities")
        labels = None
        if require_label:
            labels = frame.label.to_numpy(dtype=int)
            if not np.isin(labels, [0, 1]).all():
                raise ValueError("stacking labels must be binary")
        return matrix, labels

    def save(self, path: Path) -> None:
        if not self._fitted:
            raise RuntimeError("cannot save an unfitted stacking model")
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"schema": self.artifact_schema, "configuration": asdict(self.config),
                     "estimator": self.estimator}, path)

    @classmethod
    def load(cls, path: Path) -> Self:
        payload = joblib.load(path)
        if payload.get("schema") != cls.artifact_schema:
            raise ValueError("incompatible stacking artifact")
        config = dict(payload["configuration"])
        config["risk_feature_names"] = tuple(config["risk_feature_names"])
        instance = cls(StackingConfig(**config))
        instance.estimator = payload["estimator"]
        if not hasattr(instance.estimator, "classes_"):
            raise ValueError("stacking artifact contains an unfitted estimator")
        instance._fitted = True
        return instance


class ProbabilityCalibrator:
    """One-dimensional probability calibration fitted on held-out predictions."""

    methods = {"none", "platt", "isotonic"}
    artifact_schema = "predictive-maintenance.probability-calibrator.v1"

    def __init__(self, method: Literal["none", "platt", "isotonic"], *, seed: int = 4502) -> None:
        if method not in self.methods:
            raise ValueError(f"unsupported calibration method: {method}")
        self.method = method
        self.seed = seed
        self.estimator: LogisticRegression | IsotonicRegression | None = None
        self._fitted = False

    def fit(self, probabilities: Sequence[float], labels: Sequence[int]) -> Self:
        scores, target = _probability_vectors(probabilities, labels)
        if len(np.unique(target)) != 2:
            raise ValueError("calibration requires both classes")
        if self.method == "platt":
            self.estimator = LogisticRegression(random_state=self.seed, solver="lbfgs")
            self.estimator.fit(_logit(scores).reshape(-1, 1), target)
        elif self.method == "isotonic":
            self.estimator = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
            self.estimator.fit(scores, target)
        self._fitted = True
        return self

    def predict(self, probabilities: Sequence[float]) -> np.ndarray:
        if not self._fitted:
            raise RuntimeError("calibrator must be fitted")
        scores, _ = _probability_vectors(probabilities)
        if self.method == "none":
            calibrated = scores
        elif self.method == "platt":
            calibrated = self.estimator.predict_proba(_logit(scores).reshape(-1, 1))[:, 1]
        else:
            calibrated = self.estimator.predict(scores)
        calibrated = np.asarray(calibrated, dtype=float)
        if not np.isfinite(calibrated).all():
            raise RuntimeError("calibrator returned non-finite values")
        return np.clip(calibrated, 0.0, 1.0)

    def save(self, path: Path) -> None:
        if not self._fitted:
            raise RuntimeError("cannot save an unfitted calibrator")
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"schema": self.artifact_schema, "method": self.method,
                     "seed": self.seed, "estimator": self.estimator}, path)

    @classmethod
    def load(cls, path: Path) -> Self:
        payload = joblib.load(path)
        if payload.get("schema") != cls.artifact_schema:
            raise ValueError("incompatible calibration artifact")
        instance = cls(payload["method"], seed=int(payload["seed"]))
        instance.estimator = payload["estimator"]
        instance._fitted = True
        return instance


@dataclass(frozen=True)
class AlertThresholds:
    attention: float
    alert: float
    critical: float
    attention_horizon: int = 30
    alert_horizon: int = 30
    critical_horizon: int = 15
    persistence_cycles: int = 3

    def __post_init__(self) -> None:
        values = (self.attention, self.alert, self.critical)
        if not all(np.isfinite(value) for value in values) or not (0 <= values[0] < values[1] < values[2] <= 1):
            raise ValueError("thresholds must be finite and strictly ordered in [0, 1]")
        if any(type(value) is not int or value <= 0 for value in
               (self.attention_horizon, self.alert_horizon, self.critical_horizon,
                self.persistence_cycles)):
            raise ValueError("horizons and persistence must be positive integers")


def assign_alert_levels(predictions: pd.DataFrame, policy: AlertThresholds) -> pd.DataFrame:
    """Apply ordered levels and require consecutive evidence for emitted state."""
    required = {"unit_id", "cycle", "horizon", "risk_score"}
    if predictions.empty or not required <= set(predictions.columns):
        raise ValueError(f"predictions require {sorted(required)}")
    if predictions.duplicated(["unit_id", "cycle", "horizon"]).any():
        raise ValueError("prediction keys must be unique")
    pivot = predictions.pivot(index=["unit_id", "cycle"], columns="horizon",
                              values="risk_score")
    needed = {policy.attention_horizon, policy.alert_horizon, policy.critical_horizon}
    if not needed <= set(pivot.columns) or pivot.loc[:, list(needed)].isna().any().any():
        raise ValueError("all policy horizons must be present for every observation")
    frame = pivot.reset_index().sort_values(["unit_id", "cycle"]).reset_index(drop=True)
    attention = frame[policy.attention_horizon].to_numpy(float) >= policy.attention
    alert = frame[policy.alert_horizon].to_numpy(float) >= policy.alert
    critical = frame[policy.critical_horizon].to_numpy(float) >= policy.critical
    candidate = np.maximum(attention.astype(int), 2 * alert.astype(int))
    candidate = np.maximum(candidate, 3 * critical.astype(int))
    emitted = np.zeros(len(frame), dtype=int)
    for _, positions in frame.groupby("unit_id", sort=False).indices.items():
        run = np.zeros(4, dtype=int)
        for position in positions:
            level = int(candidate[position])
            for threshold_level in (1, 2, 3):
                run[threshold_level] = run[threshold_level] + 1 if level >= threshold_level else 0
            eligible = [threshold_level for threshold_level in (1, 2, 3)
                        if run[threshold_level] >= policy.persistence_cycles]
            emitted[position] = max(eligible, default=0)
    names = np.asarray(["normal", "atenção", "alerta", "crítico"], dtype=object)
    frame["raw_alert_level"] = names[candidate]
    frame["alert_level"] = names[emitted]
    frame["alert_persistence_cycles"] = policy.persistence_cycles
    return frame


def alert_metrics_by_unit(predictions: pd.DataFrame, *, threshold: float,
                          persistence_cycles: int) -> pd.DataFrame:
    """Compute temporal alert metrics for one horizon and one probability threshold."""
    required = {"unit_id", "cycle", "risk_score", "label", "RUL"}
    if predictions.empty or not required <= set(predictions.columns):
        raise ValueError(f"predictions require {sorted(required)}")
    if not np.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("threshold must be within [0, 1]")
    if type(persistence_cycles) is not int or persistence_cycles < 1:
        raise ValueError("persistence_cycles must be positive")
    rows: list[dict[str, object]] = []
    for unit_id, part in predictions.groupby("unit_id", sort=True):
        part = part.sort_values("cycle")
        cycles = part.cycle.to_numpy(dtype=int)
        above = part.risk_score.to_numpy(dtype=float) >= threshold
        false = above & part.label.eq(0).to_numpy(dtype=bool)
        episodes = _episode_lengths(above, cycles)
        false_episodes = _episode_lengths(false, cycles)
        runs = _consecutive_run_lengths(above, cycles)
        emitted = np.flatnonzero(runs >= persistence_cycles)
        first_cycle = int(cycles[emitted[0]]) if len(emitted) else None
        final_cycles = (part.cycle + part.RUL).to_numpy(dtype=int)
        if len(set(final_cycles.tolist())) != 1:
            raise ValueError("RUL is inconsistent with one terminal cycle per unit")
        rows.append({
            "unit_id": int(unit_id),
            "first_alert_cycle": first_cycle,
            "lead_time": (int(final_cycles[0]) - first_cycle if first_cycle is not None else None),
            "false_alert_episode_count": len(false_episodes),
            "false_alert_episode_duration": int(sum(false_episodes)),
            "alert_persistence": (float(sum(length >= persistence_cycles for length in episodes) / len(episodes))
                                  if episodes else 0.0),
            "longest_consecutive_alert": int(max(episodes, default=0)),
            "fraction_life_under_alert": float(above.mean()),
            "alert_episode_count": len(episodes),
        })
    return pd.DataFrame(rows)


class FrozenEvaluationGate:
    """Refuse a holdout read before freeze or after a recorded evaluation."""

    def __init__(self, freeze_manifest: Path, evaluation_receipt: Path) -> None:
        self.freeze_manifest = freeze_manifest
        self.evaluation_receipt = evaluation_receipt

    def authorize_single_read(self) -> Mapping[str, object]:
        if self.evaluation_receipt.exists():
            raise RuntimeError("test_internal evaluation already has a receipt")
        if not self.freeze_manifest.exists():
            raise RuntimeError("fusion must be frozen before test_internal is read")
        payload = json.loads(self.freeze_manifest.read_text(encoding="utf-8"))
        if payload.get("state") != "frozen" or payload.get("test_internal_read") is not False:
            raise RuntimeError("freeze manifest does not authorize the final evaluation")
        return payload


def _probability_vectors(probabilities: Sequence[float], labels: Sequence[int] | None = None):
    scores = np.asarray(probabilities, dtype=float)
    if scores.ndim != 1 or len(scores) == 0 or not np.isfinite(scores).all() or (scores < 0).any() or (scores > 1).any():
        raise ValueError("probabilities must be a non-empty finite vector in [0, 1]")
    if labels is None:
        return scores, None
    target = np.asarray(labels, dtype=int)
    if target.ndim != 1 or len(target) != len(scores) or not np.isin(target, [0, 1]).all():
        raise ValueError("labels must be an aligned binary vector")
    return scores, target


def _logit(probabilities: np.ndarray) -> np.ndarray:
    clipped = np.clip(probabilities, 1e-8, 1.0 - 1e-8)
    return np.log(clipped / (1.0 - clipped))


def _consecutive_run_lengths(mask: np.ndarray, cycles: np.ndarray) -> np.ndarray:
    result = np.zeros(len(mask), dtype=int)
    run = 0
    previous = None
    for index, (active, cycle) in enumerate(zip(mask, cycles, strict=True)):
        run = run + 1 if active and (previous is None or cycle == previous + 1) else int(active)
        result[index] = run
        previous = cycle
    return result


def _episode_lengths(mask: np.ndarray, cycles: np.ndarray) -> list[int]:
    runs = _consecutive_run_lengths(mask, cycles)
    ends = [index for index in range(len(runs))
            if runs[index] > 0 and (index == len(runs) - 1 or runs[index + 1] == 0)]
    return [int(runs[index]) for index in ends]
