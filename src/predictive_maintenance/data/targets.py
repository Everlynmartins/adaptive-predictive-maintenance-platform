"""Offline evaluation targets for complete, run-to-failure trajectories."""

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class HorizonConfig:
    failure_horizon: int = 30
    critical_horizon: int = 15

    def __post_init__(self) -> None:
        for value in (self.failure_horizon, self.critical_horizon):
            if type(value) is not int or value <= 0:
                raise ValueError("horizons must be positive integer cycles")
        if self.critical_horizon >= self.failure_horizon:
            raise ValueError("critical horizon must be smaller than failure horizon")


def build_evaluation_targets(
    telemetry: pd.DataFrame,
    config: HorizonConfig,
    *,
    complete_run_to_failure: bool,
) -> pd.DataFrame:
    """Return targets only, keyed by unit/cycle; never infer failure for censored data.

    Boundary convention: 0 <= RUL <= H, including the recorded terminal cycle.
    is_operational identifies rows eligible for prospective training and metrics.
    Use build_operational_targets for the conditional prediction population.
    """
    if not complete_run_to_failure:
        raise ValueError("RUL from final cycle requires complete run-to-failure data")
    if telemetry.empty or not {"unit_id", "cycle"} <= set(telemetry.columns):
        raise ValueError("non-empty unit_id and cycle columns are required")
    keys = telemetry[["unit_id", "cycle"]].copy()
    if keys.isna().any().any() or keys.duplicated().any():
        raise ValueError("target keys must be non-missing and unique")
    for name in keys:
        values = pd.to_numeric(keys[name], errors="coerce")
        if values.isna().any() or (values <= 0).any() or values.mod(1).ne(0).any():
            raise ValueError("FD001 target keys must be positive integers")
    for _, unit in keys.groupby("unit_id", sort=False):
        if unit.cycle.tolist() != list(range(1, len(unit) + 1)):
            raise ValueError("complete trajectories must have consecutive cycles 1..N")
    final_cycle = keys.groupby("unit_id").cycle.transform("max")
    keys["RUL"] = (final_cycle - keys.cycle).clip(lower=0).astype("int64")
    keys["failure_within_horizon"] = keys.RUL.le(config.failure_horizon)
    keys["failure_within_critical_horizon"] = keys.RUL.le(config.critical_horizon)
    keys["is_operational"] = keys.RUL.gt(0)
    return keys


def build_operational_targets(
    telemetry: pd.DataFrame,
    config: HorizonConfig,
    *,
    complete_run_to_failure: bool,
) -> pd.DataFrame:
    """Return offline targets at t < T only, with explicit horizon metadata.

    This is target preparation, never a feature transform or online liveness test.
    The retrospective table (including RUL=0) is preserved by the other function.
    """
    targets = build_evaluation_targets(
        telemetry, config, complete_run_to_failure=complete_run_to_failure,
    )
    operational = targets.loc[targets.is_operational].copy()
    operational["horizon"] = config.failure_horizon
    operational["critical_horizon"] = config.critical_horizon
    return operational
