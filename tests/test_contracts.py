"""Small architectural checks without ingestion or concrete predictive models."""

import importlib
import inspect
from dataclasses import asdict
from pathlib import Path
import tomllib
import unittest

from predictive_maintenance.core.records import RiskPrediction
from predictive_maintenance.models.interfaces import RiskModel


class ContractTests(unittest.TestCase):
    def test_all_interfaces_import_and_remain_abstract(self):
        contracts = {
            "data.interfaces": ("TelemetryIngestor", {"ingest"}),
            "features.interfaces": ("FeatureEngineer", {"fit", "transform"}),
            "models.interfaces": ("RiskModel", {"fit", "predict_risk", "save", "load"}),
            "models.anomaly.interfaces": ("AnomalyDetector", {"fit", "detect"}),
            "models.fusion.interfaces": ("ModelFusion", {"fuse"}),
            "filtering.interfaces": ("TelemetryFilter", {"filter", "process", "reset", "metrics"}),
            "evaluation.interfaces": ("Evaluator", {"evaluate"}),
        }
        for module_name, (class_name, methods) in contracts.items():
            with self.subTest(interface=class_name):
                module = importlib.import_module(f"predictive_maintenance.{module_name}")
                contract = getattr(module, class_name)
                self.assertTrue(inspect.isabstract(contract))
                self.assertTrue(methods <= contract.__abstractmethods__)
                with self.assertRaises(TypeError):
                    contract()

    def test_extension_packages_import(self):
        for name in ("core", "models.reliability", "models.ml", "models.temporal", "application"):
            with self.subTest(package=name):
                importlib.import_module(f"predictive_maintenance.{name}")

    def test_load_is_a_class_method(self):
        self.assertIsInstance(inspect.getattr_static(RiskModel, "load"), classmethod)

    def test_standard_output_and_optional_extensions(self):
        prediction = RiskPrediction(
            unit_id="unit-1", cycle=10, horizon=30, risk_score=0.2,
            model_name="contract-fixture", model_version="test",
            prediction_status="available", input_validity="valid",
        )
        self.assertEqual(
            set(asdict(prediction)),
            {"unit_id", "cycle", "horizon", "risk_score", "health_score", "model_name",
             "model_version", "uncertainty", "anomaly_score", "explanation",
             "survival_score", "prediction_status", "input_validity", "disagreement"},
        )
        self.assertIsNone(prediction.uncertainty)
        self.assertIsNone(prediction.anomaly_score)
        self.assertIsNone(prediction.explanation)
        extended = RiskPrediction(
            unit_id="unit-1", cycle=10, horizon=15, risk_score=0.0,
            model_name="contract-fixture", model_version="test",
            prediction_status="available", input_validity="valid",
            uncertainty={"standard_deviation": 0.1},
            anomaly_score=2.5,
            explanation="Schema fixture only.",
        )
        self.assertEqual(extended.uncertainty["standard_deviation"], 0.1)

    def test_risk_and_health_reject_invalid_scores(self):
        for field in ("risk_score", "health_score"):
            for value in (-0.01, 1.01, float("nan"), float("inf"), -float("inf")):
                with self.subTest(field=field, value=value):
                    scores = {"risk_score": 0.2, "health_score": 80.0, field: value}
                    with self.assertRaises(ValueError):
                        RiskPrediction(unit_id="unit-1", cycle=10, horizon=30,
                                       model_name="fixture", model_version="test",
                                       prediction_status="available", input_validity="valid", **scores)

    def test_python_requirement_and_changelog_match_project(self):
        root = Path(__file__).resolve().parents[1]
        metadata = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(metadata["project"]["requires-python"], ">=3.11,<3.12")
        self.assertEqual((root / ".python-version").read_text().strip(), "3.11")
        changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn(f'## [{metadata["project"]["version"]}]', changelog)


if __name__ == "__main__":
    unittest.main()
