"""Cluster bootstrap utilities that preserve complete asset trajectories."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Callable, Mapping

import numpy as np
import pandas as pd


MetricFunction = Callable[[pd.DataFrame], float | None]


@dataclass(frozen=True)
class UnitBootstrapConfig:
    resamples: int = 1000
    confidence_level: float = 0.95
    seed: int = 4801

    def __post_init__(self) -> None:
        if type(self.resamples) is not int or self.resamples < 2:
            raise ValueError("resamples must be an integer of at least two")
        if not 0.0 < self.confidence_level < 1.0:
            raise ValueError("confidence_level must be in (0, 1)")
        if type(self.seed) is not int:
            raise ValueError("seed must be an integer")


def resample_complete_units(
    frame: pd.DataFrame, sampled_units: np.ndarray | list[object],
) -> pd.DataFrame:
    """Materialize a cluster sample and assign a fresh id to repeated draws."""
    if frame.empty or "unit_id" not in frame.columns:
        raise ValueError("frame must contain complete units")
    parts: list[pd.DataFrame] = []
    available = set(frame["unit_id"].unique().tolist())
    for draw_index, unit_id in enumerate(sampled_units, start=1):
        if unit_id not in available:
            raise ValueError(f"sampled unit is absent: {unit_id}")
        part = frame.loc[frame.unit_id.eq(unit_id)].copy()
        part["bootstrap_source_unit_id"] = unit_id
        part["unit_id"] = draw_index
        parts.append(part)
    if not parts:
        raise ValueError("sampled_units must not be empty")
    return pd.concat(parts, ignore_index=True)


def unit_bootstrap_intervals(
    frame: pd.DataFrame,
    metrics: Mapping[str, MetricFunction],
    *,
    config: UnitBootstrapConfig | None = None,
) -> dict[str, dict[str, object]]:
    """Estimate percentile intervals by resampling units, never individual rows."""
    cfg = config or UnitBootstrapConfig()
    if frame.empty or "unit_id" not in frame.columns or not metrics:
        raise ValueError("non-empty frame, unit_id and metrics are required")
    units = np.asarray(sorted(frame.unit_id.unique().tolist()))
    if len(units) < 2:
        raise ValueError("cluster bootstrap requires at least two units")
    rng = np.random.default_rng(cfg.seed)
    values: dict[str, list[float]] = {name: [] for name in metrics}
    invalid: dict[str, Counter[str]] = {name: Counter() for name in metrics}

    for _ in range(cfg.resamples):
        sampled = rng.choice(units, size=len(units), replace=True)
        replicate = resample_complete_units(frame, sampled)
        for name, function in metrics.items():
            try:
                value = function(replicate)
                if value is None or not np.isfinite(float(value)):
                    invalid[name]["non_finite_or_missing"] += 1
                else:
                    values[name].append(float(value))
            except (ValueError, ZeroDivisionError, FloatingPointError) as exc:
                invalid[name][type(exc).__name__ + ": " + str(exc)] += 1

    alpha = (1.0 - cfg.confidence_level) / 2.0
    output: dict[str, dict[str, object]] = {}
    for name, observed_values in values.items():
        array = np.asarray(observed_values, dtype=float)
        output[name] = {
            "confidence_level": cfg.confidence_level,
            "lower": float(np.quantile(array, alpha)) if len(array) else None,
            "median": float(np.quantile(array, 0.5)) if len(array) else None,
            "upper": float(np.quantile(array, 1.0 - alpha)) if len(array) else None,
            "valid_replicates": int(len(array)),
            "invalid_replicates": int(cfg.resamples - len(array)),
            "invalid_reasons": dict(sorted(invalid[name].items())),
            "resampling_unit": "unit_id complete trajectory",
            "seed": cfg.seed,
        }
    return output
