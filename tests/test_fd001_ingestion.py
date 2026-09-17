"""Automated checks for FD001 parsing, validation, reporting and splitting."""

import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from predictive_maintenance.application.prepare_fd001 import prepare_fd001
from predictive_maintenance.data.cmapss import CMAPSSFD001Loader
from predictive_maintenance.data.cmapss_schema import FD001_COLUMNS
from predictive_maintenance.data.reporting import build_fd001_report
from predictive_maintenance.data.splitting import UnitSplitConfig, split_by_unit
from predictive_maintenance.data.validation import (
    FD001ValidationError,
    validate_fd001,
)


def telemetry_row(unit_id: object, cycle: object, offset: float = 0.0) -> list[object]:
    return [unit_id, cycle, *[offset + index / 10 for index in range(1, 25)]]


def frame_for_units(number_of_units: int, cycles: int = 2) -> pd.DataFrame:
    rows = [
        telemetry_row(unit_id, cycle, offset=float(unit_id))
        for unit_id in range(1, number_of_units + 1)
        for cycle in range(1, cycles + 1)
    ]
    return validate_fd001(pd.DataFrame(rows, columns=FD001_COLUMNS))


def issue_codes(error: FD001ValidationError) -> set[str]:
    return {issue.code for issue in error.issues}


class FD001ValidationTests(unittest.TestCase):
    def test_loader_assigns_clear_names_and_numeric_types(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "train_FD001.txt"
            rows = [telemetry_row(1, 1), telemetry_row(1, 2, 1.0)]
            source.write_text(
                "\n".join(" ".join(map(str, row)) for row in rows) + "\n",
                encoding="utf-8",
            )
            frame = CMAPSSFD001Loader().load_frame(source)
            records = list(CMAPSSFD001Loader().ingest(source))

        self.assertEqual(tuple(frame.columns), FD001_COLUMNS)
        self.assertEqual(frame["unit_id"].dtype.name, "int64")
        self.assertEqual(frame["cycle"].dtype.name, "int64")
        self.assertTrue(all(frame[column].dtype.name == "float64" for column in FD001_COLUMNS[2:]))
        self.assertEqual(records[0].unit_id, "1")
        self.assertEqual(len(records[0].values), 24)

    def test_invalid_column_count_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "train_FD001.txt"
            source.write_text(" ".join(map(str, telemetry_row(1, 1)[:-1])), encoding="utf-8")
            with self.assertRaises(FD001ValidationError) as raised:
                CMAPSSFD001Loader().load_frame(source)
        self.assertIn("INVALID_COLUMN_COUNT", issue_codes(raised.exception))

    def test_non_numeric_and_missing_values_are_rejected(self):
        frame = pd.DataFrame(
            [telemetry_row(1, 1), telemetry_row(2, 1)],
            columns=FD001_COLUMNS,
        )
        frame = frame.astype(object)
        frame.loc[0, "sensor_1"] = "broken"
        frame.loc[1, "sensor_2"] = None
        with self.assertRaises(FD001ValidationError) as raised:
            validate_fd001(frame)
        self.assertEqual(
            issue_codes(raised.exception),
            {"NON_NUMERIC_VALUES", "MISSING_VALUES"},
        )

    def test_loader_treats_nan_token_as_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "train_FD001.txt"
            row = telemetry_row(1, 1)
            row[5] = "NaN"
            source.write_text(" ".join(map(str, row)), encoding="utf-8")
            with self.assertRaises(FD001ValidationError) as raised:
                CMAPSSFD001Loader().load_frame(source)
        self.assertIn("MISSING_VALUES", issue_codes(raised.exception))

    def test_exact_duplicate_rows_and_unit_cycles_are_rejected(self):
        row = telemetry_row(1, 1)
        frame = pd.DataFrame([row, row], columns=FD001_COLUMNS)
        with self.assertRaises(FD001ValidationError) as raised:
            validate_fd001(frame)
        self.assertTrue(
            {"DUPLICATE_ROWS", "DUPLICATE_UNIT_CYCLES"}
            <= issue_codes(raised.exception)
        )

    def test_duplicate_cycle_with_different_values_is_rejected(self):
        frame = pd.DataFrame(
            [telemetry_row(1, 1), telemetry_row(1, 1, 5.0)],
            columns=FD001_COLUMNS,
        )
        with self.assertRaises(FD001ValidationError) as raised:
            validate_fd001(frame)
        self.assertIn("DUPLICATE_UNIT_CYCLES", issue_codes(raised.exception))
        self.assertNotIn("DUPLICATE_ROWS", issue_codes(raised.exception))

    def test_empty_dataset_is_rejected(self):
        frame = pd.DataFrame(columns=FD001_COLUMNS)
        with self.assertRaises(FD001ValidationError) as raised:
            validate_fd001(frame)
        self.assertIn("NO_UNITS", issue_codes(raised.exception))

    def test_non_increasing_source_order_is_rejected(self):
        frame = pd.DataFrame(
            [telemetry_row(1, 1), telemetry_row(1, 3), telemetry_row(1, 2)],
            columns=FD001_COLUMNS,
        )
        with self.assertRaises(FD001ValidationError) as raised:
            validate_fd001(frame)
        self.assertIn("NON_INCREASING_CYCLES", issue_codes(raised.exception))

    def test_cycle_gaps_are_rejected(self):
        frame = pd.DataFrame(
            [telemetry_row(1, 1), telemetry_row(1, 3)],
            columns=FD001_COLUMNS,
        )
        with self.assertRaises(FD001ValidationError) as raised:
            validate_fd001(frame)
        self.assertIn("NON_CONSECUTIVE_CYCLES", issue_codes(raised.exception))

    def test_non_integer_and_non_positive_identifiers_are_rejected(self):
        frame = pd.DataFrame(
            [telemetry_row(1.5, 1), telemetry_row(2, 0)],
            columns=FD001_COLUMNS,
        )
        with self.assertRaises(FD001ValidationError) as raised:
            validate_fd001(frame)
        self.assertEqual(
            issue_codes(raised.exception),
            {"NON_INTEGER_IDENTIFIER", "NON_POSITIVE_IDENTIFIER", "NON_CONSECUTIVE_CYCLES"},
        )


class FD001SplitAndReportTests(unittest.TestCase):
    def setUp(self):
        self.frame = frame_for_units(20, cycles=3)
        self.config = UnitSplitConfig(42, 0.70, 0.15, 0.15)

    def test_split_is_reproducible_complete_and_disjoint_by_unit(self):
        first = split_by_unit(self.frame, self.config)
        second = split_by_unit(self.frame, self.config)
        self.assertEqual(first.train_units, second.train_units)
        self.assertEqual(first.validation_units, second.validation_units)
        self.assertEqual(first.test_internal_units, second.test_internal_units)

        unit_sets = [
            set(first.train_units),
            set(first.validation_units),
            set(first.test_internal_units),
        ]
        self.assertFalse(unit_sets[0] & unit_sets[1])
        self.assertFalse(unit_sets[0] & unit_sets[2])
        self.assertFalse(unit_sets[1] & unit_sets[2])
        self.assertEqual(set.union(*unit_sets), set(range(1, 21)))
        self.assertEqual([len(units) for units in unit_sets], [14, 3, 3])
        for subset, units in (
            (first.train, unit_sets[0]),
            (first.validation, unit_sets[1]),
            (first.test_internal, unit_sets[2]),
        ):
            self.assertEqual(set(subset["unit_id"]), units)
            self.assertTrue(all(subset.groupby("unit_id").size() == 3))

    def test_report_contains_requested_summary(self):
        report = build_fd001_report(self.frame)
        self.assertEqual(report["number_of_engines"], 20)
        self.assertEqual(report["total_cycles"], 60)
        self.assertEqual(report["minimum_cycles_per_engine"], 3)
        self.assertEqual(report["maximum_cycles_per_engine"], 3)
        self.assertEqual(report["median_cycles_per_engine"], 3.0)
        self.assertEqual(report["number_of_sensors"], 21)
        self.assertEqual(report["number_of_operational_settings"], 3)

    def test_preparation_writes_parquet_and_never_reads_official_test(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_dir = root / "raw"
            processed_dir = root / "processed"
            raw_dir.mkdir()
            training = raw_dir / "train_FD001.txt"
            training.write_text(
                "\n".join(
                    " ".join(map(str, row))
                    for row in self.frame.itertuples(index=False, name=None)
                )
                + "\n",
                encoding="utf-8",
            )
            (raw_dir / "test_FD001.txt").write_text(
                "this file must remain unread by internal preparation",
                encoding="utf-8",
            )
            config_path = Path(__file__).resolve().parents[1] / "configs" / "fd001.toml"
            result = prepare_fd001(config_path, raw_dir, processed_dir)
            output = Path(result["output_dir"])

            loaded = {
                name: pd.read_parquet(output / f"{name}.parquet")
                for name in ("train", "validation", "test_internal")
            }
            manifest = json.loads(
                (output / "split_manifest.json").read_text(encoding="utf-8")
            )
            report = json.loads(
                (output / "validation_report.json").read_text(encoding="utf-8")
            )

        self.assertEqual(sum(len(value) for value in loaded.values()), len(self.frame))
        self.assertFalse(manifest["official_evaluation"]["used"])
        self.assertTrue(manifest["official_evaluation"]["files_present"]["official_test"])
        self.assertEqual(report["number_of_engines"], 20)

    def test_missing_training_file_fails_without_creating_processed_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_dir = root / "raw"
            processed_dir = root / "processed"
            raw_dir.mkdir()
            config_path = Path(__file__).resolve().parents[1] / "configs" / "fd001.toml"
            with self.assertRaises(FileNotFoundError):
                prepare_fd001(config_path, raw_dir, processed_dir)
            self.assertFalse(processed_dir.exists())


if __name__ == "__main__":
    unittest.main()
