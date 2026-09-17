"""Causal telemetry features for ordered per-unit trajectories."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Sequence, Self

import numpy as np
import pandas as pd

from predictive_maintenance.core.causality import validate_feature_names
from predictive_maintenance.core.records import FeatureRecord, TelemetryRecord
from predictive_maintenance.features.interfaces import FeatureEngineer


@dataclass(frozen=True)
class CausalFeatureConfig:
    windows: tuple[int, ...] = (5, 10, 20)
    relative_epsilon: float = 1e-12
    variance_epsilon: float = 0.0
    include_cycle: bool = True

    def __post_init__(self) -> None:
        if not self.windows or any(type(value) is not int or value < 2 for value in self.windows):
            raise ValueError("windows must contain integers greater than one")
        if tuple(sorted(set(self.windows))) != self.windows:
            raise ValueError("windows must be strictly increasing and unique")
        if not np.isfinite(self.relative_epsilon) or self.relative_epsilon <= 0:
            raise ValueError("relative_epsilon must be positive and finite")
        if not np.isfinite(self.variance_epsilon) or self.variance_epsilon < 0:
            raise ValueError("variance_epsilon must be non-negative and finite")


class CausalTelemetryFeatures(FeatureEngineer):
    """Generate prefix-only features and apply train-fitted selection/imputation.

    Selection removes only raw columns whose training variance is at or below
    ``variance_epsilon``. Medians are learned from eligible training rows after
    causal feature generation. No statistic for an output at cycle t uses a row
    after t, although the learned medians are global training-partition state.
    """

    artifact_schema = "causal-telemetry-features/v1"

    def __init__(self, config: CausalFeatureConfig | None = None) -> None:
        self.config = config or CausalFeatureConfig()
        self.raw_columns: tuple[str, ...] = ()
        self.dropped_constant_columns: tuple[str, ...] = ()
        self.feature_names: tuple[str, ...] = ()
        self.imputation_medians: dict[str, float] = {}
        self._fitted = False

    def fit(self, telemetry: Sequence[TelemetryRecord]) -> Self:
        return self.fit_frame(_records_to_frame(telemetry))

    def transform(self, telemetry: Sequence[TelemetryRecord]) -> list[FeatureRecord]:
        frame = self.transform_frame(_records_to_frame(telemetry))
        return [FeatureRecord(
            unit_id=str(row.unit_id), cycle=int(row.cycle),
            values={name: float(getattr(row, name)) for name in self.feature_names},
        ) for row in frame.itertuples(index=False)]

    def fit_frame(
        self, telemetry: pd.DataFrame, *, fit_mask: Sequence[bool] | None = None,
    ) -> Self:
        frame = _validate_telemetry(telemetry)
        mask = _validated_mask(fit_mask, len(frame))
        candidates = [name for name in frame.columns if name not in {"unit_id", "cycle"}]
        if not candidates:
            raise ValueError("telemetry must contain sensor or operating-setting columns")
        selected, dropped = [], []
        for name in candidates:
            variance = float(frame.loc[mask, name].var(ddof=0))
            unique_values = int(frame.loc[mask, name].nunique(dropna=False))
            (selected if unique_values > 1 and variance > self.config.variance_epsilon
             else dropped).append(name)
        if not selected:
            raise ValueError("all telemetry columns are constant in the fitting population")
        self.raw_columns = tuple(selected)
        self.dropped_constant_columns = tuple(dropped)
        generated = self._generate(frame)
        feature_names = [name for name in generated.columns if name not in {"unit_id", "cycle"}]
        medians: dict[str, float] = {}
        for name in feature_names:
            values = generated.loc[mask, name]
            if not values.notna().any():
                raise ValueError(f"feature has no finite fitting values: {name}")
            median = float(values.median())
            if not np.isfinite(median):
                raise ValueError(f"feature median is not finite: {name}")
            medians[name] = median
        validate_feature_names(feature_names)
        self.feature_names = tuple(feature_names)
        self.imputation_medians = medians
        self._fitted = True
        return self

    def fit_receiver_frame(
        self,
        telemetry: pd.DataFrame,
        observed_mask: pd.DataFrame,
        *,
        fit_mask: Sequence[bool] | None = None,
    ) -> Self:
        """Fit features from the information available at a telemetry receiver.

        ``telemetry`` contains the receiver state at every logical cycle, while
        ``observed_mask`` identifies which values arrived as new observations at
        that cycle.  Held values never update a sensor's temporal history.  This
        distinction prevents a held value from being counted repeatedly as if it
        were newly sampled.
        """

        frame = _validate_telemetry(telemetry)
        observations = _validate_observed_mask(observed_mask, frame)
        mask = _validated_mask(fit_mask, len(frame))
        candidates = [name for name in frame.columns if name not in {"unit_id", "cycle"}]
        if not candidates:
            raise ValueError("telemetry must contain sensor or operating-setting columns")

        selected, dropped = [], []
        for name in candidates:
            eligible = mask & observations[name].to_numpy(dtype=bool, copy=False)
            values = frame.loc[eligible, name]
            variance = float(values.var(ddof=0)) if len(values) else float("nan")
            unique_values = int(values.nunique(dropna=False))
            (selected if unique_values > 1 and np.isfinite(variance)
             and variance > self.config.variance_epsilon else dropped).append(name)
        if not selected:
            raise ValueError(
                "all telemetry columns are constant or unobserved in the fitting population"
            )

        self.raw_columns = tuple(selected)
        self.dropped_constant_columns = tuple(dropped)
        generated = self._generate_receiver(frame, observations)
        feature_names = [name for name in generated.columns if name not in {"unit_id", "cycle"}]
        medians: dict[str, float] = {}
        for name in feature_names:
            values = generated.loc[mask, name]
            if not values.notna().any():
                raise ValueError(f"feature has no finite fitting values: {name}")
            median = float(values.median())
            if not np.isfinite(median):
                raise ValueError(f"feature median is not finite: {name}")
            medians[name] = median
        validate_feature_names(feature_names)
        self.feature_names = tuple(feature_names)
        self.imputation_medians = medians
        self._fitted = True
        return self

    def transform_frame(self, telemetry: pd.DataFrame) -> pd.DataFrame:
        if not self._fitted:
            raise RuntimeError("feature engineer must be fitted before transform")
        frame = _validate_telemetry(telemetry, required_value_columns=self.raw_columns)
        generated = self._generate(frame)
        if tuple(name for name in generated.columns if name not in {"unit_id", "cycle"}) != self.feature_names:
            raise RuntimeError("generated feature schema differs from fitted schema")
        generated.loc[:, self.feature_names] = generated.loc[:, self.feature_names].fillna(
            self.imputation_medians
        )
        values = generated.loc[:, self.feature_names].to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise ValueError("feature transformation produced non-finite values")
        return generated

    def transform_receiver_frame(
        self, telemetry: pd.DataFrame, observed_mask: pd.DataFrame,
    ) -> pd.DataFrame:
        """Transform a causal receiver state without treating holds as samples."""

        if not self._fitted:
            raise RuntimeError("feature engineer must be fitted before transform")
        frame = _validate_telemetry(telemetry, required_value_columns=self.raw_columns)
        observations = _validate_observed_mask(observed_mask, frame)
        generated = self._generate_receiver(frame, observations)
        if tuple(name for name in generated.columns if name not in {"unit_id", "cycle"}) != self.feature_names:
            raise RuntimeError("generated feature schema differs from fitted schema")
        generated.loc[:, self.feature_names] = generated.loc[:, self.feature_names].fillna(
            self.imputation_medians
        )
        values = generated.loc[:, self.feature_names].to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise ValueError("feature transformation produced non-finite values")
        return generated

    def manifest(self) -> dict[str, object]:
        if not self._fitted:
            raise RuntimeError("feature engineer is not fitted")
        return {
            "schema": self.artifact_schema,
            "configuration": {**asdict(self.config), "windows": list(self.config.windows)},
            "raw_columns": list(self.raw_columns),
            "dropped_constant_columns": list(self.dropped_constant_columns),
            "feature_names": list(self.feature_names),
            "feature_count": len(self.feature_names),
            "imputation": "per-feature median fitted on eligible training rows only",
            "causal_definitions": {
                "current": "x_t",
                "delta": "x_t - x_(t-1)",
                "relative_delta": "delta / x_(t-1) when abs(x_(t-1)) > epsilon",
                "rolling": "right-aligned window ending at t, never centered",
                "slope": "least-squares slope over the right-aligned window",
                "cumulative_abs_change": "sum from k=2..t of abs(x_k - x_(k-1))",
                "receiver_hold": (
                    "when a value is not newly observed, its previously generated sensor "
                    "features are held and its observation history is not updated"
                ),
                "receiver_slope": (
                    "least-squares slope over transmitted observations using their real cycles"
                ),
            },
        }

    def save(self, path: Path) -> None:
        payload = self.manifest() | {"imputation_medians": self.imputation_medians}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                   indent=2, allow_nan=False) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Self:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema") != cls.artifact_schema:
            raise ValueError("incompatible causal feature artifact")
        config = payload["configuration"]
        instance = cls(CausalFeatureConfig(
            windows=tuple(config["windows"]),
            relative_epsilon=float(config["relative_epsilon"]),
            variance_epsilon=float(config["variance_epsilon"]),
            include_cycle=bool(config["include_cycle"]),
        ))
        instance.raw_columns = tuple(payload["raw_columns"])
        instance.dropped_constant_columns = tuple(payload["dropped_constant_columns"])
        instance.feature_names = tuple(payload["feature_names"])
        instance.imputation_medians = {
            str(name): float(value) for name, value in payload["imputation_medians"].items()
        }
        if set(instance.imputation_medians) != set(instance.feature_names):
            raise ValueError("imputation schema does not match feature names")
        validate_feature_names(instance.feature_names)
        instance._fitted = True
        return instance

    def _generate(self, frame: pd.DataFrame) -> pd.DataFrame:
        unit_values = frame["unit_id"].to_numpy()
        groups = [np.asarray(index, dtype=int) for index in frame.groupby("unit_id", sort=False).indices.values()]
        output: dict[str, np.ndarray] = {
            "unit_id": unit_values.copy(),
            "cycle": frame["cycle"].to_numpy(dtype=np.int64, copy=True),
        }
        if self.config.include_cycle:
            output["age_cycle"] = frame["cycle"].to_numpy(dtype=float, copy=True)
        for column in self.raw_columns:
            values = frame[column].to_numpy(dtype=float, copy=False)
            current = values.copy()
            delta = np.full(len(frame), np.nan, dtype=float)
            relative = np.full(len(frame), np.nan, dtype=float)
            cumulative = np.zeros(len(frame), dtype=float)
            output[f"{column}__current"] = current
            for positions in groups:
                local = values[positions]
                local_delta = np.diff(local, prepend=np.nan)
                delta[positions] = local_delta
                previous = np.roll(local, 1)
                previous[0] = np.nan
                valid = np.abs(previous) > self.config.relative_epsilon
                local_relative = np.full(len(local), np.nan, dtype=float)
                local_relative[valid] = local_delta[valid] / previous[valid]
                relative[positions] = local_relative
                cumulative[positions] = np.cumsum(
                    np.nan_to_num(np.abs(local_delta), nan=0.0)
                )
            output[f"{column}__delta"] = delta
            output[f"{column}__relative_delta"] = relative
            output[f"{column}__cumulative_abs_change"] = cumulative
            for window in self.config.windows:
                mean = np.empty(len(frame), dtype=float)
                std = np.empty(len(frame), dtype=float)
                minimum = np.empty(len(frame), dtype=float)
                maximum = np.empty(len(frame), dtype=float)
                slope = np.full(len(frame), np.nan, dtype=float)
                for positions in groups:
                    local = values[positions]
                    series = pd.Series(local)
                    rolling = series.rolling(window=window, min_periods=1)
                    mean[positions] = rolling.mean().to_numpy()
                    std[positions] = rolling.std(ddof=0).to_numpy()
                    minimum[positions] = rolling.min().to_numpy()
                    maximum[positions] = rolling.max().to_numpy()
                    slope[positions] = _causal_rolling_slope(local, window)
                suffix = f"w{window}"
                output[f"{column}__mean_{suffix}"] = mean
                output[f"{column}__std_{suffix}"] = std
                output[f"{column}__min_{suffix}"] = minimum
                output[f"{column}__max_{suffix}"] = maximum
                output[f"{column}__slope_{suffix}"] = slope
        return pd.DataFrame(output, index=frame.index)

    def _generate_receiver(
        self, frame: pd.DataFrame, observed_mask: pd.DataFrame,
    ) -> pd.DataFrame:
        """Generate temporal features from receiver-visible observation events."""

        # Preserve byte-for-byte numerical behavior and model compatibility for
        # the unfiltered case, including the original slope implementation.
        if observed_mask.loc[:, self.raw_columns].to_numpy(dtype=bool).all():
            return self._generate(frame)

        groups = [
            np.asarray(index, dtype=int)
            for index in frame.groupby("unit_id", sort=False).indices.values()
        ]
        output: dict[str, np.ndarray] = {
            "unit_id": frame["unit_id"].to_numpy(copy=True),
            "cycle": frame["cycle"].to_numpy(dtype=np.int64, copy=True),
        }
        if self.config.include_cycle:
            output["age_cycle"] = frame["cycle"].to_numpy(dtype=float, copy=True)

        row_count = len(frame)
        for column in self.raw_columns:
            feature_arrays: dict[str, np.ndarray] = {
                f"{column}__current": np.full(row_count, np.nan, dtype=float),
                f"{column}__delta": np.full(row_count, np.nan, dtype=float),
                f"{column}__relative_delta": np.full(row_count, np.nan, dtype=float),
                f"{column}__cumulative_abs_change": np.full(row_count, np.nan, dtype=float),
            }
            for window in self.config.windows:
                suffix = f"w{window}"
                for statistic in ("mean", "std", "min", "max", "slope"):
                    feature_arrays[f"{column}__{statistic}_{suffix}"] = np.full(
                        row_count, np.nan, dtype=float
                    )

            values = frame[column].to_numpy(dtype=float, copy=False)
            cycles = frame["cycle"].to_numpy(dtype=float, copy=False)
            observed = observed_mask[column].to_numpy(dtype=bool, copy=False)
            for positions in groups:
                history_cycles: list[float] = []
                history_values: list[float] = []
                cumulative = 0.0
                previous_state: dict[str, float] | None = None
                for position in positions:
                    if observed[position]:
                        value = float(values[position])
                        cycle = float(cycles[position])
                        delta = (
                            value - history_values[-1] if history_values else float("nan")
                        )
                        relative = float("nan")
                        if history_values and abs(history_values[-1]) > self.config.relative_epsilon:
                            relative = delta / history_values[-1]
                        if history_values:
                            cumulative += abs(delta)
                        history_cycles.append(cycle)
                        history_values.append(value)
                        state: dict[str, float] = {
                            f"{column}__current": value,
                            f"{column}__delta": delta,
                            f"{column}__relative_delta": relative,
                            f"{column}__cumulative_abs_change": cumulative,
                        }
                        for window in self.config.windows:
                            local_values = np.asarray(history_values[-window:], dtype=float)
                            local_cycles = np.asarray(history_cycles[-window:], dtype=float)
                            suffix = f"w{window}"
                            state[f"{column}__mean_{suffix}"] = float(local_values.mean())
                            state[f"{column}__std_{suffix}"] = float(local_values.std(ddof=0))
                            state[f"{column}__min_{suffix}"] = float(local_values.min())
                            state[f"{column}__max_{suffix}"] = float(local_values.max())
                            state[f"{column}__slope_{suffix}"] = _least_squares_slope(
                                local_cycles, local_values
                            )
                        previous_state = state

                    # A hold copies the complete last feature state. It neither
                    # appends a value nor advances rolling/cumulative statistics.
                    if previous_state is not None:
                        for name, value in previous_state.items():
                            feature_arrays[name][position] = value

            output.update(feature_arrays)
        return pd.DataFrame(output, index=frame.index)


def _causal_rolling_slope(values: np.ndarray, window: int) -> np.ndarray:
    result = np.full(len(values), np.nan, dtype=float)
    for end in range(1, len(values)):
        start = max(0, end - window + 1)
        y = values[start:end + 1]
        x = np.arange(len(y), dtype=float)
        denominator = len(y) * float(np.dot(x, x)) - float(x.sum() ** 2)
        if denominator > 0:
            result[end] = (len(y) * float(np.dot(x, y)) - float(x.sum() * y.sum())) / denominator
    return result


def _least_squares_slope(cycles: np.ndarray, values: np.ndarray) -> float:
    """Return an OLS slope on real cycle coordinates, or NaN for one point."""

    if len(values) < 2:
        return float("nan")
    centered_cycles = cycles - float(cycles.mean())
    denominator = float(np.dot(centered_cycles, centered_cycles))
    if denominator <= 0:
        return float("nan")
    centered_values = values - float(values.mean())
    return float(np.dot(centered_cycles, centered_values) / denominator)


def _validated_mask(mask: Sequence[bool] | None, length: int) -> np.ndarray:
    if mask is None:
        result = np.ones(length, dtype=bool)
    else:
        result = np.asarray(mask)
        if result.ndim != 1 or len(result) != length or result.dtype != bool:
            raise ValueError("fit_mask must be a boolean vector aligned with telemetry")
    if not result.any():
        raise ValueError("fit_mask must select at least one row")
    return result


def _validate_observed_mask(
    observed_mask: pd.DataFrame, telemetry: pd.DataFrame,
) -> pd.DataFrame:
    """Validate exact row/column alignment of receiver observation flags."""

    if not isinstance(observed_mask, pd.DataFrame):
        raise ValueError("observed_mask must be a DataFrame")
    value_columns = [name for name in telemetry.columns if name not in {"unit_id", "cycle"}]
    if list(observed_mask.columns) != value_columns:
        raise ValueError(
            "observed_mask columns must exactly match telemetry value columns in order"
        )
    if not observed_mask.index.equals(telemetry.index):
        raise ValueError("observed_mask index must be aligned with telemetry")
    if observed_mask.isna().any().any() or any(
        not pd.api.types.is_bool_dtype(dtype) for dtype in observed_mask.dtypes
    ):
        raise ValueError("observed_mask values must be non-missing booleans")
    return observed_mask.copy()


def _validate_telemetry(
    telemetry: pd.DataFrame, *, required_value_columns: Sequence[str] | None = None,
) -> pd.DataFrame:
    if not isinstance(telemetry, pd.DataFrame) or telemetry.empty:
        raise ValueError("telemetry must be a non-empty DataFrame")
    if not {"unit_id", "cycle"} <= set(telemetry.columns):
        raise ValueError("telemetry requires unit_id and cycle")
    frame = telemetry.copy()
    required = tuple(required_value_columns or ())
    missing = set(required) - set(frame.columns)
    if missing:
        raise ValueError(f"telemetry is missing fitted raw columns: {sorted(missing)}")
    columns = [name for name in frame.columns if name not in {"unit_id", "cycle"}]
    validate_feature_names(columns)
    if frame[["unit_id", "cycle"]].isna().any().any() or frame.duplicated(["unit_id", "cycle"]).any():
        raise ValueError("telemetry keys must be non-missing and unique")
    for name in ["unit_id", "cycle", *columns]:
        values = pd.to_numeric(frame[name], errors="coerce")
        if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
            raise ValueError(f"telemetry column must be finite numeric: {name}")
        frame[name] = values
    if (frame[["unit_id", "cycle"]] <= 0).any().any():
        raise ValueError("unit_id and cycle must be positive")
    if frame.unit_id.mod(1).ne(0).any() or frame.cycle.mod(1).ne(0).any():
        raise ValueError("unit_id and cycle must be integers")
    frame["unit_id"] = frame.unit_id.astype("int64")
    frame["cycle"] = frame.cycle.astype("int64")
    for _, unit in frame.groupby("unit_id", sort=False):
        cycles = unit.cycle.to_numpy()
        if len(cycles) > 1 and not np.all(np.diff(cycles) == 1):
            raise ValueError("each unit must be ordered in consecutive increasing cycles")
    return frame


def _records_to_frame(records: Sequence[TelemetryRecord]) -> pd.DataFrame:
    if not records:
        raise ValueError("telemetry records must not be empty")
    rows = [{"unit_id": record.unit_id, "cycle": record.cycle, **dict(record.values)}
            for record in records]
    return pd.DataFrame(rows)
