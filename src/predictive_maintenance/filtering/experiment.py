"""Causal reconstruction helpers for local telemetry-reduction experiments."""

from __future__ import annotations

from dataclasses import dataclass, fields
from math import isfinite
from typing import Mapping

import numpy as np
import pandas as pd

from predictive_maintenance.core.records import TelemetryRecord
from predictive_maintenance.filtering.policies import (
    AdaptiveTelemetryConfig,
    AdaptiveTelemetryFilter,
    FixedIntervalFilter,
    FullTelemetryFilter,
    SensorSubsetFilter,
    TelemetryReceiver,
)


@dataclass(frozen=True)
class ReceiverReconstruction:
    """State actually available at the receiver plus explicit provenance."""

    values: pd.DataFrame
    observed_mask: pd.DataFrame
    states: pd.DataFrame
    packets: pd.DataFrame
    communication_metrics: Mapping[str, object]
    resolved_policy: Mapping[str, object]


def adaptive_relative_threshold(
    training: pd.DataFrame,
    sensors: tuple[str, ...],
    quantile: float,
    *,
    epsilon: float = 1e-12,
) -> float:
    """Estimate one cheap relative-change trigger from training prefixes only."""
    if not 0.0 < quantile < 1.0:
        raise ValueError("relative-change quantile must be in (0, 1)")
    if not sensors or not set(sensors) <= set(training.columns):
        raise ValueError("adaptive monitored sensors must exist in training")
    if not isfinite(epsilon) or epsilon <= 0:
        raise ValueError("epsilon must be finite and positive")
    values: list[np.ndarray] = []
    ordered = _validated_source(training)
    for sensor in sensors:
        previous = ordered.groupby("unit_id", sort=False)[sensor].shift(1)
        valid = previous.notna()
        relative = (ordered.loc[valid, sensor] - previous.loc[valid]).abs()
        relative = relative / np.maximum(previous.loc[valid].abs(), epsilon)
        values.append(relative.to_numpy(dtype=float))
    pooled = np.concatenate(values)
    if len(pooled) == 0 or not np.isfinite(pooled).all():
        raise ValueError("training relative changes are unavailable or non-finite")
    return float(np.quantile(pooled, quantile, method="linear"))


def build_filter(
    policy: Mapping[str, object],
    *,
    training_reference: pd.DataFrame,
    accounting: Mapping[str, object],
    stale_after_cycles: int,
    inference_cadence: str = "each_cycle",
):
    """Resolve train-derived policy parameters and construct a fresh filter."""
    kind = str(policy["kind"])
    policy_id = str(policy["id"])
    source = _validated_source(training_reference)
    value_columns = tuple(name for name in source.columns if name not in {"unit_id", "cycle"})
    kwargs = {
        "metadata_overhead_bytes": int(accounting["metadata_overhead_bytes"]),
        "value_bytes": int(accounting["value_bytes"]),
    }
    resolved: dict[str, object] = {"id": policy_id, "kind": kind}
    if kind == "full":
        instance = FullTelemetryFilter(receiver=TelemetryReceiver(
            required_sensors=value_columns, stale_after_cycles=stale_after_cycles,
            inference_cadence=inference_cadence), **kwargs)
    elif kind == "fixed_interval":
        interval = int(policy["interval_cycles"])
        resolved["interval_cycles"] = interval
        instance = FixedIntervalFilter(interval_cycles=interval, receiver=TelemetryReceiver(
            required_sensors=value_columns, stale_after_cycles=stale_after_cycles,
            inference_cadence=inference_cadence), **kwargs)
    elif kind == "sensor_subset":
        selected = tuple(str(value) for value in policy["selected_sensors"])
        missing = set(selected) - set(value_columns)
        if missing:
            raise ValueError(f"selected train sensors are missing: {sorted(missing)}")
        resolved.update({"selected_sensors": list(selected),
                         "selection_source": str(policy["selection_source"])})
        instance = SensorSubsetFilter(
            selected_sensors=selected, selection_source="train",
            receiver=TelemetryReceiver(required_sensors=selected,
                stale_after_cycles=stale_after_cycles,
                inference_cadence=inference_cadence), **kwargs)
    elif kind == "adaptive":
        sensors = tuple(str(value) for value in policy["monitored_sensors"])
        quantile = float(policy["relative_change_quantile"])
        threshold = adaptive_relative_threshold(source, sensors, quantile)
        config = AdaptiveTelemetryConfig(
            stable_interval_cycles=int(policy["stable_interval_cycles"]),
            high_frequency_interval_cycles=int(policy["high_frequency_interval_cycles"]),
            high_frequency_duration_cycles=int(policy["high_frequency_duration_cycles"]),
            monitored_sensors=sensors,
            relative_change_threshold=threshold,
        )
        resolved.update({
            "stable_interval_cycles": config.stable_interval_cycles,
            "high_frequency_interval_cycles": config.high_frequency_interval_cycles,
            "high_frequency_duration_cycles": config.high_frequency_duration_cycles,
            "monitored_sensors": list(sensors),
            "relative_change_quantile": quantile,
            "relative_change_threshold": threshold,
            "threshold_source": "training_reference_only",
        })
        instance = AdaptiveTelemetryFilter(config=config, receiver=TelemetryReceiver(
            required_sensors=value_columns, stale_after_cycles=stale_after_cycles,
            inference_cadence=inference_cadence), **kwargs)
    else:
        raise ValueError(f"unsupported telemetry policy kind: {kind}")
    return instance, resolved


def reconstruct_receiver_stream(
    source: pd.DataFrame,
    telemetry_filter,
    *,
    resolved_policy: Mapping[str, object],
) -> ReceiverReconstruction:
    """Run sender, packet and receiver sequentially without hidden-data joins."""
    frame = _validated_source(source)
    value_columns = tuple(name for name in frame.columns if name not in {"unit_id", "cycle"})
    records = [TelemetryRecord(
        unit_id=str(int(row.unit_id)), cycle=int(row.cycle),
        values={name: float(getattr(row, name)) for name in value_columns},
    ) for row in frame.itertuples(index=False)]
    results = telemetry_filter.filter(records)
    value_rows: list[dict[str, object]] = []
    mask_rows: list[dict[str, object]] = []
    state_rows: list[dict[str, object]] = []
    packet_rows: list[dict[str, object]] = []
    sensor_values_transmitted = 0
    setting_values_transmitted = 0
    for item in results:
        state = item.receiver_state
        values = {name: sensor.value for name, sensor in state.sensors.items()}
        if any(value is None for value in values.values()):
            # Every implemented policy sends all declared channels on the first unit cycle.
            raise RuntimeError("receiver lacks an initial value for a declared channel")
        value_rows.append({"unit_id": int(state.unit_id), "cycle": state.cycle, **values})
        mask_rows.append({"unit_id": int(state.unit_id), "cycle": state.cycle,
                          **{name: sensor.was_transmitted_this_cycle
                             for name, sensor in state.sensors.items()}})
        ages = [sensor.sensor_age_cycles for sensor in state.sensors.values()
                if sensor.sensor_age_cycles is not None]
        state_rows.append({
            "unit_id": int(state.unit_id), "cycle": state.cycle,
            "logical_timestamp": state.logical_timestamp,
            "packet_received": state.packet_received,
            "inference_due": state.inference_due,
            "telemetry_stale": state.telemetry_stale,
            "max_sensor_age_cycles": int(max(ages, default=0)),
            "observed_value_count": int(sum(
                sensor.was_transmitted_this_cycle for sensor in state.sensors.values())),
            "held_value_count": int(sum(
                sensor.value_validity == "valid_held" for sensor in state.sensors.values())),
            "stale_value_count": int(sum(
                sensor.value_validity == "stale" for sensor in state.sensors.values())),
            "unavailable_value_count": int(sum(
                sensor.value_validity == "unavailable" for sensor in state.sensors.values())),
        })
        if item.packet is not None:
            names = tuple(item.packet.transmitted_sensors)
            sensor_values_transmitted += sum(name.startswith("sensor_") for name in names)
            setting_values_transmitted += sum(name.startswith("setting_") for name in names)
            packet_rows.append({
                "unit_id": int(item.packet.unit_id), "cycle": item.packet.cycle,
                "logical_timestamp": item.packet.logical_timestamp,
                "transmitted_sensors": list(names), "value_count": item.packet.value_count,
                "estimated_bytes": item.packet.estimated_bytes,
                "send_reason": item.packet.send_reason, "policy": item.packet.policy,
            })
    values_frame = pd.DataFrame(value_rows)
    observed_frame = pd.DataFrame(mask_rows)
    states = pd.DataFrame(state_rows)
    packets = pd.DataFrame(packet_rows)
    if not values_frame[["unit_id", "cycle"]].equals(frame[["unit_id", "cycle"]]):
        raise RuntimeError("receiver keys differ from source keys")
    metric_record = telemetry_filter.metrics
    metrics = {field.name: getattr(metric_record, field.name) for field in fields(metric_record)}
    metrics["adaptive_activation_reasons"] = dict(metrics["adaptive_activation_reasons"])
    generated = len(frame)
    metrics.update({
        "sensor_values_transmitted": sensor_values_transmitted,
        "setting_values_transmitted": setting_values_transmitted,
        "sensor_transmission_fraction": (
            sensor_values_transmitted / (21 * generated) if generated else 0.0),
        "setting_transmission_fraction": (
            setting_values_transmitted / (3 * generated) if generated else 0.0),
        "packet_fraction": metrics["observations_transmitted"] / generated if generated else 0.0,
    })
    return ReceiverReconstruction(
        values=values_frame, observed_mask=observed_frame, states=states,
        packets=packets, communication_metrics=metrics,
        resolved_policy=dict(resolved_policy),
    )


def _validated_source(source: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(source, pd.DataFrame) or source.empty:
        raise ValueError("source telemetry must be a non-empty DataFrame")
    if not {"unit_id", "cycle"} <= set(source.columns):
        raise ValueError("source telemetry requires unit_id and cycle")
    frame = source.copy().sort_values(["unit_id", "cycle"]).reset_index(drop=True)
    if frame.duplicated(["unit_id", "cycle"]).any():
        raise ValueError("source telemetry keys must be unique")
    numeric = frame.apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any() or not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise ValueError("source telemetry must be finite numeric")
    for _, unit in numeric.groupby("unit_id", sort=False):
        if len(unit) > 1 and not np.all(np.diff(unit.cycle.to_numpy(dtype=int)) == 1):
            raise ValueError("source cycles must be consecutive within each unit")
    numeric["unit_id"] = numeric.unit_id.astype(int)
    numeric["cycle"] = numeric.cycle.astype(int)
    return numeric
