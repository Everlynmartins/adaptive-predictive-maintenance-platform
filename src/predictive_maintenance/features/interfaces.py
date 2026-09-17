"""Feature engineering boundary independent of datasets and estimators."""

from abc import ABC, abstractmethod
from typing import Self, Sequence

from predictive_maintenance.core.records import FeatureRecord, TelemetryRecord


class FeatureEngineer(ABC):
    @abstractmethod
    def fit(self, telemetry: Sequence[TelemetryRecord]) -> Self:
        """Learn preprocessing state from the training partition only."""
        ...

    @abstractmethod
    def transform(self, telemetry: Sequence[TelemetryRecord]) -> list[FeatureRecord]:
        """Produce features using only observations available by each output cycle."""
        ...

