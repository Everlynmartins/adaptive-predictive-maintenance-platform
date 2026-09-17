import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from predictive_maintenance.application.anomaly_detection_fd001 import run_anomaly_detection
from test_classical_ml_pipeline import _frame


class AnomalyPipelineTests(unittest.TestCase):
    def test_grouped_oof_train_only_healthy_region_and_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); processed, reports = root / "processed", root / "reports"
            processed.mkdir()
            train = _frame({1: 14, 2: 16, 3: 18, 4: 20})
            validation = _frame({5: 17, 6: 19})
            train.to_parquet(processed / "train.parquet", index=False)
            validation.to_parquet(processed / "validation.parquet", index=False)
            (processed / "test_internal.parquet").write_text("must not be read", encoding="utf-8")
            (processed / "split_manifest.json").write_text(json.dumps({
                "dataset": "FD001", "source": {"file": "train_FD001.txt"},
                "rows": {"train": len(train), "validation": len(validation), "test_internal": 1},
                "units": {"train": [1, 2, 3, 4], "validation": [5, 6], "test_internal": [7]},
            }), encoding="utf-8")
            config = root / "anomaly.toml"
            config.write_text('''[model]\nmodel_version="test"\nrandom_seed=7\nn_estimators=20\nmax_samples=8\ncontamination="auto"\n[healthy_region]\nminimum_rul_exclusive=5\n[features]\nwindows=[2,3]\n[cross_validation]\nfolds=2\nseed=8\n[analysis]\nnear_event_rul_inclusive=3\ndiagnostic_healthy_quantile=0.95\nrepresentative_units=3\n''', encoding="utf-8")
            with patch("pandas.read_parquet", wraps=pd.read_parquet) as read:
                result = run_anomaly_detection(processed, config, reports)
            self.assertEqual([call.args[0].name for call in read.call_args_list], ["train.parquet", "validation.parquet"])
            artifacts = reports / "anomaly_detection/artifacts"
            oof = pd.read_parquet(artifacts / "train_oof_anomaly_scores.parquet")
            self.assertEqual(len(oof), len(train) - train.unit_id.nunique())
            self.assertFalse(oof.duplicated(["unit_id", "cycle"]).any())
            self.assertTrue(oof.anomaly_score.between(0, 1).all())
            folds = json.loads((artifacts / "fold_manifest.json").read_text(encoding="utf-8"))
            for fold in folds["folds"]:
                self.assertFalse(set(fold["fitting_units"]) & set(fold["holdout_units"]))
                self.assertEqual(set(oof.loc[oof.fold.eq(fold["fold"]), "unit_id"]), set(fold["holdout_units"]))
            self.assertEqual(result["validation"]["healthy_region"]["rows"],
                             int((validation.groupby("unit_id").cycle.transform("max") - validation.cycle > 5).sum()))
            self.assertTrue((reports / "anomaly_detection_report.md").exists())
            self.assertTrue((reports / "anomaly_detection/model_card.json").exists())
