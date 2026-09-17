"""Pipeline isolation and artifact checks with small temporary trajectories."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from predictive_maintenance.application.weibull_fd001 import run_weibull_baseline


class WeibullPipelineTests(unittest.TestCase):
    def test_pipeline_reads_age_only_train_validation_and_writes_complete_card(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            processed, reports = root / "processed", root / "reports"
            processed.mkdir()
            train_lengths = {1: 20, 2: 24, 3: 29, 4: 35, 5: 42, 6: 50}
            validation_lengths = {7: 25, 8: 40}
            for name, lengths in (("train", train_lengths), ("validation", validation_lengths)):
                pd.DataFrame([(unit, cycle) for unit, length in lengths.items()
                              for cycle in range(1, length + 1)],
                             columns=["unit_id", "cycle"]).to_parquet(processed / f"{name}.parquet", index=False)
            (processed / "test_internal.parquet").write_text("must not be read", encoding="utf-8")
            manifest = {
                "dataset": "FD001", "source": {"file": "train_FD001.txt", "sha256": "fixture"},
                "split": {"seed": 42},
                "rows": {"train": sum(train_lengths.values()),
                         "validation": sum(validation_lengths.values()), "test_internal": 1},
                "units": {"train": list(train_lengths), "validation": list(validation_lengths),
                          "test_internal": [9]},
            }
            (processed / "split_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            config = root / "weibull.toml"
            config.write_text('''[model]\nname="fixture"\nversion="test"\n[fit]\nconfidence_level=0.90\nbootstrap_samples=20\nbootstrap_seed=1\n[goodness_of_fit]\nparametric_bootstrap_samples=20\nbootstrap_seed=2\nsignificance_level=0.05\n[prediction]\nhorizons=[5,10]\n[evaluation]\nreliability_bins=5\nlog_loss_epsilon=1e-12\n[sensitivity]\nages=[5,15]\n''', encoding="utf-8")
            reader = pd.read_parquet
            with patch("predictive_maintenance.application.weibull_fd001.pd.read_parquet",
                       wraps=reader) as read:
                result = run_weibull_baseline(processed, config, reports)
            self.assertEqual([call.args[0].name for call in read.call_args_list],
                             ["train.parquet", "validation.parquet"])
            self.assertEqual([call.kwargs["columns"] for call in read.call_args_list],
                             [["unit_id", "cycle"], ["unit_id", "cycle"]])
            card = json.loads((reports / "weibull/model_card.json").read_text(encoding="utf-8"))
            self.assertEqual(card["model_name"], "fixture")
            self.assertEqual(card["training_data_manifest"]["censored_count"], 0)
            self.assertFalse(card["provenance"]["test_internal_read"])
            self.assertFalse(card["provenance"]["official_test_read"])
            self.assertFalse(card["provenance"]["sensors_read"])
            self.assertEqual(card["artifact_hash"]["value"], result["model_artifact_sha256"])
            predictions = pd.read_parquet(reports / "weibull/artifacts/validation_predictions.parquet")
            unit_metrics = pd.read_parquet(reports / "weibull/artifacts/validation_metrics_by_unit.parquet")
            self.assertEqual(set(predictions.horizon), {5, 10})
            self.assertEqual(set(predictions.prediction_status), {"available"})
            self.assertTrue((predictions.risk_score.between(0, 1)).all())
            self.assertEqual(len(unit_metrics), 4)
            self.assertEqual(set(unit_metrics.unit_id), {7, 8})
            self.assertTrue((reports / "weibull_report.md").exists())


if __name__ == "__main__":
    unittest.main()
