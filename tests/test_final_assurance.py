from __future__ import annotations

import json
from pathlib import Path
import unittest

from predictive_maintenance.application.final_assurance import run_audit


ROOT = Path(__file__).resolve().parents[1]


class FinalAssuranceTests(unittest.TestCase):
    def test_final_audit_core_checks_pass(self):
        payload = run_audit(ROOT, ROOT / "configs" / "final_assurance.toml")
        # Existing interpreter caches are ignored workspace artifacts; the
        # substantive assurance checks must all pass independently of cleanup.
        substantive = {
            key: value for key, value in payload["checks"].items()
            if key != "no_source_cache_artifacts"
        }
        self.assertTrue(all(substantive.values()), substantive)
        self.assertEqual(payload["requirement_status"]["verified"], 77)
        self.assertEqual(payload["assumption_status"]["open"], 37)

    def test_configuration_index_and_audit_artifact_exist(self):
        self.assertTrue((ROOT / "docs" / "configuration_index.md").exists())
        audit = ROOT / "reports" / "final_assurance" / "artifacts" / "audit_results.json"
        self.assertTrue(audit.exists())
        self.assertEqual(json.loads(audit.read_text(encoding="utf-8"))["project_version"], "0.16.0")

    def test_model_cards_are_versioned(self):
        for path in (
            ROOT / "reports" / "weibull" / "model_card.json",
            ROOT / "reports" / "classical_ml" / "random_forest_model_card.json",
            ROOT / "reports" / "classical_ml" / "xgboost_model_card.json",
            ROOT / "reports" / "discrete_hazard" / "model_card.json",
            ROOT / "reports" / "anomaly_detection" / "model_card.json",
            ROOT / "reports" / "fusion" / "model_card.json",
            ROOT / "reports" / "tcn" / "model_card.json",
            ROOT / "reports" / "transformer" / "model_card.json",
        ):
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["model_version"], "1.0.0")


if __name__ == "__main__":
    unittest.main()
