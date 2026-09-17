"""Training-only descriptive summaries with explicit unit-level aggregation."""

import numpy as np
import pandas as pd

from predictive_maintenance.data.cmapss_schema import SENSOR_COLUMNS, SETTING_COLUMNS


def summarize_training(
    train: pd.DataFrame,
    *,
    dominant_fraction: float = 0.95,
    max_unique: int = 2,
    trend_min_rho: float = 0.5,
    trend_min_agreement: float = 0.8,
) -> dict:
    """All criteria and descriptive statistics depend on this frame only."""
    lifetime = train.groupby("unit_id").cycle.max()
    stats = {}
    for name in (*SETTING_COLUMNS, *SENSOR_COLUMNS):
        column = train[name]
        unique = int(column.nunique())
        constant = unique == 1
        dominant = float(column.value_counts(normalize=True).iloc[0])
        rhos = []
        for _, unit in train.groupby("unit_id", sort=True):
            if unit[name].nunique() > 1:
                # Spearman = Pearson of ranks; no hypothesis test on dependent rows.
                rhos.append(float(unit[name].rank().corr(unit.cycle.rank())))
        median_rho = float(np.median(rhos)) if rhos else None
        direction_agreement = (
            sum(np.sign(rho) == np.sign(median_rho) for rho in rhos) / len(rhos)
            if rhos else None
        )
        means = train.groupby("unit_id")[name].mean()
        within = train.groupby("unit_id")[name].var(ddof=1)
        stats[name] = {
            "min": float(column.min()), "max": float(column.max()),
            "mean": float(column.mean()),
            # Exact constants can have spurious nonzero variance from float roundoff.
            "variance": 0.0 if constant else float(column.var(ddof=1)),
            "std": 0.0 if constant else float(column.std(ddof=1)),
            "unique_values": unique, "dominant_fraction": dominant,
            "constant": constant,
            "near_constant": not constant and unique <= max_unique and dominant >= dominant_fraction,
            "median_unit_spearman_age": median_rho,
            "rho_q25": float(np.quantile(rhos, .25)) if rhos else None,
            "rho_q75": float(np.quantile(rhos, .75)) if rhos else None,
            "direction_agreement": direction_agreement,
            "units_with_defined_rho": len(rhos),
            "std_between_unit_means": 0.0 if constant else float(means.std(ddof=1)),
            "median_within_unit_std": 0.0 if constant else float(within.pow(.5).median()),
            "informative_trend_candidate": bool(
                median_rho is not None
                and abs(median_rho) >= trend_min_rho
                and direction_agreement >= trend_min_agreement
            ),
        }
    active = [name for name in SENSOR_COLUMNS if not stats[name]["constant"]]
    centered = train[active] - train.groupby("unit_id")[active].transform("mean")
    pooled = train[active].corr()
    centered_corr = centered.corr()
    pairs = [
        {"left": left, "right": right, "pearson": float(pooled.loc[left, right]),
         "within_centered_pearson": float(centered_corr.loc[left, right])}
        for i, left in enumerate(active) for right in active[i + 1:]
    ]
    pairs.sort(key=lambda pair: -abs(pair["pearson"]))
    return {
        "analysis_partition": "train",
        "engines": int(len(lifetime)), "rows": len(train),
        "lifetime": {key: float(value) for key, value in lifetime.describe().items()},
        "columns": stats, "strongest_correlation_pairs": pairs[:10],
        "constant_sensors": [s for s in SENSOR_COLUMNS if stats[s]["constant"]],
        "near_constant_sensors": [s for s in SENSOR_COLUMNS if stats[s]["near_constant"]],
        "trend_candidates": [s for s in SENSOR_COLUMNS if stats[s]["informative_trend_candidate"]],
    }


def normalized_unit_curves(
    train: pd.DataFrame, sensor: str, points: int = 101
) -> tuple[np.ndarray, np.ndarray, list[int]]:
    """Retrospective interpolation; one curve/weight per unit, not per row."""
    if type(points) is not int or points < 2:
        raise ValueError("at least two normalized life points are required")
    grid = np.linspace(0, 1, points)
    curves, units = [], []
    for unit_id, unit in train.groupby("unit_id", sort=True):
        # Endpoints exactly 0 and 1; never export this future-dependent axis as features.
        life = (unit.cycle - 1) / (unit.cycle.max() - 1)
        if len(unit) < 2:
            raise ValueError("normalized life requires at least two cycles per unit")
        curves.append(np.interp(grid, life, unit[sensor]))
        units.append(int(unit_id))
    return grid, np.asarray(curves), units
