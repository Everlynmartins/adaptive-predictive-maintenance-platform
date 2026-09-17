"""Verification for calibration, explanation semantics and cluster bootstrap."""

from __future__ import annotations

import json
import unittest

import numpy as np
import pandas as pd

from predictive_maintenance.application.explainability_uncertainty_fd001 import _validate_config
from predictive_maintenance.evaluation.calibration import (
    calibration_audit,
    calibration_intercept_slope,
    expected_calibration_error,
)
from predictive_maintenance.evaluation.explainability import (
    top_sensor_contributions,
    top_shap_contributions,
    validate_explanation_frame,
)
from predictive_maintenance.evaluation.uncertainty import (
    UnitBootstrapConfig,
    resample_complete_units,
    unit_bootstrap_intervals,
)


class CalibrationAuditTests(unittest.TestCase):
    def test_ece_and_calibration_fit_are_explicit(self):
        labels = np.asarray([0, 0, 0, 1, 1, 1, 0, 1])
        probabilities = np.asarray([0.05, 0.15, 0.25, 0.65, 0.75, 0.95, 0.35, 0.85])
        audit = calibration_audit(labels, probabilities, bins=5)
        self.assertAlmostEqual(
            audit["expected_calibration_error"],
            expected_calibration_error(labels, probabilities, bins=5),
        )
        self.assertEqual(audit["calibration_fit_status"], "available")
        self.assertTrue(np.isfinite(audit["calibration_intercept"]))
        self.assertTrue(np.isfinite(audit["calibration_slope"]))

    def test_uncalculable_calibration_fit_is_not_silenced(self):
        result = calibration_intercept_slope([0, 0, 0], [0.1, 0.2, 0.3])
        self.assertIsNone(result["intercept"])
        self.assertEqual(result["status"], "unavailable_single_class")


class UnitBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({
            "unit_id": [1, 1, 2, 2, 3, 3],
            "cycle": [1, 2, 1, 2, 1, 2],
            "label": [0, 1, 0, 1, 0, 1],
            "risk_score": [0.1, 0.8, 0.2, 0.7, 0.3, 0.9],
        })

    def test_resampling_keeps_whole_units_and_separates_duplicate_draws(self):
        sampled = resample_complete_units(self.frame, [2, 2, 1])
        self.assertEqual(sampled.groupby("unit_id").size().tolist(), [2, 2, 2])
        self.assertEqual(sampled.bootstrap_source_unit_id.tolist(), [2, 2, 2, 2, 1, 1])
        self.assertEqual(sampled.groupby("unit_id").cycle.apply(list).tolist(), [[1, 2]] * 3)

    def test_bootstrap_is_reproducible_and_counts_invalid_replicates(self):
        metrics = {
            "mean": lambda frame: float(frame.risk_score.mean()),
            "undefined": lambda frame: None,
        }
        config = UnitBootstrapConfig(resamples=25, seed=99)
        first = unit_bootstrap_intervals(self.frame, metrics, config=config)
        second = unit_bootstrap_intervals(self.frame, metrics, config=config)
        self.assertEqual(first, second)
        self.assertEqual(first["mean"]["valid_replicates"], 25)
        self.assertEqual(first["undefined"]["invalid_replicates"], 25)
        self.assertEqual(first["mean"]["resampling_unit"], "unit_id complete trajectory")


class ExplanationSemanticsTests(unittest.TestCase):
    def test_local_shap_has_direction_and_relative_magnitude(self):
        keys = pd.DataFrame({"unit_id": [1], "cycle": [4]})
        names = ["sensor_2__current", "sensor_2__slope_w5", "sensor_3__delta"]
        feature_values = np.asarray([[10.0, 2.0, -1.0]])
        shap_values = np.asarray([[0.5, -0.25, 0.25]])
        local = top_shap_contributions(
            keys, names, feature_values, shap_values, horizon=15, top_k=3,
        )
        self.assertEqual(local.direction.tolist(), ["increases_risk", "decreases_risk", "increases_risk"])
        self.assertAlmostEqual(local.relative_magnitude.sum(), 1.0)
        self.assertEqual(local.contribution_space.unique().tolist(), ["xgboost_raw_margin"])
        sensors = top_sensor_contributions(keys, names, shap_values, horizon=15, top_k=2)
        self.assertEqual(sensors.iloc[0].source_signal, "sensor_2")
        self.assertAlmostEqual(sensors.relative_magnitude.sum(), 1.0)

    def test_anomaly_and_disagreement_remain_non_probability_indicators(self):
        frame = pd.DataFrame([{
            "unit_id": 1, "cycle": 2, "horizon": 15,
            "risk_weibull": 0.1, "risk_xgboost": 0.2,
            "risk_hazard_discrete": 0.3, "risk_final": 0.25,
            "anomaly_score": 1.4, "disagreement": 1.2,
            "top_features": json.dumps([]), "top_sensors": json.dumps([]),
            "reason_codes": json.dumps([]), "prediction_status": "valid",
            "input_validity": "valid", "telemetry_stale": False,
        }])
        validate_explanation_frame(frame)
        frame.loc[0, "risk_final"] = 1.2
        with self.assertRaisesRegex(ValueError, "risk fields"):
            validate_explanation_frame(frame)

    def test_scope_guard_rejects_test_or_retraining(self):
        config = {
            "scope": {"use_test_internal": True, "use_official_test": False,
                      "use_official_rul": False, "retrain_models": False},
            "analysis": {"reliability_bins": 10, "shap_batch_size": 10},
        }
        with self.assertRaisesRegex(ValueError, "validation-only"):
            _validate_config(config)
