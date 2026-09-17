"""Generic telemetry ingestion boundary for dataset-specific adapters."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterable

from predictive_maintenance.core.records import TelemetryRecord


class TelemetryIngestor(ABC):
    """Adapt a local source to shared records, preserving asset identity and order."""

    @abstractmethod
    def ingest(self, source: Path) -> Iterable[TelemetryRecord]:
        """Read a local source through a concrete dataset adapter."""
        ...
