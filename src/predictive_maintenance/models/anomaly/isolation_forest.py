"""Isolation Forest anomaly detector with an explicitly non-probabilistic scale."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from math import isfinite
from pathlib import Path
from typing import Self, Sequence

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from predictive_maintenance.core.causality import validate_feature_names
from predictive_maintenance.core.records import AnomalyPrediction, FeatureRecord
from predictive_maintenance.models.anomaly.interfaces import AnomalyDetector


@dataclass(frozen=True)
class IsolationForestConfig:
    model_version: str = "1.0.0"
    random_seed: int = 4401
    n_estimators: int = 200
    max_samples: int = 256
    contamination: str = "auto"

    def __post_init__(self) -> None:
        if not self.model_version.strip() or type(self.random_seed) is not int:
            raise ValueError("model version and integer seed are required")
        if type(self.n_estimators) is not int or self.n_estimators < 1:
            raise ValueError("n_estimators must be positive")
        if type(self.max_samples) is not int or self.max_samples < 2:
            raise ValueError("max_samples must be at least two")
        if self.contamination != "auto":
            raise ValueError("only contamination='auto' is supported; no anomaly threshold is fitted")


class IsolationForestAnomalyDetector(AnomalyDetector):
    """Score = empirical CDF of -IsolationForest.score_samples on healthy training rows.

    Larger values mean more unusual relative to the healthy fitting population.
    It is a bounded ranking/percentile scale, neither a failure probability nor
    a calibrated abnormal-event probability.
    """

    artifact_schema = "isolation-forest-anomaly/v1"
    model_name = "isolation_forest_anomaly"

    def __init__(self, feature_names: Sequence[str], config: IsolationForestConfig | None = None) -> None:
        if not feature_names or len(set(feature_names)) != len(feature_names):
            raise ValueError("feature names must be non-empty and unique")
        validate_feature_names(feature_names)
        self.feature_names = tuple(feature_names)
        self.config = config or IsolationForestConfig()
        self.scaler = StandardScaler()
        self.estimator = IsolationForest(
            n_estimators=self.config.n_estimators, max_samples=self.config.max_samples,
            contamination=self.config.contamination, random_state=self.config.random_seed,
            n_jobs=1,
        )
        self.healthy_raw_scores: np.ndarray | None = None
        self.training_summary: dict[str, object] = {}
        self._fitted = False

    def fit(self, features: Sequence[FeatureRecord]) -> Self:
        if len(features) < 2:
            raise ValueError("at least two healthy fitting features are required")
        matrix = self._valid_matrix(features)
        scaled = self.scaler.fit_transform(matrix)
        self.estimator.fit(scaled)
        raw = -self.estimator.score_samples(scaled)
        if not np.isfinite(raw).all():
            raise RuntimeError("isolation forest produced non-finite healthy scores")
        self.healthy_raw_scores = np.sort(raw)
        units = {record.unit_id for record in features}
        self.training_summary = {
            "healthy_rows": int(len(features)), "healthy_units": int(len(units)),
            "raw_anomaly_score_min": float(raw.min()), "raw_anomaly_score_max": float(raw.max()),
            "normalization": "empirical CDF of -score_samples on healthy fitting rows",
            "contamination": self.config.contamination,
        }
        self._fitted = True
        return self

    def detect(self, features: Sequence[FeatureRecord]) -> list[AnomalyPrediction]:
        if not self._fitted or self.healthy_raw_scores is None:
            raise RuntimeError("detector must be fitted or loaded before detection")
        results: list[AnomalyPrediction] = []
        for record in features:
            reason = self._invalid_reason(record)
            if reason is not None:
                unit_id = record.unit_id if isinstance(record.unit_id, str) and record.unit_id.strip() else "invalid-unit"
                cycle = record.cycle if type(record.cycle) is int and record.cycle > 0 else 1
                results.append(AnomalyPrediction(unit_id, cycle, None, self.model_name,
                    self.config.model_version, "unavailable", "invalid", reason))
                continue
            row = np.asarray([[float(record.values[name]) for name in self.feature_names]])
            raw = float(-self.estimator.score_samples(self.scaler.transform(row))[0])
            score = self._empirical_percentile(raw)
            results.append(AnomalyPrediction(record.unit_id, record.cycle, score, self.model_name,
                self.config.model_version, "available", "valid"))
        return results

    def raw_anomaly_score(self, features: Sequence[FeatureRecord]) -> np.ndarray:
        """Diagnostic only: larger -score_samples means more isolated."""
        if not self._fitted:
            raise RuntimeError("detector must be fitted or loaded before detection")
        return -self.estimator.score_samples(self.scaler.transform(self._valid_matrix(features)))

    def save(self, path: Path) -> None:
        if not self._fitted or self.healthy_raw_scores is None:
            raise RuntimeError("cannot save an unfitted detector")
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"schema": self.artifact_schema, "configuration": asdict(self.config),
                     "feature_names": self.feature_names, "scaler": self.scaler,
                     "estimator": self.estimator, "healthy_raw_scores": self.healthy_raw_scores,
                     "training_summary": self.training_summary}, path, compress=3)

    @classmethod
    def load(cls, path: Path) -> Self:
        payload = joblib.load(path)  # Trusted local artifact only.
        if not isinstance(payload, dict) or payload.get("schema") != cls.artifact_schema:
            raise ValueError("incompatible anomaly detector artifact")
        instance = cls(payload["feature_names"], IsolationForestConfig(**payload["configuration"]))
        instance.scaler = payload["scaler"]
        instance.estimator = payload["estimator"]
        instance.healthy_raw_scores = np.asarray(payload["healthy_raw_scores"], dtype=float)
        if (instance.healthy_raw_scores.ndim != 1 or len(instance.healthy_raw_scores) < 2
                or not np.isfinite(instance.healthy_raw_scores).all()
                or np.any(np.diff(instance.healthy_raw_scores) < 0)):
            raise ValueError("invalid healthy score reference")
        if instance.scaler.n_features_in_ != len(instance.feature_names):
            raise ValueError("incompatible anomaly scaler")
        instance.training_summary = dict(payload["training_summary"])
        instance._fitted = True
        return instance

    @staticmethod
    def artifact_hash(path: Path) -> str:
        return sha256(path.read_bytes()).hexdigest()

    def _empirical_percentile(self, raw_score: float) -> float:
        assert self.healthy_raw_scores is not None
        # Right-continuous empirical CDF. Values outside the healthy support map to 0/1.
        return float(np.searchsorted(self.healthy_raw_scores, raw_score, side="right") /
                     len(self.healthy_raw_scores))

    def _valid_matrix(self, features: Sequence[FeatureRecord]) -> np.ndarray:
        rows = []
        for record in features:
            reason = self._invalid_reason(record)
            if reason is not None:
                raise ValueError(reason)
            rows.append([float(record.values[name]) for name in self.feature_names])
        return np.asarray(rows, dtype=float)

    def _invalid_reason(self, record: FeatureRecord) -> str | None:
        if not isinstance(record.unit_id, str) or not record.unit_id.strip():
            return "unit_id is invalid"
        if type(record.cycle) is not int or record.cycle <= 0:
            return "cycle is invalid"
        if set(record.values) != set(self.feature_names):
            return "feature schema is missing or incompatible"
        for name in self.feature_names:
            value = record.values[name]
            if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
                return f"feature {name} is not numeric"
            if not isfinite(float(value)):
                return f"feature {name} is not finite"
        return None
