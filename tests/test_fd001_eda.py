"""Target boundaries and protection against validation/test influence."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from predictive_maintenance.analysis.fd001 import normalized_unit_curves
from predictive_maintenance.application.eda_fd001 import load_development, run_eda
from predictive_maintenance.data.cmapss_schema import FD001_COLUMNS
from predictive_maintenance.data.targets import HorizonConfig, build_evaluation_targets


def fixture(units):
    return pd.DataFrame([
        [unit, cycle, *[float(unit + cycle * (index + 1) / 10)
                       for index in range(24)]]
        for unit in units for cycle in range(1, 7)
    ], columns=FD001_COLUMNS)


class TargetTests(unittest.TestCase):
    def test_exact_horizon_boundaries_terminal_and_no_clipping(self):
        frame = pd.DataFrame({"unit_id": [1] * 40, "cycle": range(1, 41)})
        targets = build_evaluation_targets(frame, HorizonConfig(),
                                           complete_run_to_failure=True)
        self.assertEqual(targets.RUL.tolist(), list(range(39, -1, -1)))
        by_rul = targets.set_index("RUL")
        self.assertFalse(by_rul.loc[31, "failure_within_horizon"])
        self.assertTrue(by_rul.loc[30, "failure_within_horizon"])
        self.assertFalse(by_rul.loc[16, "failure_within_critical_horizon"])
        self.assertTrue(by_rul.loc[15, "failure_within_critical_horizon"])
        self.assertTrue(by_rul.loc[0, "failure_within_horizon"])
        self.assertFalse(by_rul.loc[0, "is_operational"])
        self.assertEqual(int(targets.failure_within_horizon.sum()), 31)
        self.assertTrue((~targets.failure_within_critical_horizon
                         | targets.failure_within_horizon).all())

    def test_per_unit_terminal_and_configurable_horizons(self):
        keys = pd.DataFrame({"unit_id": [1, 1, 2, 2, 2, 2],
                             "cycle": [1, 2, 1, 2, 3, 4], "sensor_1": [5.] * 6})
        original = keys.copy(deep=True)
        result = build_evaluation_targets(keys, HorizonConfig(2, 1),
                                          complete_run_to_failure=True)
        self.assertEqual(result.RUL.tolist(), [1, 0, 3, 2, 1, 0])
        self.assertEqual(result.failure_within_horizon.tolist(),
                         [True, True, False, True, True, True])
        self.assertNotIn("sensor_1", result)
        pd.testing.assert_frame_equal(keys, original)
        pd.testing.assert_frame_equal(keys[["unit_id", "cycle"]],
                                      result[["unit_id", "cycle"]])

    def test_reject_censored_or_invalid_trajectory(self):
        frame = pd.DataFrame({"unit_id": [1, 1], "cycle": [1, 3]})
        for complete in (False, True):
            with self.subTest(complete=complete), self.assertRaises(ValueError):
                build_evaluation_targets(frame, HorizonConfig(),
                                         complete_run_to_failure=complete)
        duplicate = pd.DataFrame({"unit_id": [1, 1], "cycle": [1, 1]})
        with self.assertRaises(ValueError):
            build_evaluation_targets(duplicate, HorizonConfig(),
                                     complete_run_to_failure=True)

    def test_invalid_horizons(self):
        for pair in ((0, 1), (30, 30), (15, 30), (30, -1), (30., 15), (True, 1)):
            with self.subTest(pair=pair), self.assertRaises(ValueError):
                HorizonConfig(*pair)

    def test_normalized_average_weights_units_equally(self):
        train = pd.DataFrame({
            "unit_id": [1, 1, 2, 2, 2, 2], "cycle": [1, 2, 1, 2, 3, 4],
            "sensor_1": [0., 0., 10., 10., 10., 10.],
        })
        grid, curves, units = normalized_unit_curves(train, "sensor_1", 5)
        self.assertEqual(units, [1, 2])
        np.testing.assert_allclose(curves.mean(axis=0), [5.] * 5)
        self.assertEqual((grid[0], grid[-1]), (0, 1))


class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.train = fixture([1, 2, 3])
        self.validation = fixture([4])
        self.train.to_parquet(self.root / "train.parquet", index=False)
        self.validation.to_parquet(self.root / "validation.parquet", index=False)
        # Deliberately unreadable holdout. Any read attempt must fail.
        (self.root / "test_internal.parquet").write_text("do not read", encoding="utf-8")
        self.manifest = {
            "dataset": "FD001", "source": {"file": "train_FD001.txt"},
            "units": {"train": [1, 2, 3], "validation": [4], "test_internal": [5]},
            "rows": {"train": 18, "validation": 6, "test_internal": 1},
        }
        self.write_manifest()

    def write_manifest(self):
        (self.root / "split_manifest.json").write_text(
            json.dumps(self.manifest), encoding="utf-8")

    def test_only_two_development_parquets_are_read(self):
        reader = pd.read_parquet
        with patch("predictive_maintenance.application.eda_fd001.pd.read_parquet",
                   wraps=reader) as read:
            frames = load_development(self.root)
        self.assertEqual(set(frames), {"train", "validation"})
        self.assertEqual([c.args[0].name for c in read.call_args_list],
                         ["train.parquet", "validation.parquet"])

    def test_overlap_or_inconsistent_membership_is_rejected(self):
        self.manifest["units"]["test_internal"] = [1]
        self.write_manifest()
        with self.assertRaises(ValueError):
            load_development(self.root)
        self.manifest["units"]["test_internal"] = [5]
        self.manifest["units"]["validation"] = [6]
        self.write_manifest()
        with self.assertRaises(ValueError):
            load_development(self.root)

    def test_eda_statistics_and_candidates_ignore_validation_values(self):
        config = Path(__file__).resolve().parents[1] / "configs/fd001_eda.toml"
        stats = []
        for iteration in (1, 2):
            if iteration == 2:
                self.validation.loc[:, list(FD001_COLUMNS[2:])] *= 100000.
                self.validation.to_parquet(self.root / "validation.parquet", index=False)
            report_dir = self.root / f"reports_{iteration}"
            # Figures are inspected from a full real-data execution separately.
            with patch("predictive_maintenance.application.eda_fd001.plot_training",
                       return_value=[]) as plot:
                run_eda(self.root, config, report_dir)
                pd.testing.assert_frame_equal(plot.call_args.args[0], self.train)
            payload = json.loads((report_dir / "eda" / "summary.json").read_text(encoding="utf-8"))
            stats.append(payload["statistics"])
            targets = pd.read_parquet(self.root / "evaluation_targets" / "validation_targets.parquet")
            self.assertEqual(targets.RUL.tolist(), [5, 4, 3, 2, 1, 0])
        self.assertEqual(stats[0], stats[1])
