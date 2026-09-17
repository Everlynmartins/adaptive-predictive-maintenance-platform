"""Isolation, grouped-fold and artifact tests for the classical ML pipeline."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from predictive_maintenance.application.classical_ml_fd001 import (
    grouped_unit_folds, run_classical_ml,
)


def _frame(lengths):
    rows = []
    for unit_id, length in lengths.items():
        for cycle in range(1, length + 1):
            row = {"unit_id": unit_id, "cycle": cycle}
            row.update({f"setting_{index}": (cycle / length if index < 3 else 100.0)
                        for index in range(1, 4)})
            row.update({f"sensor_{index}": (unit_id + cycle * index / 10.0
                                             if index not in {1, 5, 10, 16, 18, 19}
                                             else float(index))
                        for index in range(1, 22)})
            rows.append(row)
    return pd.DataFrame(rows)


class ClassicalPipelineTests(unittest.TestCase):
    def test_grouped_folds_are_reproducible_disjoint_and_complete(self):
        first = grouped_unit_folds(list(range(1, 13)), folds=4, seed=7)
        second = grouped_unit_folds(list(range(1, 13)), folds=4, seed=7)
        self.assertEqual(first, second)
        self.assertEqual(set().union(*(set(part) for part in first)), set(range(1, 13)))
        for left in range(len(first)):
            for right in range(left + 1, len(first)):
                self.assertFalse(set(first[left]) & set(first[right]))

    def test_pipeline_uses_only_train_validation_and_writes_separate_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            processed, reports = root / "processed", root / "reports"
            processed.mkdir(); (reports / "weibull/artifacts").mkdir(parents=True)
            train_lengths = {unit: 38 + unit for unit in range(1, 7)}
            validation_lengths = {7: 46, 8: 49}
            _frame(train_lengths).to_parquet(processed / "train.parquet", index=False)
            validation = _frame(validation_lengths)
            validation.to_parquet(processed / "validation.parquet", index=False)
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
            weibull_rows = []
            for horizon in (15, 30):
                for unit, length in validation_lengths.items():
                    for cycle in range(1, length):
                        weibull_rows.append({"unit_id": unit, "cycle": cycle, "horizon": horizon,
                                             "risk_score": min(0.99, cycle / length)})
            pd.DataFrame(weibull_rows).to_parquet(
                reports / "weibull/artifacts/validation_predictions.parquet", index=False,
            )
            config = root / "classical.toml"
            config.write_text('''[models]\nversion="test"\nrandom_seed=4\n[features]\nwindows=[2,3]\nrelative_epsilon=1e-12\nvariance_epsilon=0.0\ninclude_cycle=true\n[cross_validation]\nfolds=3\nseed=5\n[prediction]\nhorizons=[15,30]\n[random_forest]\nn_estimators=5\nmax_depth=3\nmin_samples_leaf=1\nmax_features="sqrt"\n[xgboost]\nn_estimators=5\nmax_depth=2\nlearning_rate=0.1\nsubsample=1.0\ncolsample_bytree=1.0\nmin_child_weight=1.0\nreg_lambda=1.0\ntree_method="hist"\n[evaluation]\nreliability_bins=4\nlog_loss_epsilon=1e-12\nexploratory_threshold=0.5\n[importance]\npermutation_repeats=1\nseed=6\n''', encoding="utf-8")
            reader = pd.read_parquet
            with patch("predictive_maintenance.application.classical_ml_fd001.pd.read_parquet",
                       wraps=reader) as read:
                result = run_classical_ml(processed, config, reports)
            read_names = [call.args[0].name for call in read.call_args_list]
            self.assertEqual(read_names[:2], ["train.parquet", "validation.parquet"])
            self.assertNotIn("test_internal.parquet", read_names)
            self.assertEqual(result["oof_rows"], (sum(train_lengths.values()) - len(train_lengths)) * 4)
            self.assertEqual(result["validation_prediction_rows"],
                             (sum(validation_lengths.values()) - len(validation_lengths)) * 4)
            artifact_root = reports / "classical_ml/artifacts"
            for name in ("train_oof_predictions.parquet", "validation_predictions.parquet",
                         "metrics_by_unit.parquet", "fold_manifest.json",
                         "causal_feature_engineer.json", "xgboost_gain_importance.parquet",
                         "xgboost_permutation_importance_oof.parquet"):
                self.assertTrue((artifact_root / name).exists(), name)
            self.assertTrue((reports / "classical_ml/random_forest_model_card.json").exists())
            self.assertTrue((reports / "classical_ml/xgboost_model_card.json").exists())
            self.assertTrue((reports / "classical_ml_report.md").exists())
            card = json.loads((reports / "classical_ml/xgboost_model_card.json").read_text(encoding="utf-8"))
            self.assertTrue(card["shared_dependencies"])
            self.assertTrue(any("not an alert policy" in item for item in card["limitations"]))
            metrics = json.loads((reports / "classical_ml/metrics.json").read_text(encoding="utf-8"))
            self.assertIn("cross_horizon_coherence", metrics["results"])
            permutation = pd.read_parquet(artifact_root / "xgboost_permutation_importance_oof.parquet")
            self.assertEqual(set(permutation.folds), {3})
            folds = json.loads((artifact_root / "fold_manifest.json").read_text(encoding="utf-8"))
            for fold in folds["folds"]:
                self.assertFalse(set(fold["fitting_units"]) & set(fold["holdout_units"]))


if __name__ == "__main__":
    unittest.main()
