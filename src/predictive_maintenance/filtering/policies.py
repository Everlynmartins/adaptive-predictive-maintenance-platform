"""Causal local filtering policies and hold-last-value receiver semantics."""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from math import isfinite
from numbers import Real
from statistics import pstdev
from time import perf_counter
import re
from typing import Mapping, Sequence

from predictive_maintenance.core.causality import validate_feature_names
from predictive_maintenance.core.records import TelemetryRecord
from predictive_maintenance.filtering.interfaces import TelemetryFilter
from predictive_maintenance.filtering.records import (
    ReceiverTelemetryState,
    SensorReceptionState,
    TelemetryFilterMetrics,
    TelemetryFilterResult,
    TelemetryPacket,
)


_PROHIBITED_RUNTIME_FIELDS = frozenset({
    "label", "target", "event", "event_observed", "failure", "rul_target",
})
_INFERENCE_CADENCES = frozenset({"each_cycle", "on_transmission"})


class TelemetryReceiver:
    """Maintain the last actually transmitted value for each required sensor."""

    def __init__(
        self,
        *,
        required_sensors: Sequence[str] | None = None,
        stale_after_cycles: int = 3,
        inference_cadence: str = "each_cycle",
    ) -> None:
        if type(stale_after_cycles) is not int or stale_after_cycles < 0:
            raise ValueError("stale_after_cycles must be a non-negative integer")
        if inference_cadence not in _INFERENCE_CADENCES:
            raise ValueError(f"inference_cadence must be one of {sorted(_INFERENCE_CADENCES)}")
        if required_sensors is not None:
            required = tuple(required_sensors)
            if not required or len(set(required)) != len(required):
                raise ValueError("required_sensors must be non-empty and unique")
            _validate_names(required)
        else:
            required = None
        self._configured_sensors = required
        self.stale_after_cycles = stale_after_cycles
        self.inference_cadence = inference_cadence
        self.reset()

    def reset(self) -> None:
        self._required_sensors = self._configured_sensors
        self._known: dict[str, dict[str, tuple[float, int]]] = defaultdict(dict)

    def receive(
        self,
        *,
        unit_id: str,
        cycle: int,
        logical_timestamp: int,
        packet: TelemetryPacket | None,
        declared_sensors: Sequence[str],
    ) -> ReceiverTelemetryState:
        declared = tuple(declared_sensors)
        if self._required_sensors is None:
            if not declared:
                raise ValueError("receiver requires at least one declared sensor")
            _validate_names(declared)
            self._required_sensors = declared
        elif set(declared) != set(self._required_sensors):
            raise ValueError("declared sensor schema changed during sequential processing")

        transmitted = {} if packet is None else dict(packet.transmitted_values)
        unknown = set(transmitted).difference(self._required_sensors)
        if unknown:
            raise ValueError(f"packet contains undeclared sensors: {sorted(unknown)}")
        known = self._known[unit_id]
        states: dict[str, SensorReceptionState] = {}
        for sensor in self._required_sensors:
            if sensor in transmitted:
                value = float(transmitted[sensor])
                known[sensor] = (value, cycle)
                states[sensor] = SensorReceptionState(
                    value=value,
                    last_observed_cycle=cycle,
                    sensor_age_cycles=0,
                    was_transmitted_this_cycle=True,
                    value_validity="valid_observed",
                )
                continue
            if sensor not in known:
                states[sensor] = SensorReceptionState(
                    value=None,
                    last_observed_cycle=None,
                    sensor_age_cycles=None,
                    was_transmitted_this_cycle=False,
                    value_validity="unavailable",
                )
                continue
            value, observed_cycle = known[sensor]
            age = cycle - observed_cycle
            validity = "stale" if age > self.stale_after_cycles else "valid_held"
            states[sensor] = SensorReceptionState(
                value=value,
                last_observed_cycle=observed_cycle,
                sensor_age_cycles=age,
                was_transmitted_this_cycle=False,
                value_validity=validity,
            )
        stale = any(state.value_validity in {"stale", "unavailable"} for state in states.values())
        inference_due = (
            self.inference_cadence == "each_cycle" or packet is not None
        )
        return ReceiverTelemetryState(
            unit_id=unit_id,
            cycle=cycle,
            logical_timestamp=logical_timestamp,
            sensors=states,
            telemetry_stale=stale,
            inference_due=inference_due,
            packet_received=packet is not None,
        )


class _SequentialTelemetryFilter(TelemetryFilter):
    def __init__(
        self,
        *,
        policy_name: str,
        receiver: TelemetryReceiver | None = None,
        metadata_overhead_bytes: int = 32,
        value_bytes: int = 8,
    ) -> None:
        for name, value in {
            "metadata_overhead_bytes": metadata_overhead_bytes,
            "value_bytes": value_bytes,
        }.items():
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if value_bytes == 0:
            raise ValueError("value_bytes must be positive")
        self.policy_name = policy_name
        self.receiver = receiver or TelemetryReceiver()
        self.metadata_overhead_bytes = metadata_overhead_bytes
        self.value_bytes = value_bytes
        self.reset()

    def reset(self) -> None:
        self.receiver.reset()
        self._last_cycle: dict[str, int] = {}
        self._input_schema: tuple[str, ...] | None = None
        self._observations_generated = 0
        self._observations_transmitted = 0
        self._values_transmitted = 0
        self._estimated_bytes = 0
        self._full_bytes = 0
        self._policy_time_seconds = 0.0
        self._reset_policy()

    def _reset_policy(self) -> None:
        pass

    def filter(self, telemetry: Sequence[TelemetryRecord]) -> list[TelemetryFilterResult]:
        self.reset()
        return [self.process(observation) for observation in telemetry]

    def process(
        self,
        observation: TelemetryRecord,
        *,
        logical_timestamp: int | None = None,
        anomaly_score: float | None = None,
    ) -> TelemetryFilterResult:
        values = _validate_observation(observation)
        timestamp = observation.cycle if logical_timestamp is None else logical_timestamp
        if type(timestamp) is not int or timestamp < 0:
            raise ValueError("logical_timestamp must be a non-negative integer")
        last_cycle = self._last_cycle.get(observation.unit_id)
        if last_cycle is not None and observation.cycle <= last_cycle:
            raise ValueError("cycles must be strictly increasing within each unit")
        schema = tuple(values)
        if self._input_schema is None:
            self._input_schema = schema
        elif set(schema) != set(self._input_schema):
            raise ValueError("input telemetry schema changed during sequential processing")

        start = perf_counter()
        selected, reason = self._select_values(observation, values, anomaly_score)
        elapsed = perf_counter() - start
        packet = None
        if selected:
            estimated = self.metadata_overhead_bytes + self.value_bytes * len(selected)
            packet = TelemetryPacket(
                unit_id=observation.unit_id,
                cycle=observation.cycle,
                logical_timestamp=timestamp,
                transmitted_values=selected,
                estimated_bytes=estimated,
                send_reason=reason,
                policy=self.policy_name,
            )
            self._observations_transmitted += 1
            self._values_transmitted += packet.value_count
            self._estimated_bytes += estimated

        declared = self._declared_receiver_sensors(values)
        state = self.receiver.receive(
            unit_id=observation.unit_id,
            cycle=observation.cycle,
            logical_timestamp=timestamp,
            packet=packet,
            declared_sensors=declared,
        )
        self._last_cycle[observation.unit_id] = observation.cycle
        self._observations_generated += 1
        self._full_bytes += self.metadata_overhead_bytes + self.value_bytes * len(values)
        self._policy_time_seconds += elapsed
        self._after_observation(observation, values, packet)
        return TelemetryFilterResult(packet=packet, receiver_state=state)

    def _declared_receiver_sensors(self, values: Mapping[str, float]) -> tuple[str, ...]:
        return tuple(values)

    def _after_observation(
        self,
        observation: TelemetryRecord,
        values: Mapping[str, float],
        packet: TelemetryPacket | None,
    ) -> None:
        pass

    def _select_values(
        self,
        observation: TelemetryRecord,
        values: Mapping[str, float],
        anomaly_score: float | None,
    ) -> tuple[Mapping[str, float] | None, str]:
        raise NotImplementedError

    @property
    def metrics(self) -> TelemetryFilterMetrics:
        generated = self._observations_generated
        frequency = self._observations_transmitted / generated if generated else 0.0
        reduction = 1.0 - self._estimated_bytes / self._full_bytes if self._full_bytes else 0.0
        extras = self._adaptive_metric_fields()
        return TelemetryFilterMetrics(
            policy=self.policy_name,
            observations_generated=generated,
            observations_transmitted=self._observations_transmitted,
            values_transmitted=self._values_transmitted,
            estimated_bytes=self._estimated_bytes,
            full_telemetry_estimated_bytes=self._full_bytes,
            byte_reduction_fraction=reduction,
            effective_frequency=frequency,
            policy_time_seconds=self._policy_time_seconds,
            **extras,
        )

    def _adaptive_metric_fields(self) -> dict[str, object]:
        return {}


class FullTelemetryFilter(_SequentialTelemetryFilter):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(policy_name="full", **kwargs)

    def _select_values(self, observation, values, anomaly_score):
        return dict(values), "full_telemetry"


class FixedIntervalFilter(_SequentialTelemetryFilter):
    def __init__(self, *, interval_cycles: int, **kwargs: object) -> None:
        if type(interval_cycles) is not int or interval_cycles <= 0:
            raise ValueError("interval_cycles must be a positive integer")
        self.interval_cycles = interval_cycles
        super().__init__(policy_name="fixed_interval", **kwargs)

    def _reset_policy(self) -> None:
        self._last_transmitted_cycle: dict[str, int] = {}

    def _select_values(self, observation, values, anomaly_score):
        last = self._last_transmitted_cycle.get(observation.unit_id)
        if last is None or observation.cycle - last >= self.interval_cycles:
            self._last_transmitted_cycle[observation.unit_id] = observation.cycle
            reason = "initial_observation" if last is None else "fixed_interval_due"
            return dict(values), reason
        return None, "fixed_interval_hold"


class SensorSubsetFilter(_SequentialTelemetryFilter):
    def __init__(
        self,
        *,
        selected_sensors: Sequence[str],
        selection_source: str = "train",
        **kwargs: object,
    ) -> None:
        selected = tuple(selected_sensors)
        if not selected or len(set(selected)) != len(selected):
            raise ValueError("selected_sensors must be non-empty and unique")
        _validate_names(selected)
        if selection_source != "train":
            raise ValueError("sensor subset decisions must have selection_source='train'")
        self.selected_sensors = selected
        self.selection_source = selection_source
        receiver = kwargs.pop("receiver", None)
        if receiver is None:
            receiver = TelemetryReceiver(required_sensors=selected)
        super().__init__(policy_name="sensor_subset", receiver=receiver, **kwargs)

    def _declared_receiver_sensors(self, values: Mapping[str, float]) -> tuple[str, ...]:
        missing = set(self.selected_sensors).difference(values)
        if missing:
            raise ValueError(f"selected sensors absent from input: {sorted(missing)}")
        return self.selected_sensors

    def _select_values(self, observation, values, anomaly_score):
        missing = set(self.selected_sensors).difference(values)
        if missing:
            raise ValueError(f"selected sensors absent from input: {sorted(missing)}")
        return {name: values[name] for name in self.selected_sensors}, "sensor_subset"


@dataclass(frozen=True, kw_only=True)
class AdaptiveTelemetryConfig:
    stable_interval_cycles: int = 5
    high_frequency_interval_cycles: int = 1
    high_frequency_duration_cycles: int = 5
    monitored_sensors: tuple[str, ...] | None = None
    absolute_change_threshold: float | None = None
    relative_change_threshold: float | None = None
    relative_epsilon: float = 1e-12
    moving_window: int = 5
    moving_deviation_threshold: float | None = None
    variation_window: int = 5
    variation_threshold: float | None = None
    anomaly_score_threshold: float | None = None

    def __post_init__(self) -> None:
        for name in (
            "stable_interval_cycles", "high_frequency_interval_cycles",
            "high_frequency_duration_cycles", "moving_window", "variation_window",
        ):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.monitored_sensors is not None:
            if not self.monitored_sensors or len(set(self.monitored_sensors)) != len(self.monitored_sensors):
                raise ValueError("monitored_sensors must be non-empty and unique")
            _validate_names(self.monitored_sensors)
        for name in (
            "absolute_change_threshold", "relative_change_threshold",
            "moving_deviation_threshold", "variation_threshold",
            "anomaly_score_threshold",
        ):
            value = getattr(self, name)
            if value is not None and (not isfinite(value) or value < 0):
                raise ValueError(f"{name} must be finite and non-negative")
        if not isfinite(self.relative_epsilon) or self.relative_epsilon <= 0:
            raise ValueError("relative_epsilon must be finite and positive")


class AdaptiveTelemetryFilter(_SequentialTelemetryFilter):
    def __init__(self, *, config: AdaptiveTelemetryConfig, **kwargs: object) -> None:
        self.config = config
        super().__init__(policy_name="adaptive", **kwargs)

    def _reset_policy(self) -> None:
        history_size = max(self.config.moving_window, self.config.variation_window) + 1
        self._history: dict[str, dict[str, deque[float]]] = defaultdict(
            lambda: defaultdict(lambda: deque(maxlen=history_size))
        )
        self._last_transmitted_cycle: dict[str, int] = {}
        self._high_until: dict[str, int] = {}
        self._adaptive_activations = 0
        self._activation_reasons: Counter[str] = Counter()
        self._high_frequency_cycles = 0
        self._active_episode_lengths: dict[str, int] = {}
        self._completed_episode_lengths: list[int] = []

    def _select_values(self, observation, values, anomaly_score):
        sensors = self.config.monitored_sensors or tuple(values)
        missing = set(sensors).difference(values)
        if missing:
            raise ValueError(f"monitored sensors absent from input: {sorted(missing)}")
        triggers = self._change_triggers(observation.unit_id, values, sensors, anomaly_score)
        old_until = self._high_until.get(observation.unit_id, -1)
        was_high = observation.cycle <= old_until
        if triggers:
            new_until = observation.cycle + self.config.high_frequency_duration_cycles - 1
            self._high_until[observation.unit_id] = max(old_until, new_until)
            if not was_high:
                self._adaptive_activations += 1
                self._activation_reasons.update(triggers)
        high = observation.cycle <= self._high_until.get(observation.unit_id, -1)
        self._update_episode(observation.unit_id, high)
        if high:
            self._high_frequency_cycles += 1

        last = self._last_transmitted_cycle.get(observation.unit_id)
        interval = (
            self.config.high_frequency_interval_cycles if high
            else self.config.stable_interval_cycles
        )
        should_send = last is None or bool(triggers) or observation.cycle - last >= interval
        if should_send:
            self._last_transmitted_cycle[observation.unit_id] = observation.cycle
            if last is None:
                reason = "initial_observation"
            elif triggers:
                reason = "adaptive_activation:" + ",".join(triggers)
            elif high:
                reason = "adaptive_high_frequency"
            else:
                reason = "adaptive_stable_interval"
            return dict(values), reason
        return None, "adaptive_hold"

    def _change_triggers(
        self,
        unit_id: str,
        values: Mapping[str, float],
        sensors: Sequence[str],
        anomaly_score: float | None,
    ) -> list[str]:
        triggers: list[str] = []
        history = self._history[unit_id]
        for sensor in sensors:
            past = history[sensor]
            current = values[sensor]
            if past:
                previous = past[-1]
                if (self.config.absolute_change_threshold is not None
                        and abs(current - previous) >= self.config.absolute_change_threshold):
                    triggers.append(f"absolute_change:{sensor}")
                if self.config.relative_change_threshold is not None:
                    relative = abs(current - previous) / max(abs(previous), self.config.relative_epsilon)
                    if relative >= self.config.relative_change_threshold:
                        triggers.append(f"relative_change:{sensor}")
            if self.config.moving_deviation_threshold is not None and past:
                causal_window = list(past)[-self.config.moving_window:]
                mean = sum(causal_window) / len(causal_window)
                if abs(current - mean) >= self.config.moving_deviation_threshold:
                    triggers.append(f"moving_deviation:{sensor}")
            if self.config.variation_threshold is not None:
                prior_count = self.config.variation_window - 1
                prior_values = list(past)[-prior_count:] if prior_count else []
                causal_values = prior_values + [current]
                if len(causal_values) >= 2 and pstdev(causal_values) >= self.config.variation_threshold:
                    triggers.append(f"variation:{sensor}")
        if self.config.anomaly_score_threshold is not None:
            if anomaly_score is None:
                pass
            elif isinstance(anomaly_score, bool) or not isinstance(anomaly_score, Real) or not isfinite(anomaly_score):
                raise ValueError("anomaly_score must be a finite real number")
            elif anomaly_score >= self.config.anomaly_score_threshold:
                triggers.append("anomaly_score")
        return sorted(set(triggers))

    def _after_observation(self, observation, values, packet):
        history = self._history[observation.unit_id]
        for sensor, value in values.items():
            history[sensor].append(value)

    def _update_episode(self, unit_id: str, high: bool) -> None:
        if high:
            self._active_episode_lengths[unit_id] = self._active_episode_lengths.get(unit_id, 0) + 1
        elif unit_id in self._active_episode_lengths:
            self._completed_episode_lengths.append(self._active_episode_lengths.pop(unit_id))

    def _adaptive_metric_fields(self) -> dict[str, object]:
        durations = self._completed_episode_lengths + list(self._active_episode_lengths.values())
        return {
            "adaptive_activations": self._adaptive_activations,
            "adaptive_activation_reasons": dict(self._activation_reasons),
            "high_frequency_cycles": self._high_frequency_cycles,
            "high_frequency_durations": tuple(durations),
        }


def _validate_observation(observation: TelemetryRecord) -> dict[str, float]:
    if not isinstance(observation, TelemetryRecord):
        raise TypeError("observation must be a TelemetryRecord")
    if not isinstance(observation.unit_id, str) or not observation.unit_id.strip():
        raise ValueError("unit_id must be a non-empty string")
    if type(observation.cycle) is not int or observation.cycle <= 0:
        raise ValueError("cycle must be a positive integer")
    values = dict(observation.values)
    if not values:
        raise ValueError("telemetry observation must contain values")
    _validate_names(values)
    for name, value in values.items():
        if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value):
            raise ValueError(f"{name} must be a finite real number")
        values[name] = float(value)
    return values


def _validate_names(names: Sequence[str] | Mapping[str, object]) -> None:
    validate_feature_names(names)
    for name in names:
        canonical = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        if canonical in _PROHIBITED_RUNTIME_FIELDS or canonical.startswith(("target_", "label_")):
            raise ValueError(f"target or retrospective field forbidden in telemetry policy: {name}")
