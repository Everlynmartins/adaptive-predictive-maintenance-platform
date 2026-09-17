from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from predictive_maintenance.application.transformer_fd001 import (
    _early_stopping_units,
    _feature_records,
    _load_development,
    _operational_frame,
    _target_records,
)


class TransformerPipelineTests(unittest.TestCase):
    def test_early_stopping_is_grouped_disjoint_and_reproducible(self):
        first = _early_stopping_units(range(1, 71), fraction=0.2, seed=4701)
        second = _early_stopping_units(range(1, 71), fraction=0.2, seed=4701)
        self.assertEqual(first, second)
        self.assertFalse(set(first[0]) & set(first[1]))
        self.assertEqual(set(first[0]) | set(first[1]), set(range(1, 71)))

    def test_rul_is_only_in_target_path(self):
        frame = pd.DataFrame({"unit_id": [1, 1, 1], "cycle": [1, 2, 3],
                              "sensor_2": [1.0, 2.0, 3.0]})
        operational = _operational_frame(frame)
        records = _feature_records(operational, ("sensor_2", "age_cycle"))
        targets = _target_records(operational, (1, 2))
        self.assertNotIn("RUL", records[0].values)
        self.assertNotIn("failure_within_h1", records[0].values)
        self.assertIn("failure_within_h1", targets[0].values)

    def test_loader_reads_only_train_and_validation_parquets(self):
        manifest = {"units": {"train": [1], "validation": [2], "test_internal": [3]},
                    "rows": {"train": 2, "validation": 2, "test_internal": 2}}
        train = pd.DataFrame({"unit_id": [1, 1], "cycle": [1, 2]})
        validation = pd.DataFrame({"unit_id": [2, 2], "cycle": [1, 2]})
        with tempfile.TemporaryDirectory() as directory:
            processed = Path(directory)
            (processed / "split_manifest.json").write_text(__import__("json").dumps(manifest))
            opened = []

            def fake_read(path):
                opened.append(Path(path).name)
                return train if Path(path).name == "train.parquet" else validation

            with patch("pandas.read_parquet", side_effect=fake_read):
                _load_development(processed, Path("unused"))
            self.assertEqual(opened, ["train.parquet", "validation.parquet"])
            self.assertNotIn("test_internal.parquet", opened)


if __name__ == "__main__":
    unittest.main()
