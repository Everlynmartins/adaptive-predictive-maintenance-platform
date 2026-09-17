"""Reusable, strict local loader for NASA C-MAPSS FD001 telemetry."""

from pathlib import Path
from typing import Iterable

import pandas as pd

from predictive_maintenance.core.records import TelemetryRecord
from predictive_maintenance.data.cmapss_schema import (
    FD001_COLUMNS,
    FD001_COLUMN_COUNT,
)
from predictive_maintenance.data.interfaces import TelemetryIngestor
from predictive_maintenance.data.validation import (
    FD001ValidationError,
    ValidationIssue,
    validate_fd001,
)


class CMAPSSFD001Loader(TelemetryIngestor):
    """Load a whitespace-delimited FD001 train or test telemetry file."""

    def load_frame(self, source: Path) -> pd.DataFrame:
        source = Path(source)
        if not source.is_file():
            raise FileNotFoundError(
                f"FD001 telemetry file not found: {source}. "
                "Place the official NASA file in data/raw."
            )

        rows: list[list[str]] = []
        column_issues: list[ValidationIssue] = []
        with source.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                tokens = line.split()
                if not tokens:
                    continue
                if len(tokens) != FD001_COLUMN_COUNT:
                    column_issues.append(
                        ValidationIssue(
                            "INVALID_COLUMN_COUNT",
                            f"line {line_number} has {len(tokens)} columns; "
                            f"expected {FD001_COLUMN_COUNT}",
                            (line_number,),
                        )
                    )
                    continue
                rows.append(tokens)

        if column_issues:
            raise FD001ValidationError(column_issues)

        frame = pd.DataFrame(rows, columns=FD001_COLUMNS)
        return validate_fd001(frame)

    def ingest(self, source: Path) -> Iterable[TelemetryRecord]:
        frame = self.load_frame(source)
        value_columns = FD001_COLUMNS[2:]
        return [
            TelemetryRecord(
                unit_id=str(row.unit_id),
                cycle=int(row.cycle),
                values={name: float(getattr(row, name)) for name in value_columns},
            )
            for row in frame.itertuples(index=False)
        ]

