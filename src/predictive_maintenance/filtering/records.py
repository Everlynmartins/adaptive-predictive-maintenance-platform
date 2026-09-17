"""Immutable records emitted by the local telemetry filtering layer."""

from dataclasses import dataclass, field
from math import isfinite
from numbers import Real
from types import MappingProxyType
from typing import Literal, Mapping


ValueValidity = Literal["valid_observed", "valid_held", "stale", "unavailable"]


@dataclass(frozen=True, kw_only=True)
class TelemetryPacket:
    unit_id: str
    cycle: int
    logical_timestamp: int
    transmitted_values: Mapping[str, float]
    estimated_bytes: int
    send_reason: str
    policy: str
    transmitted_sensors: tuple[str, ...] = field(init=False)
    value_count: int = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.unit_id, str) or not self.unit_id.strip():
            raise ValueError("unit_id must be a non-empty string")
        if type(self.cycle) is not int or self.cycle <= 0:
            raise ValueError("cycle must be a positive integer")
        if type(self.logical_timestamp) is not int or self.logical_timestamp < 0:
            raise ValueError("logical_timestamp must be a non-negative integer")
        if type(self.estimated_bytes) is not int or self.estimated_bytes < 0:
            raise ValueError("estimated_bytes must be a non-negative integer")
        if not self.send_reason.strip() or not self.policy.strip():
            raise ValueError("send_reason and policy must be non-empty")
        values = dict(self.transmitted_values)
        if not values:
            raise ValueError("a packet must transmit at least one value")
        for name, value in values.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("sensor names must be non-empty strings")
            if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value):
                raise ValueError(f"{name} must be a finite real number")
        object.__setattr__(self, "transmitted_values", MappingProxyType(values))
        object.__setattr__(self, "transmitted_sensors", tuple(values))
        object.__setattr__(self, "value_count", len(values))


@dataclass(frozen=True, kw_only=True)
class SensorReceptionState:
    value: float | None
    last_observed_cycle: int | None
    sensor_age_cycles: int | None
    was_transmitted_this_cycle: bool
    value_validity: ValueValidity


@dataclass(frozen=True, kw_only=True)
class ReceiverTelemetryState:
    unit_id: str
    cycle: int
    logical_timestamp: int
    sensors: Mapping[str, SensorReceptionState]
    telemetry_stale: bool
    inference_due: bool
    packet_received: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "sensors", MappingProxyType(dict(self.sensors)))


@dataclass(frozen=True, kw_only=True)
class TelemetryFilterResult:
    packet: TelemetryPacket | None
    receiver_state: ReceiverTelemetryState


@dataclass(frozen=True, kw_only=True)
class TelemetryFilterMetrics:
    policy: str
    observations_generated: int
    observations_transmitted: int
    values_transmitted: int
    estimated_bytes: int
    full_telemetry_estimated_bytes: int
    byte_reduction_fraction: float
    effective_frequency: float
    policy_time_seconds: float
    adaptive_activations: int = 0
    adaptive_activation_reasons: Mapping[str, int] = field(default_factory=dict)
    high_frequency_cycles: int = 0
    high_frequency_durations: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "adaptive_activation_reasons",
            MappingProxyType(dict(self.adaptive_activation_reasons)),
        )
