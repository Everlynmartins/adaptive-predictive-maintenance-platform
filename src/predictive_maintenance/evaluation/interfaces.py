"""Evaluation boundary independent of fitting and application orchestration."""

from abc import ABC, abstractmethod
from typing import Mapping, Sequence

from predictive_maintenance.core.records import RiskPrediction, TargetRecord


class Evaluator(ABC):
    @abstractmethod
    def evaluate(
        self,
        predictions: Sequence[RiskPrediction],
        targets: Sequence[TargetRecord],
    ) -> Mapping[str, float]:
        """Match keys/horizon and target semantics; use operational instants only.

        Report unavailable/invalid coverage separately; never score them as zero
        risk or silently discard them from availability statistics.
        """
        ...
