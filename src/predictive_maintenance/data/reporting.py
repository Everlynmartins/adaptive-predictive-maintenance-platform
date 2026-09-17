"""Compact validation summary for FD001."""

from typing import Any

import pandas as pd

from predictive_maintenance.data.cmapss_schema import SENSOR_COLUMNS, SETTING_COLUMNS


def build_fd001_report(frame: pd.DataFrame) -> dict[str, Any]:
    cycle_counts = frame.groupby("unit_id", sort=True)["cycle"].count()
    constant_columns = [
        column
        for column in (*SETTING_COLUMNS, *SENSOR_COLUMNS)
        if frame[column].nunique(dropna=False) <= 1
    ]
    behaviors = []
    if constant_columns:
        behaviors.append(
            {
                "code": "CONSTANT_COLUMNS",
                "message": "Columns with one observed value were retained; review before modeling.",
                "columns": constant_columns,
            }
        )
    return {
        "number_of_engines": int(frame["unit_id"].nunique()),
        "total_cycles": int(len(frame)),
        "minimum_cycles_per_engine": int(cycle_counts.min()),
        "maximum_cycles_per_engine": int(cycle_counts.max()),
        "median_cycles_per_engine": float(cycle_counts.median()),
        "number_of_sensors": len(SENSOR_COLUMNS),
        "number_of_operational_settings": len(SETTING_COLUMNS),
        "validation_status": "valid",
        "observed_behaviors": behaviors,
    }

