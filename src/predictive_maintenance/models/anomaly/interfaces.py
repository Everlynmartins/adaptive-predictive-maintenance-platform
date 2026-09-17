"""Anomaly detection boundary; anomaly scores are not risk probabilities."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Self, Sequence

from predictive_maintenance.core.records import AnomalyPrediction, FeatureRecord


class AnomalyDetector(ABC):
    @abstractmethod
    def fit(self, features: Sequence[FeatureRecord]) -> Self:
        """Fit using training observations only."""
        ...

    @abstractmethod
    def detect(self, features: Sequence[FeatureRecord]) -> list[AnomalyPrediction]:
        """Return one detector result per input key, in input order."""
        ...

    @abstractmethod
    def save(self, path: Path) -> None:
        """Persist the fitted detector and score-reference state locally."""
        ...

    @classmethod
    @abstractmethod
    def load(cls, path: Path) -> Self:
        """Restore a compatible detector from a trusted local artifact."""
        ...
