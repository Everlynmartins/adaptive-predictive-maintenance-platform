"""Reproducible FD001 partitioning at unit level."""

from dataclasses import dataclass
from math import floor, isclose
import random

import pandas as pd


@dataclass(frozen=True)
class UnitSplitConfig:
    seed: int
    train_fraction: float
    validation_fraction: float
    test_fraction: float

    def validate(self) -> None:
        fractions = (
            self.train_fraction,
            self.validation_fraction,
            self.test_fraction,
        )
        if any(value <= 0 or value >= 1 for value in fractions):
            raise ValueError("all split fractions must be between 0 and 1")
        if not isclose(sum(fractions), 1.0, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("split fractions must sum to 1")


@dataclass(frozen=True)
class UnitSplit:
    train: pd.DataFrame
    validation: pd.DataFrame
    test_internal: pd.DataFrame
    train_units: tuple[int, ...]
    validation_units: tuple[int, ...]
    test_internal_units: tuple[int, ...]


def _allocate_counts(total: int, fractions: tuple[float, float, float]) -> list[int]:
    raw = [total * fraction for fraction in fractions]
    counts = [floor(value) for value in raw]
    for index in sorted(range(3), key=lambda item: (-(raw[item] - counts[item]), item)):
        if sum(counts) == total:
            break
        counts[index] += 1

    for empty_index, count in enumerate(counts):
        if count == 0:
            donor = max(range(3), key=lambda item: counts[item])
            if counts[donor] <= 1:
                raise ValueError("at least three units are required for three non-empty splits")
            counts[donor] -= 1
            counts[empty_index] += 1
    return counts


def split_by_unit(frame: pd.DataFrame, config: UnitSplitConfig) -> UnitSplit:
    """Partition complete units; source rows and their order remain unchanged."""

    config.validate()
    units = sorted(int(value) for value in frame["unit_id"].unique())
    if len(units) < 3:
        raise ValueError("at least three distinct units are required")

    random.Random(config.seed).shuffle(units)
    counts = _allocate_counts(
        len(units),
        (config.train_fraction, config.validation_fraction, config.test_fraction),
    )
    train_end = counts[0]
    validation_end = train_end + counts[1]
    train_units = tuple(sorted(units[:train_end]))
    validation_units = tuple(sorted(units[train_end:validation_end]))
    test_units = tuple(sorted(units[validation_end:]))

    unit_sets = (set(train_units), set(validation_units), set(test_units))
    if any(unit_sets[left] & unit_sets[right] for left, right in ((0, 1), (0, 2), (1, 2))):
        raise RuntimeError("unit split invariant violated: overlapping units")

    def select(selected: tuple[int, ...]) -> pd.DataFrame:
        return frame.loc[frame["unit_id"].isin(selected)].reset_index(drop=True)

    return UnitSplit(
        train=select(train_units),
        validation=select(validation_units),
        test_internal=select(test_units),
        train_units=train_units,
        validation_units=validation_units,
        test_internal_units=test_units,
    )

