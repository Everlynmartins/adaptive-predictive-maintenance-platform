"""Fusion boundary consuming common risk outputs."""

from abc import ABC, abstractmethod
from typing import Sequence

from predictive_maintenance.core.records import FusionPrediction, RiskPrediction


class ModelFusion(ABC):
    @abstractmethod
    def fuse(
        self, predictions: Sequence[Sequence[RiskPrediction]]
    ) -> list[FusionPrediction]:
        """Combine aligned model batches; reject missing/duplicate or incompatible keys.

        Align by (unit_id, cycle, horizon), never by position alone. Check event,
        population, probability semantics, prediction_status and input_validity.
        No implicit zero imputation for unavailable outputs. Preserve first-batch
        order and identify the fusion method with its own name and version.
        """
        ...
