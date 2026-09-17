"""Contract and integration tests for the local application service."""

from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from predictive_maintenance.application.local_service import (
    ApplicationSelection,
    ArtifactCompatibilityError,
    ConfigurationUnavailableError,
    LocalApplicationService,
)


ROOT = Path(__file__).resolve().parents[1]


class LocalApplicationServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = LocalApplicationService(ROOT)

    def selection(self, **changes):
        values = dict(
            unit_id=self.service.available_units[0],
            horizon=30,
            model="fusion",
            telemetry_policy="full",
            inference_cadence="each_cycle",
            retrospective=False,
        )
        values.update(changes)
        return ApplicationSelection(**values)

    def test_full_telemetry_produces_valid_contract_scores(self):
        result = self.service.run(self.selection())
        frame = result.trajectory
        self.assertTrue(frame.prediction_status.eq("valid").all())
        self.assertTrue(frame.input_validity.eq("valid").all())
        self.assertTrue(frame.risk_score.between(0.0, 1.0).all())
        np.testing.assert_allclose(frame.survival_score, 1.0 - frame.risk_score)
        np.testing.assert_allclose(frame.health_score, 100.0 * frame.survival_score)
        self.assertNotIn("rul_evaluation", frame.columns)

    def test_rul_is_visible_only_in_explicit_retrospective_mode(self):
        result = self.service.run(self.selection(retrospective=True))
        self.assertIn("rul_evaluation", result.trajectory.columns)
        # Prediction origins are restricted to cycles where the unit is still
        # operational (T_i > t), so the last valid origin has RUL=1.
        self.assertEqual(int(result.trajectory.rul_evaluation.iloc[-1]), 1)
        self.assertTrue(result.summary["retrospective"])

    def test_filtered_held_values_are_degraded_not_new_observations(self):
        frame = self.service.run(self.selection(telemetry_policy="fixed_k3")).trajectory
        degraded = frame.loc[frame.prediction_status.eq("degraded")]
        self.assertGreater(len(degraded), 0)
        self.assertTrue(degraded.max_sensor_age_cycles.gt(0).all())
        self.assertTrue((~degraded.telemetry_transmitted).all())
        self.assertTrue(degraded.risk_score.between(0.0, 1.0).all())

    def test_stale_telemetry_is_explicitly_unavailable(self):
        frame = self.service.run(self.selection(telemetry_policy="fixed_k5")).trajectory
        stale = frame.loc[frame.telemetry_stale]
        self.assertGreater(len(stale), 0)
        self.assertTrue(stale.prediction_status.eq("unavailable").all())
        self.assertTrue(stale.input_validity.eq("stale").all())
        self.assertTrue(stale.risk_score.isna().all())

    def test_on_transmission_cadence_marks_cycles_without_packets_unavailable(self):
        frame = self.service.run(self.selection(
            telemetry_policy="fixed_k3", inference_cadence="on_transmission",
        )).trajectory
        held = frame.loc[~frame.telemetry_transmitted]
        self.assertGreater(len(held), 0)
        self.assertTrue(held.prediction_status.eq("unavailable").all())
        self.assertTrue(held.risk_score.isna().all())

    def test_model_without_filtered_artifact_is_not_silently_substituted(self):
        frame = self.service.run(self.selection(
            model="transformer", telemetry_policy="fixed_k3",
        )).trajectory
        self.assertTrue(frame.prediction_status.eq("unavailable").all())
        self.assertTrue(frame.input_validity.eq("invalid").all())
        self.assertTrue(frame.risk_score.isna().all())
        self.assertTrue(frame.reason_codes.str.contains(
            "MODEL_NOT_AVAILABLE_FOR_TELEMETRY_POLICY"
        ).all())

    def test_invalid_selection_is_rejected(self):
        invalid = (
            self.selection(unit_id=999999),
            self.selection(horizon=16),
            self.selection(model="unknown"),
            self.selection(telemetry_policy="unknown"),
            self.selection(inference_cadence="future_aware"),
        )
        for selection in invalid:
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                self.service.run(selection)

    def test_missing_configuration_is_explicit(self):
        missing = ROOT / "configs" / "does_not_exist.toml"
        with self.assertRaises(ConfigurationUnavailableError):
            LocalApplicationService(ROOT, missing)

    def test_incompatible_model_artifact_is_explicit(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            path = Path(directory) / "incompatible.parquet"
            pd.DataFrame({"unit_id": [1], "cycle": [1]}).to_parquet(path, index=False)
            with self.assertRaises(ArtifactCompatibilityError):
                LocalApplicationService._read_parquet_contract(
                    path, {"unit_id", "cycle", "risk_score"}
                )

    def test_invalid_persisted_risk_is_not_presented_as_valid(self):
        original = self.service._selected_model_scores

        def invalid_score(selection):
            frame = original(selection).copy()
            frame.loc[frame.index[0], "risk_score"] = 1.5
            return frame

        with patch.object(self.service, "_selected_model_scores", side_effect=invalid_score):
            frame = self.service.run(self.selection()).trajectory
        first = frame.iloc[0]
        self.assertEqual(first.prediction_status, "unavailable")
        self.assertEqual(first.input_validity, "invalid")
        self.assertTrue(pd.isna(first.risk_score))
        self.assertIn("INVALID_RISK_SCORE_ARTIFACT", first.reason_codes)

    def test_multiple_units_cover_each_operational_cycle_to_event_boundary(self):
        for unit_id in self.service.available_units[:3]:
            with self.subTest(unit_id=unit_id):
                result = self.service.run(self.selection(
                    unit_id=unit_id, retrospective=True,
                ))
                trajectory = result.trajectory
                terminal_cycle = int(
                    self.service._unit_validation(unit_id).cycle.max()
                )
                self.assertEqual(int(trajectory.cycle.iloc[0]), 1)
                self.assertEqual(int(trajectory.cycle.iloc[-1]), terminal_cycle - 1)
                self.assertEqual(int(trajectory.rul_evaluation.iloc[-1]), 1)
                self.assertTrue(trajectory.prediction_status.eq("valid").all())
                self.assertTrue(trajectory.risk_score.between(0.0, 1.0).all())

    def test_assurance_is_evidence_summary_without_certification_claim(self):
        assurance = self.service.run(self.selection()).assurance
        self.assertFalse(assurance["certification_claim"])
        self.assertIn("not a safety certificate", assurance["claim"].lower())
        self.assertEqual(assurance["horizon"], 30)
        self.assertIn("requirements", assurance)
        self.assertIn("open_assumptions", assurance)


if __name__ == "__main__":
    unittest.main()
