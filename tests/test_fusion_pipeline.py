"""Isolation and artifact tests for the FD001 fusion application."""

import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

import pandas as pd

from predictive_maintenance.application.classical_ml_fd001 import grouped_unit_folds
from predictive_maintenance.application.fusion_fd001 import load_fusion_development


class FusionPipelineTests(unittest.TestCase):
    def test_adjustment_loader_never_reads_test_internal(self):
        manifest = {"dataset": "FD001", "official_evaluation": {"used": False},
            "units": {"train": [1, 2], "validation": [3], "test_internal": [4]},
            "rows": {"train": 2, "validation": 1, "test_internal": 1}}
        frames = {"train.parquet": pd.DataFrame({"unit_id": [1,2], "cycle": [1,1]}),
                  "validation.parquet": pd.DataFrame({"unit_id": [3], "cycle": [1]})}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "split_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            paths = []
            def fake_read(path):
                paths.append(Path(path).name)
                return frames[Path(path).name]
            with patch("predictive_maintenance.application.fusion_fd001.pd.read_parquet", side_effect=fake_read):
                load_fusion_development(root)
        self.assertEqual(paths, ["train.parquet", "validation.parquet"])
        self.assertNotIn("test_internal.parquet", paths)

    def test_grouped_folds_have_no_unit_overlap(self):
        folds = grouped_unit_folds(list(range(1, 21)), folds=5, seed=4502)
        flattened = [unit for fold in folds for unit in fold]
        self.assertEqual(len(flattened), len(set(flattened)))
        self.assertEqual(set(flattened), set(range(1, 21)))

    def test_real_oof_artifacts_are_aligned_and_anomaly_is_separate(self):
        root = Path(__file__).resolve().parents[1]
        audit = root / "reports/fusion/oof_audit.json"
        if not audit.exists():
            self.skipTest("fusion development artifacts not generated yet")
        payload = json.loads(audit.read_text(encoding="utf-8"))
        self.assertEqual(payload["train_rows_per_horizon"], 14564)
        self.assertEqual(payload["duplicate_keys"], 0)
        self.assertEqual(payload["aligned_missing_values"], 0)
        self.assertIn("never averaged", payload["anomaly_role"])
        for fold in payload["weibull_refit_by_fold"]:
            self.assertFalse(set(fold["fitting_units"]) & set(fold["holdout_units"]))

    def test_frozen_test_receipt_and_outputs_are_consistent(self):
        root = Path(__file__).resolve().parents[1]
        fusion = root / "reports/fusion"
        receipt = json.loads((fusion / "test_evaluation_receipt.json").read_text(encoding="utf-8"))
        freeze = json.loads((fusion / "freeze_manifest.json").read_text(encoding="utf-8"))
        metrics = json.loads((fusion / "metrics.json").read_text(encoding="utf-8"))
        policy = tomllib.loads((root / "configs/fusion_alert_policy.toml").read_text(encoding="utf-8"))
        predictions = pd.read_parquet(fusion / "artifacts/test_internal_fusion_predictions.parquet")
        self.assertEqual(receipt["status"], "complete")
        self.assertEqual(receipt["read_count"], 1)
        self.assertFalse(freeze["test_internal_read"])
        self.assertFalse(metrics["test_internal"]["evaluation_protocol"]["used_for_selection"])
        self.assertEqual(policy["source_partition"], "validation")
        self.assertLess(policy["thresholds"]["attention"], policy["thresholds"]["alert"])
        self.assertLess(policy["thresholds"]["alert"], policy["thresholds"]["critical"])
        self.assertTrue(predictions.risk_score.between(0, 1).all())
        self.assertTrue(predictions.disagreement.ge(0).all())
        self.assertTrue((predictions.health_score - 100 * (1 - predictions.risk_score)).abs().lt(1e-10).all())
        self.assertEqual(set(predictions.prediction_status), {"valid"})
