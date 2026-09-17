"""Structural and temporal validation for C-MAPSS FD001 telemetry."""

from dataclasses import dataclass
from math import isfinite
from typing import Any

import pandas as pd

from predictive_maintenance.data.cmapss_schema import FD001_COLUMNS


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    rows: tuple[int, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.rows:
            result["rows"] = list(self.rows)
        return result


class FD001ValidationError(ValueError):
    """Raised with every issue that can be established safely in one pass."""

    def __init__(self, issues: list[ValidationIssue] | tuple[ValidationIssue, ...]):
        self.issues = tuple(issues)
        details = "; ".join(f"{issue.code}: {issue.message}" for issue in self.issues)
        super().__init__(f"FD001 validation failed: {details}")


def _positions(mask: pd.Series) -> tuple[int, ...]:
    return tuple(
        position + 1
        for position, selected in enumerate(mask.tolist())
        if bool(selected)
    )[:10]


def validate_fd001(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate and return a typed copy without reordering observations."""

    issues: list[ValidationIssue] = []
    actual_columns = tuple(frame.columns)
    if actual_columns != FD001_COLUMNS:
        issues.append(
            ValidationIssue(
                "INVALID_COLUMNS",
                f"expected {len(FD001_COLUMNS)} ordered columns {FD001_COLUMNS}, "
                f"received {len(actual_columns)} columns {actual_columns}",
            )
        )
        raise FD001ValidationError(issues)

    if frame.empty:
        raise FD001ValidationError(
            [ValidationIssue("NO_UNITS", "the dataset has no telemetry rows or units")]
        )

    typed = frame.copy()
    conversion_failed = False
    for column in FD001_COLUMNS:
        source = typed[column]
        normalized = source.astype("string").str.strip().str.lower()
        missing_token = normalized.isin(("", "nan", "na", "null", "none"))
        missing = source.isna() | missing_token
        if missing.any():
            issues.append(
                ValidationIssue(
                    "MISSING_VALUES",
                    f"{column} contains {int(missing.sum())} missing value(s)",
                    _positions(missing),
                )
            )

        converted = pd.to_numeric(source.mask(missing_token), errors="coerce")
        non_numeric = converted.isna() & ~missing
        if non_numeric.any():
            issues.append(
                ValidationIssue(
                    "NON_NUMERIC_VALUES",
                    f"{column} contains {int(non_numeric.sum())} non-numeric value(s)",
                    _positions(non_numeric),
                )
            )
        non_finite = converted.notna() & ~converted.map(isfinite)
        if non_finite.any():
            issues.append(
                ValidationIssue(
                    "NON_FINITE_VALUES",
                    f"{column} contains {int(non_finite.sum())} infinite value(s)",
                    _positions(non_finite),
                )
            )
        if missing.any() or non_numeric.any() or non_finite.any():
            conversion_failed = True
        typed[column] = converted

    if conversion_failed:
        raise FD001ValidationError(issues)

    for column in ("unit_id", "cycle"):
        non_integer = typed[column].mod(1).ne(0)
        if non_integer.any():
            issues.append(
                ValidationIssue(
                    "NON_INTEGER_IDENTIFIER",
                    f"{column} must contain integers",
                    _positions(non_integer),
                )
            )
        non_positive = typed[column].le(0)
        if non_positive.any():
            issues.append(
                ValidationIssue(
                    "NON_POSITIVE_IDENTIFIER",
                    f"{column} must contain positive values",
                    _positions(non_positive),
                )
            )

    exact_duplicates = typed.duplicated(keep=False)
    if exact_duplicates.any():
        issues.append(
            ValidationIssue(
                "DUPLICATE_ROWS",
                f"found {int(exact_duplicates.sum())} rows participating in exact duplicates",
                _positions(exact_duplicates),
            )
        )

    duplicate_cycles = typed.duplicated(subset=["unit_id", "cycle"], keep=False)
    if duplicate_cycles.any():
        issues.append(
            ValidationIssue(
                "DUPLICATE_UNIT_CYCLES",
                f"found {int(duplicate_cycles.sum())} rows with duplicate (unit_id, cycle)",
                _positions(duplicate_cycles),
            )
        )

    for unit_id, unit_rows in typed.groupby("unit_id", sort=False):
        cycles = unit_rows["cycle"]
        if len(cycles) > 1 and not cycles.is_monotonic_increasing:
            issues.append(
                ValidationIssue(
                    "NON_INCREASING_CYCLES",
                    f"cycles for unit {int(unit_id)} are not in increasing source order",
                )
            )
        observed = cycles.astype("int64").tolist()
        expected = list(range(1, len(observed) + 1))
        if observed != expected and len(set(observed)) == len(observed):
            issues.append(
                ValidationIssue(
                    "NON_CONSECUTIVE_CYCLES",
                    f"unit {int(unit_id)} must contain the consecutive sequence 1..N",
                )
            )

    if issues:
        raise FD001ValidationError(issues)

    typed["unit_id"] = typed["unit_id"].astype("int64")
    typed["cycle"] = typed["cycle"].astype("int64")
    for column in FD001_COLUMNS[2:]:
        typed[column] = typed[column].astype("float64")
    return typed
