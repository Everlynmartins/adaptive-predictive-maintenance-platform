"""Sequential telemetry filtering boundary independent of feature engineering."""

from abc import ABC, abstractmethod
from typing import Sequence

from predictive_maintenance.core.records import TelemetryRecord
from predictive_maintenance.filtering.records import TelemetryFilterMetrics, TelemetryFilterResult


class TelemetryFilter(ABC):
    @abstractmethod
    def process(
        self,
        observation: TelemetryRecord,
        *,
        logical_timestamp: int | None = None,
        anomaly_score: float | None = None,
    ) -> TelemetryFilterResult:
        """Process exactly one current observation without access to a suffix."""
        ...

    @abstractmethod
    def filter(self, telemetry: Sequence[TelemetryRecord]) -> list[TelemetryFilterResult]:
        """Reset and process an already ordered sequence one observation at a time."""
        ...

    @abstractmethod
    def reset(self) -> None:
        """Clear causal policy and receiver state."""
        ...

    @property
    @abstractmethod
    def metrics(self) -> TelemetryFilterMetrics:
        """Return an immutable snapshot of local transmission accounting."""
        ...
