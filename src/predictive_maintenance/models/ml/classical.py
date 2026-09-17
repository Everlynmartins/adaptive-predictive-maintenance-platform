"""Classical tree models implementing the common horizon-risk contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from math import isfinite
from pathlib import Path
from typing import Sequence, Self

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from xgboost import XGBClassifier

from predictive_maintenance.core.records import FeatureRecord, RiskPrediction, TargetRecord
from predictive_maintenance.models.interfaces import RiskModel


@dataclass(frozen=True)
class TreeModelConfig:
    model_name: str
    model_version: str
    horizon: int
    random_seed: int
    parameters: dict[str, object]

    def __post_init__(self) -> None:
        if not self.model_name.strip() or not self.model_version.strip():
            raise ValueError("model name and version must be non-empty")
        if type(self.horizon) is not int or self.horizon <= 0:
            raise ValueError("horizon must be a positive integer")
        if type(self.random_seed) is not int:
            raise ValueError("random_seed must be an integer")


class _TreeRiskModel(RiskModel):
    artifact_schema = "classical-tree-risk-model/v1"
    algorithm = "base"

    def __init__(self, config: TreeModelConfig, feature_names: Sequence[str]) -> None:
        if not feature_names or len(set(feature_names)) != len(feature_names):
            raise ValueError("feature_names must be non-empty and unique")
        self.config = config
        self.feature_names = tuple(feature_names)
        self.estimator = self._new_estimator()
        self.training_summary: dict[str, object] = {}
        self._fitted = False

    def fit(
        self, features: Sequence[FeatureRecord], targets: Sequence[TargetRecord] | None = None,
    ) -> Self:
        if not features or targets is None or len(features) != len(targets):
            raise ValueError("aligned non-empty features and targets are required")
        matrix = self._valid_matrix(features)
        labels = np.empty(len(targets), dtype=np.int8)
        for index, (feature, target) in enumerate(zip(features, targets, strict=True)):
            if (feature.unit_id, feature.cycle) != (target.unit_id, target.cycle):
                raise ValueError("feature and target keys are not aligned")
            horizon = target.values.get("horizon")
            label = target.values.get("failure_within_horizon")
            if horizon != self.config.horizon or label not in {0, 1, False, True}:
                raise ValueError("target does not match the configured horizon")
            labels[index] = int(label)
        if np.unique(labels).size != 2:
            raise ValueError("training targets require both classes")
        unit_ids = np.asarray([record.unit_id for record in features], dtype=object)
        weights = _unit_and_class_balanced_weights(unit_ids, labels)
        self.estimator.fit(matrix, labels, sample_weight=weights)
        self.training_summary = {
            "rows": len(features),
            "units": int(np.unique(unit_ids).size),
            "positive_rows": int(labels.sum()),
            "negative_rows": int(len(labels) - labels.sum()),
            "prevalence": float(labels.mean()),
            "weighting": "inverse rows per unit multiplied by inverse class frequency; mean normalized to one",
            "weight_min": float(weights.min()),
            "weight_max": float(weights.max()),
        }
        self._fitted = True
        return self

    def predict_risk(
        self, features: Sequence[FeatureRecord], *, horizon: int,
    ) -> list[RiskPrediction]:
        if not self._fitted:
            raise RuntimeError("model must be fitted or loaded before prediction")
        if type(horizon) is not int or horizon <= 0 or horizon != self.config.horizon:
            raise ValueError(f"model supports only horizon {self.config.horizon}")
        results: list[RiskPrediction | None] = [None] * len(features)
        valid_indexes, rows = [], []
        for index, record in enumerate(features):
            reason = self._invalid_reason(record)
            if reason is not None:
                results[index] = RiskPrediction(
                    unit_id=str(record.unit_id) if str(record.unit_id).strip() else "invalid-unit",
                    cycle=int(record.cycle) if type(record.cycle) is int and record.cycle > 0 else 1,
                    horizon=horizon, risk_score=None,
                    model_name=self.config.model_name, model_version=self.config.model_version,
                    prediction_status="unavailable", input_validity="invalid",
                    explanation=reason,
                )
            else:
                valid_indexes.append(index)
                rows.append([float(record.values[name]) for name in self.feature_names])
        if rows:
            probabilities = self.estimator.predict_proba(np.asarray(rows, dtype=float))[:, 1]
            for index, probability in zip(valid_indexes, probabilities, strict=True):
                record = features[index]
                results[index] = RiskPrediction(
                    unit_id=record.unit_id, cycle=record.cycle, horizon=horizon,
                    risk_score=float(np.clip(probability, 0.0, 1.0)),
                    model_name=self.config.model_name, model_version=self.config.model_version,
                    prediction_status="available", input_validity="valid",
                )
        return [result for result in results if result is not None]

    def save(self, path: Path) -> None:
        if not self._fitted:
            raise RuntimeError("cannot save an unfitted model")
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({
            "schema": self.artifact_schema,
            "algorithm": self.algorithm,
            "class_name": type(self).__name__,
            "configuration": asdict(self.config),
            "feature_names": list(self.feature_names),
            "training_summary": self.training_summary,
            "estimator": self.estimator,
        }, path, compress=3)

    @classmethod
    def load(cls, path: Path) -> Self:
        payload = joblib.load(path)
        if (not isinstance(payload, dict) or payload.get("schema") != cls.artifact_schema
                or payload.get("algorithm") != cls.algorithm
                or payload.get("class_name") != cls.__name__):
            raise ValueError("incompatible model artifact")
        raw = payload["configuration"]
        instance = cls(TreeModelConfig(
            model_name=str(raw["model_name"]), model_version=str(raw["model_version"]),
            horizon=int(raw["horizon"]), random_seed=int(raw["random_seed"]),
            parameters=dict(raw["parameters"]),
        ), payload["feature_names"])
        instance.estimator = payload["estimator"]
        instance.training_summary = dict(payload["training_summary"])
        instance._fitted = True
        return instance

    @staticmethod
    def artifact_hash(path: Path) -> str:
        return sha256(path.read_bytes()).hexdigest()

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

    def _new_estimator(self):
        raise NotImplementedError


class RandomForestRiskModel(_TreeRiskModel):
    algorithm = "random_forest"

    def _new_estimator(self) -> RandomForestClassifier:
        return RandomForestClassifier(
            random_state=self.config.random_seed,
            n_jobs=1,
            class_weight=None,
            **self.config.parameters,
        )


class XGBoostRiskModel(_TreeRiskModel):
    algorithm = "xgboost"

    def _new_estimator(self) -> XGBClassifier:
        return XGBClassifier(
            objective="binary:logistic", eval_metric="logloss",
            random_state=self.config.random_seed, n_jobs=1,
            **self.config.parameters,
        )


def _unit_and_class_balanced_weights(unit_ids: np.ndarray, labels: np.ndarray) -> np.ndarray:
    unique_units, unit_inverse, unit_counts = np.unique(
        unit_ids, return_inverse=True, return_counts=True,
    )
    unit_weight = len(labels) / (len(unique_units) * unit_counts[unit_inverse])
    class_counts = np.bincount(labels, minlength=2)
    class_weight = len(labels) / (2.0 * class_counts[labels])
    weights = unit_weight * class_weight
    return weights / weights.mean()
