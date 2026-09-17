"""One internal contract for all risk-model families."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Self, Sequence

from predictive_maintenance.core.records import FeatureRecord, RiskPrediction, TargetRecord


class RiskModel(ABC):
    @abstractmethod
    def fit(
        self,
        features: Sequence[FeatureRecord],
        targets: Sequence[TargetRecord] | None = None,
    ) -> Self:
        """Fit training data; supervised adapters must reject missing targets."""
        ...

    @abstractmethod
    def predict_risk(
        self, features: Sequence[FeatureRecord], *, horizon: int,
    ) -> list[RiskPrediction]:
        """Return P(T <= t + horizon | history through t, T > t) per input key.

        Preserve order and fit state. Reject unsupported horizons explicitly;
        never silently substitute a fitted horizon. Mark unavailable outputs.
        """
        ...

    @abstractmethod
    def save(self, path: Path) -> None:
        """Persist local state and metadata needed for equivalent predictions."""
        ...

    @classmethod
    @abstractmethod
    def load(cls, path: Path) -> Self:
        """Restore this concrete type from a compatible, trusted local artifact."""
        ...
