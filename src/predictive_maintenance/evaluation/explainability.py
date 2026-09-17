"""Semantics-preserving helpers for model explanations."""

from __future__ import annotations

import json
from typing import Sequence

import numpy as np
import pandas as pd


EXPLANATION_COLUMNS = (
    "unit_id", "cycle", "horizon", "risk_weibull", "risk_xgboost",
    "risk_hazard_discrete", "risk_final", "anomaly_score", "disagreement",
    "top_features", "top_sensors", "reason_codes", "prediction_status",
    "input_validity", "telemetry_stale",
)


def split_feature_name(name: str) -> tuple[str, str]:
    """Return source signal and temporal operation without physical semantics."""
    if name == "age_cycle":
        return "age_cycle", "current_age"
    if "__" not in name:
        return name, "unspecified"
    source, operation = name.split("__", 1)
    return source, operation


def top_shap_contributions(
    keys: pd.DataFrame,
    feature_names: Sequence[str],
    feature_values: np.ndarray,
    shap_values: np.ndarray,
    *,
    horizon: int,
    top_k: int,
) -> pd.DataFrame:
    """Create ranked local contributions with row-wise relative magnitudes."""
    names = tuple(feature_names)
    values = np.asarray(feature_values, dtype=float)
    contributions = np.asarray(shap_values, dtype=float)
    if list(keys.columns) != ["unit_id", "cycle"]:
        raise ValueError("keys must contain exactly unit_id and cycle")
    if values.shape != contributions.shape or values.shape != (len(keys), len(names)):
        raise ValueError("feature and SHAP matrices must align with keys and names")
    if not np.isfinite(values).all() or not np.isfinite(contributions).all():
        raise ValueError("feature and SHAP values must be finite")
    if type(top_k) is not int or not 1 <= top_k <= len(names):
        raise ValueError("top_k is outside the feature count")
    rows: list[dict[str, object]] = []
    for row_index, key in enumerate(keys.itertuples(index=False)):
        absolute = np.abs(contributions[row_index])
        denominator = float(absolute.sum())
        selected = np.argsort(-absolute, kind="stable")[:top_k]
        for rank, feature_index in enumerate(selected, start=1):
            name = names[int(feature_index)]
            source, operation = split_feature_name(name)
            contribution = float(contributions[row_index, feature_index])
            rows.append({
                "unit_id": int(key.unit_id), "cycle": int(key.cycle),
                "horizon": int(horizon), "rank": rank,
                "feature_name": name, "source_signal": source,
                "temporal_component": operation,
                "direction": "increases_risk" if contribution > 0 else (
                    "decreases_risk" if contribution < 0 else "neutral"
                ),
                "shap_value": contribution,
                "relative_magnitude": (
                    float(absolute[feature_index] / denominator) if denominator > 0 else 0.0
                ),
                "feature_value": float(values[row_index, feature_index]),
                "contribution_space": "xgboost_raw_margin",
            })
    return pd.DataFrame(rows)


def aggregate_sensor_contributions(
    local_contributions: pd.DataFrame, *, top_k: int,
) -> pd.DataFrame:
    """Aggregate local feature SHAP values by named source signal."""
    required = {"unit_id", "cycle", "horizon", "source_signal", "shap_value"}
    if local_contributions.empty or not required <= set(local_contributions.columns):
        raise ValueError("local contribution table is incomplete")
    grouped = local_contributions.groupby(
        ["unit_id", "cycle", "horizon", "source_signal"], as_index=False,
    ).agg(shap_value=("shap_value", "sum"), absolute_magnitude=("shap_value", lambda x: float(np.abs(x).sum())))
    grouped["relative_magnitude"] = grouped["absolute_magnitude"] / grouped.groupby(
        ["unit_id", "cycle", "horizon"]
    )["absolute_magnitude"].transform("sum").replace(0.0, 1.0)
    grouped = grouped.sort_values(
        ["unit_id", "cycle", "horizon", "absolute_magnitude"],
        ascending=[True, True, True, False], kind="stable",
    )
    grouped["rank"] = grouped.groupby(["unit_id", "cycle", "horizon"]).cumcount() + 1
    grouped = grouped.loc[grouped["rank"].le(top_k)].copy()
    grouped["direction"] = np.where(
        grouped.shap_value.gt(0), "increases_risk",
        np.where(grouped.shap_value.lt(0), "decreases_risk", "neutral"),
    )
    return grouped.reset_index(drop=True)


def top_sensor_contributions(
    keys: pd.DataFrame,
    feature_names: Sequence[str],
    shap_values: np.ndarray,
    *,
    horizon: int,
    top_k: int,
) -> pd.DataFrame:
    """Aggregate every local feature contribution before ranking source signals."""
    names = tuple(feature_names)
    values = np.asarray(shap_values, dtype=float)
    if list(keys.columns) != ["unit_id", "cycle"]:
        raise ValueError("keys must contain exactly unit_id and cycle")
    if values.shape != (len(keys), len(names)) or not np.isfinite(values).all():
        raise ValueError("SHAP matrix must be finite and aligned")
    sources = np.asarray([split_feature_name(name)[0] for name in names], dtype=object)
    unique_sources = tuple(dict.fromkeys(sources.tolist()))
    if type(top_k) is not int or not 1 <= top_k <= len(unique_sources):
        raise ValueError("top_k is outside the source-signal count")
    rows: list[dict[str, object]] = []
    for row_index, key in enumerate(keys.itertuples(index=False)):
        grouped = []
        for source in unique_sources:
            selected = sources == source
            signed = float(values[row_index, selected].sum())
            absolute = float(np.abs(values[row_index, selected]).sum())
            grouped.append((source, signed, absolute))
        denominator = sum(item[2] for item in grouped)
        for rank, (source, signed, absolute) in enumerate(
            sorted(grouped, key=lambda item: item[2], reverse=True)[:top_k], start=1,
        ):
            rows.append({
                "unit_id": int(key.unit_id), "cycle": int(key.cycle),
                "horizon": int(horizon), "rank": rank, "source_signal": source,
                "shap_value": signed, "absolute_magnitude": absolute,
                "relative_magnitude": absolute / denominator if denominator > 0 else 0.0,
                "direction": "increases_risk" if signed > 0 else (
                    "decreases_risk" if signed < 0 else "neutral"
                ),
            })
    return pd.DataFrame(rows)


def validate_explanation_frame(frame: pd.DataFrame) -> None:
    """Enforce separate semantics for risks, anomaly, disagreement and status."""
    if frame.empty or not set(EXPLANATION_COLUMNS) <= set(frame.columns):
        raise ValueError("explanation frame does not implement the common structure")
    risk_columns = ["risk_weibull", "risk_xgboost", "risk_hazard_discrete", "risk_final"]
    risk = frame[risk_columns].to_numpy(dtype=float)
    if not np.isfinite(risk).all() or ((risk < 0) | (risk > 1)).any():
        raise ValueError("risk fields must be finite probabilities in [0, 1]")
    auxiliary = frame[["anomaly_score", "disagreement"]].to_numpy(dtype=float)
    if not np.isfinite(auxiliary).all() or (auxiliary < 0).any():
        raise ValueError("anomaly_score and disagreement must be finite non-negative indicators")
    if not frame.prediction_status.isin(["valid", "degraded", "unavailable"]).all():
        raise ValueError("prediction_status is invalid")
    if not frame.input_validity.isin(["valid", "stale", "invalid"]).all():
        raise ValueError("input_validity is invalid")
    if not pd.api.types.is_bool_dtype(frame.telemetry_stale):
        raise ValueError("telemetry_stale must be boolean")
    for name in ("top_features", "top_sensors", "reason_codes"):
        for value in frame[name]:
            decoded = json.loads(value)
            if not isinstance(decoded, list):
                raise ValueError(f"{name} must encode a JSON list")
