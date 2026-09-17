"""Unit tests for probability fusion, calibration and alert status contracts."""

from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from predictive_maintenance.core.records import FusionPrediction, RiskPrediction
from predictive_maintenance.models.fusion.probabilistic import (
    AlertThresholds,
    FrozenEvaluationGate,
    LogisticStackingFusion,
    ProbabilityCalibrator,
    RISK_COMPONENTS,
    SimpleProbabilityEnsemble,
    StackingConfig,
    alert_metrics_by_unit,
    assign_alert_levels,
)


def risk(model: str, value: float | None, *, status: str = "available") -> RiskPrediction:
    return RiskPrediction(unit_id="1", cycle=10, horizon=30, risk_score=value,
        model_name=model, model_version="1", prediction_status=status,
        input_validity="valid", explanation=(None if status == "available" else "missing"))


def stacking_frame() -> pd.DataFrame:
    rows = []
    for unit in range(1, 7):
        for cycle in range(1, 7):
            label = int(cycle >= 5)
            base = 0.05 + 0.15 * cycle
            row = {"unit_id": unit, "cycle": cycle, "horizon": 30,
                   "label": label, "partition": "train_oof", "anomaly_score": base}
            row.update({name: min(0.99, base + offset) for name, offset in
                        zip(RISK_COMPONENTS, (0.0, 0.01, -0.01, 0.02), strict=True)})
            rows.append(row)
    return pd.DataFrame(rows)


class FusionContractTests(unittest.TestCase):
    def test_simple_fusion_probability_health_and_disagreement(self):
        output = SimpleProbabilityEnsemble().fuse([
            [risk("a", 0.2)], [risk("b", 0.4)], [risk("c", 0.6)]])[0]
        self.assertEqual(output.prediction_status, "valid")
        self.assertAlmostEqual(output.risk_score, 0.4)
        self.assertAlmostEqual(output.survival_score, 0.6)
        self.assertAlmostEqual(output.health_score, 60.0)
        self.assertGreaterEqual(output.disagreement, 0.0)

    def test_anomaly_score_is_not_an_arithmetic_probability_component(self):
        output = SimpleProbabilityEnsemble().fuse([[risk("a", 0.2)], [risk("b", 0.4)]])[0]
        self.assertAlmostEqual(output.risk_score, 0.3)
        self.assertIsNone(output.anomaly_score)
        frame = stacking_frame()
        frame["anomaly_score"] = 7.0  # finite analytical covariate, not bounded probability
        LogisticStackingFusion(StackingConfig(horizon=30)).fit_frame(frame)

    def test_degraded_and_unavailable_status_are_explicit(self):
        ensemble = SimpleProbabilityEnsemble(minimum_components=2)
        degraded = ensemble.fuse([[risk("a", 0.2)], [risk("b", 0.4)],
                                  [risk("c", None, status="unavailable")]])[0]
        self.assertEqual(degraded.prediction_status, "degraded")
        self.assertAlmostEqual(degraded.risk_score, 0.3)
        unavailable = ensemble.fuse([[risk("a", 0.2)],
                                     [risk("b", None, status="unavailable")]])[0]
        self.assertEqual(unavailable.prediction_status, "unavailable")
        self.assertIsNone(unavailable.risk_score)

    def test_unavailable_fusion_cannot_silently_carry_zero_risk(self):
        with self.assertRaises(ValueError):
            FusionPrediction(unit_id="1", cycle=1, horizon=15, risk_score=0.0,
                model_name="fusion", model_version="1", prediction_status="unavailable",
                input_validity="valid", component_status={"a": "missing"},
                explanation="missing")


class StackingCalibrationTests(unittest.TestCase):
    def test_meta_model_accepts_only_train_oof_predictions(self):
        frame = stacking_frame()
        frame["partition"] = "validation"
        with self.assertRaisesRegex(ValueError, "train_oof"):
            LogisticStackingFusion(StackingConfig(horizon=30)).fit_frame(frame)

    def test_reproducibility_save_load_and_probability_bounds(self):
        frame = stacking_frame()
        first = LogisticStackingFusion(StackingConfig(horizon=30, random_seed=77)).fit_frame(frame)
        second = LogisticStackingFusion(StackingConfig(horizon=30, random_seed=77)).fit_frame(frame)
        p1, p2 = first.predict_frame(frame), second.predict_frame(frame)
        np.testing.assert_array_equal(p1, p2)
        self.assertTrue(((0 <= p1) & (p1 <= 1)).all())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stack.joblib"
            first.save(path)
            loaded = LogisticStackingFusion.load(path)
            np.testing.assert_array_equal(p1, loaded.predict_frame(frame))

    def test_stacking_missing_component_or_stale_input_is_unavailable(self):
        frame = stacking_frame()
        model = LogisticStackingFusion(StackingConfig(horizon=30)).fit_frame(frame)
        values = {name: 0.2 for name in RISK_COMPONENTS}
        values["risk_weibull"] = None
        missing = model.predict_record(unit_id="1", cycle=3,
            base_probabilities=values, anomaly_score=0.4)
        self.assertEqual(missing.prediction_status, "unavailable")
        self.assertIsNone(missing.risk_score)
        values["risk_weibull"] = 0.1
        stale = model.predict_record(unit_id="1", cycle=3,
            base_probabilities=values, anomaly_score=0.4, input_validity="stale")
        self.assertEqual(stale.prediction_status, "unavailable")
        self.assertIsNone(stale.risk_score)

    def test_platt_and_isotonic_are_finite_and_round_trip(self):
        scores = np.linspace(0.01, 0.99, 30)
        labels = (scores > 0.55).astype(int)
        for method in ("none", "platt", "isotonic"):
            with self.subTest(method=method), tempfile.TemporaryDirectory() as directory:
                calibrator = ProbabilityCalibrator(method, seed=8).fit(scores, labels)
                predicted = calibrator.predict(scores)
                self.assertTrue(np.isfinite(predicted).all())
                self.assertTrue(((0 <= predicted) & (predicted <= 1)).all())
                path = Path(directory) / "cal.joblib"
                calibrator.save(path)
                np.testing.assert_array_equal(predicted, ProbabilityCalibrator.load(path).predict(scores))


class AlertPolicyTests(unittest.TestCase):
    def test_thresholds_are_strictly_ordered(self):
        AlertThresholds(0.2, 0.5, 0.8)
        with self.assertRaises(ValueError):
            AlertThresholds(0.5, 0.5, 0.8)

    def test_persistence_and_temporal_unit_metrics(self):
        rows = []
        for cycle, (p15, p30) in enumerate(((.1,.1),(.1,.6),(.2,.7),(.9,.9)), 1):
            rows.extend([{"unit_id": 1, "cycle": cycle, "horizon": 15, "risk_score": p15},
                         {"unit_id": 1, "cycle": cycle, "horizon": 30, "risk_score": p30}])
        levels = assign_alert_levels(pd.DataFrame(rows), AlertThresholds(.2,.5,.8,persistence_cycles=2))
        self.assertEqual(levels.alert_level.tolist(), ["normal", "normal", "alerta", "alerta"])
        frame = pd.DataFrame({"unit_id": [1]*5, "cycle": range(1,6),
            "risk_score": [.1,.6,.7,.1,.8], "label": [0,0,0,1,1], "RUL": [5,4,3,2,1]})
        metrics = alert_metrics_by_unit(frame, threshold=.5, persistence_cycles=2).iloc[0]
        self.assertEqual(metrics.false_alert_episode_count, 1)
        self.assertEqual(metrics.false_alert_episode_duration, 2)
        self.assertEqual(metrics.longest_consecutive_alert, 2)

    def test_holdout_gate_requires_freeze_and_refuses_second_evaluation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gate = FrozenEvaluationGate(root / "freeze.json", root / "receipt.json")
            with self.assertRaises(RuntimeError):
                gate.authorize_single_read()
            (root / "freeze.json").write_text('{"state":"frozen","test_internal_read":false}')
            self.assertEqual(gate.authorize_single_read()["state"], "frozen")
            (root / "receipt.json").write_text("{}")
            with self.assertRaisesRegex(RuntimeError, "already"):
                gate.authorize_single_read()
