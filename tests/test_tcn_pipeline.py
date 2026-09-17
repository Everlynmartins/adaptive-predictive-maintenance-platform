import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from predictive_maintenance.application.tcn_fd001 import (
    _early_stopping_units,
    _feature_records,
    _load_development,
    _operational_frame,
    _target_records,
)


class TCNPipelineTests(unittest.TestCase):
    def test_grouped_early_stopping_is_disjoint_and_reproducible(self):
        units = list(range(1, 21))
        fit_a, stop_a = _early_stopping_units(units, fraction=0.2, seed=19)
        fit_b, stop_b = _early_stopping_units(units, fraction=0.2, seed=19)
        self.assertEqual((fit_a, stop_a), (fit_b, stop_b))
        self.assertFalse(set(fit_a) & set(stop_a))
        self.assertEqual(set(fit_a) | set(stop_a), set(units))

    def test_target_and_feature_paths_keep_rul_out_of_inputs(self):
        frame = pd.DataFrame({
            "unit_id": [1, 1, 1, 2, 2, 2],
            "cycle": [1, 2, 3, 1, 2, 3],
            "sensor_2": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        })
        operational = _operational_frame(frame)
        features = _feature_records(operational, ("sensor_2", "age_cycle"))
        targets = _target_records(operational, (1, 2))
        self.assertTrue(all("RUL" not in item.values for item in features))
        self.assertTrue(all("normalized_life" not in item.values for item in features))
        self.assertTrue(all(target.values["failure_within_h2"] == 1 for target in targets))
        self.assertEqual(len(features), 4)

    def test_processed_loader_reads_only_train_and_validation_parquets(self):
        train = pd.DataFrame({"unit_id": [1, 1], "cycle": [1, 2], "sensor_2": [1.0, 2.0]})
        validation = pd.DataFrame({"unit_id": [2, 2], "cycle": [1, 2], "sensor_2": [3.0, 4.0]})
        with tempfile.TemporaryDirectory() as directory:
            processed = Path(directory)
            manifest = {
                "units": {"train": [1], "validation": [2], "test_internal": [3]},
                "rows": {"train": 2, "validation": 2, "test_internal": 1},
            }
            (processed / "split_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            opened = []

            def fake_read(path):
                opened.append(Path(path).name)
                return train.copy() if Path(path).name == "train.parquet" else validation.copy()

            with patch("predictive_maintenance.application.tcn_fd001.pd.read_parquet",
                       side_effect=fake_read):
                loaded_train, loaded_validation, _, source_mode = _load_development(
                    processed, Path(directory) / "raw",
                )
            self.assertEqual(opened, ["train.parquet", "validation.parquet"])
            self.assertEqual(source_mode, "processed_parquet")
            self.assertEqual(set(loaded_train.unit_id), {1})
            self.assertEqual(set(loaded_validation.unit_id), {2})
            self.assertNotIn("test_internal.parquet", opened)


if __name__ == "__main__":
    unittest.main()
