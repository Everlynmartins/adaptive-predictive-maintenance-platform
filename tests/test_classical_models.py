"""Common risk-contract tests for Random Forest and XGBoost adapters."""

from pathlib import Path
import tempfile
import unittest

from predictive_maintenance.core.records import FeatureRecord, TargetRecord
from predictive_maintenance.models.ml.classical import (
    RandomForestRiskModel, TreeModelConfig, XGBoostRiskModel,
)
from predictive_maintenance.evaluation.probability import threshold_metrics


def _records(horizon=3):
    features = [FeatureRecord(str(unit), cycle, {"a": float(cycle), "b": float(unit + cycle)})
                for unit in (1, 2, 3) for cycle in range(1, 8)]
    targets = [TargetRecord(item.unit_id, item.cycle, {
        "horizon": horizon, "failure_within_horizon": int(item.cycle >= 5),
    }) for item in features]
    return features, targets


def _model(model_class, horizon=3):
    parameters = ({"n_estimators": 12, "max_depth": 3, "min_samples_leaf": 1,
                   "max_features": "sqrt"} if model_class is RandomForestRiskModel else
                  {"n_estimators": 12, "max_depth": 2, "learning_rate": 0.1,
                   "subsample": 1.0, "colsample_bytree": 1.0,
                   "min_child_weight": 1.0, "reg_lambda": 1.0, "tree_method": "hist"})
    return model_class(TreeModelConfig(
        model_name=model_class.algorithm, model_version="test", horizon=horizon,
        random_seed=9, parameters=parameters,
    ), ("a", "b"))


class ClassicalModelTests(unittest.TestCase):
    def test_scores_bounds_reproducibility_and_horizon_contract(self):
        features, targets = _records()
        for model_class in (RandomForestRiskModel, XGBoostRiskModel):
            with self.subTest(model=model_class.__name__):
                first = _model(model_class).fit(features, targets)
                second = _model(model_class).fit(features, targets)
                predictions = first.predict_risk(features, horizon=3)
                self.assertEqual(predictions, second.predict_risk(features, horizon=3))
                self.assertTrue(all(0 <= item.risk_score <= 1 for item in predictions))
                self.assertTrue(all(item.horizon == 3 for item in predictions))
                with self.assertRaisesRegex(ValueError, "supports only horizon"):
                    first.predict_risk(features, horizon=4)

    def test_save_load_reproduces_predictions_and_configuration(self):
        features, targets = _records()
        for model_class in (RandomForestRiskModel, XGBoostRiskModel):
            with self.subTest(model=model_class.__name__), tempfile.TemporaryDirectory() as directory:
                model = _model(model_class).fit(features, targets)
                path = Path(directory) / "model.joblib"
                model.save(path)
                loaded = model_class.load(path)
                self.assertEqual(model.config, loaded.config)
                self.assertEqual(model.predict_risk(features, horizon=3),
                                 loaded.predict_risk(features, horizon=3))

    def test_invalid_input_returns_explicit_unavailable_status(self):
        features, targets = _records()
        model = _model(RandomForestRiskModel).fit(features, targets)
        invalid = FeatureRecord("1", 8, {"a": float("nan"), "b": 2.0})
        output = model.predict_risk([invalid], horizon=3)[0]
        self.assertEqual(output.prediction_status, "unavailable")
        self.assertEqual(output.input_validity, "invalid")
        self.assertIsNone(output.risk_score)
        self.assertTrue(output.explanation)

    def test_target_horizon_must_equal_model_horizon(self):
        features, targets = _records(horizon=4)
        with self.assertRaisesRegex(ValueError, "configured horizon"):
            _model(RandomForestRiskModel, horizon=3).fit(features, targets)

    def test_training_summary_records_class_and_unit_weighting(self):
        features, targets = _records()
        model = _model(RandomForestRiskModel).fit(features, targets)
        self.assertEqual(model.training_summary["units"], 3)
        self.assertIn("unit", model.training_summary["weighting"])
        self.assertIn("class", model.training_summary["weighting"])
        self.assertGreater(model.training_summary["weight_max"], 0)

    def test_exploratory_threshold_metrics_use_explicit_threshold(self):
        result = threshold_metrics([0, 0, 1, 1], [0.1, 0.6, 0.4, 0.9], threshold=0.5)
        self.assertEqual(result["threshold"], 0.5)
        self.assertEqual((result["precision"], result["recall"], result["f1"]),
                         (0.5, 0.5, 0.5))


if __name__ == "__main__":
    unittest.main()
