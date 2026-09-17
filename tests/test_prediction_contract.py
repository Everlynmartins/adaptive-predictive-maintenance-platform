"""Executable checks for the demonstrator contract, without predictive models."""

from dataclasses import asdict
import inspect
import unittest

import pandas as pd

from predictive_maintenance.core.records import FeatureRecord, RiskPrediction
from predictive_maintenance.data.targets import (
    HorizonConfig, build_evaluation_targets, build_operational_targets,
)
from predictive_maintenance.models.interfaces import RiskModel


def prediction(**changes):
    fields = dict(unit_id="1", cycle=10, horizon=30, risk_score=0.2,
                  model_name="schema-fixture", model_version="test",
                  prediction_status="available", input_validity="valid")
    fields.update(changes)
    return RiskPrediction(**fields)


class PredictionContractTests(unittest.TestCase):
    def test_horizon_status_validity_required_and_serialized(self):
        record = asdict(prediction())
        self.assertEqual(record["horizon"], 30)
        self.assertEqual(record["prediction_status"], "available")
        self.assertEqual(record["input_validity"], "valid")
        fields = {k: v for k, v in record.items() if k != "survival_score"}
        for name in ("horizon", "prediction_status", "input_validity"):
            missing = {k: v for k, v in fields.items() if k != name}
            with self.subTest(name=name), self.assertRaises(TypeError):
                RiskPrediction(**missing)
        parameter = inspect.signature(RiskModel.predict_risk).parameters["horizon"]
        self.assertEqual(parameter.kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertIs(parameter.default, inspect.Parameter.empty)

    def test_probability_bounds_and_complementary_scores(self):
        for probability in (0., 0.2, 1.):
            record = prediction(risk_score=probability)
            self.assertAlmostEqual(record.survival_score, 1 - probability)
            self.assertAlmostEqual(record.health_score, 100 * (1 - probability))
        self.assertEqual(prediction(health_score=80.).health_score, 80.)
        for value in (-0.01, 1.01, float("nan"), float("inf"), -float("inf"), True, None, "0.2"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                prediction(risk_score=value)
        with self.assertRaises(ValueError):
            prediction(health_score=0.8)

    def test_unavailable_never_becomes_zero_risk(self):
        for validity in ("valid", "invalid", "stale", "unknown"):
            record = prediction(risk_score=None, prediction_status="unavailable",
                                input_validity=validity, explanation="No usable probability.")
            self.assertIsNone(record.risk_score)
            self.assertIsNone(record.survival_score)
            self.assertIsNone(record.health_score)
        terminal = prediction(risk_score=None, prediction_status="not_operational",
                              explanation="Terminal event already observed.")
        self.assertIsNone(terminal.risk_score)
        for changes in (
            dict(prediction_status="unavailable"),
            dict(prediction_status="unavailable", risk_score=None),
            dict(prediction_status="unavailable", risk_score=None, health_score=100., explanation="x"),
            dict(prediction_status="not_operational", risk_score=1., explanation="x"),
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                prediction(**changes)

    def test_invalid_input_or_metadata_cannot_be_available(self):
        for validity in ("invalid", "stale", "unknown", "bogus"):
            with self.subTest(validity=validity), self.assertRaises(ValueError):
                prediction(input_validity=validity)
        for name, values in {
            "horizon": (0, -1, 30., True), "cycle": (0, -1, True),
            "model_name": ("", None), "model_version": (" ", None),
            "unit_id": ("", 1), "prediction_status": ("", "ready"),
        }.items():
            for value in values:
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    prediction(**{name: value})

    def test_anomaly_is_not_probability_and_disagreement_is_optional(self):
        record = prediction(anomaly_score=4.5)
        self.assertEqual(record.risk_score, 0.2)
        self.assertEqual(record.anomaly_score, 4.5)
        self.assertIsNone(record.disagreement)
        self.assertEqual(prediction(disagreement=0.3).disagreement, 0.3)
        for value in (-0.1, 1.1, float("nan")):
            with self.assertRaises(ValueError):
                prediction(disagreement=value)


class CausalityGuardTests(unittest.TestCase):
    def test_retrospective_fields_rejected_at_feature_boundary(self):
        for name in ("RUL", "normalized_life", "final_cycle", "max_cycle", "T_i",
                     "unit_final_time", "cycle_max", "is_operational", "horizon",
                     "failure_within_horizon", "failure_within_critical_horizon",
                     "failure_within_60", "future_sensor_1", "Final Cycle"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                FeatureRecord("1", 1, {name: 1.})

    def test_feature_mapping_cannot_be_mutated_after_guard(self):
        values = {"sensor_2": 600., "setting_1": 0.}
        record = FeatureRecord("1", 10, values)
        values["RUL"] = 30.
        self.assertNotIn("RUL", record.values)
        with self.assertRaises(TypeError):
            record.values["normalized_life"] = 0.5


class OperationalTargetTests(unittest.TestCase):
    def test_nonnegative_decreasing_rul_terminal_zero_and_no_unit_mixing(self):
        # Interleaved units of different lengths, including a terminal-only unit.
        frame = pd.DataFrame({"unit_id": [1, 2, 3, 1, 2, 2, 2],
                              "cycle": [1, 1, 1, 2, 2, 3, 4]})
        targets = build_evaluation_targets(frame, HorizonConfig(2, 1),
                                           complete_run_to_failure=True)
        self.assertEqual(targets.RUL.tolist(), [1, 3, 0, 0, 2, 1, 0])
        self.assertTrue(targets.RUL.ge(0).all())
        for _, unit in targets.groupby("unit_id"):
            self.assertEqual(unit.RUL.iloc[-1], 0)
            self.assertTrue(unit.RUL.diff().dropna().eq(-1).all())
        self.assertEqual(targets.failure_within_horizon.tolist(),
                         [True, False, True, True, True, True, True])

    def test_operational_population_excludes_terminal_and_keeps_horizons(self):
        frame = pd.DataFrame({"unit_id": [1] * 40 + [2],
                              "cycle": list(range(1, 41)) + [1]})
        original = frame.copy(deep=True)
        retrospective = build_evaluation_targets(frame, HorizonConfig(),
                                                 complete_run_to_failure=True)
        operational = build_operational_targets(frame, HorizonConfig(),
                                                 complete_run_to_failure=True)
        self.assertEqual(len(retrospective), 41)
        self.assertEqual(len(operational), 39)
        self.assertTrue(operational.RUL.gt(0).all())
        self.assertEqual(set(operational.unit_id), {1})
        self.assertEqual(int(operational.failure_within_horizon.sum()), 30)
        self.assertEqual(int(operational.failure_within_critical_horizon.sum()), 15)
        self.assertTrue(operational.horizon.eq(30).all())
        self.assertTrue(operational.critical_horizon.eq(15).all())
        self.assertFalse(operational.loc[operational.RUL > 30, "failure_within_horizon"].any())
        self.assertTrue(operational.loc[operational.RUL <= 30, "failure_within_horizon"].all())
        pd.testing.assert_frame_equal(frame, original)
        with self.assertRaises(ValueError):
            build_operational_targets(frame, HorizonConfig(), complete_run_to_failure=False)
