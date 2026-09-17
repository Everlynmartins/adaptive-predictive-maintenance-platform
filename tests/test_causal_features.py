"""Causality, unit-boundary and persistence tests for telemetry features."""

from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from predictive_maintenance.core.causality import FORBIDDEN_FEATURE_NAMES
from predictive_maintenance.features.causal import CausalFeatureConfig, CausalTelemetryFeatures


def _telemetry() -> pd.DataFrame:
    return pd.DataFrame({
        "unit_id": [1, 1, 1, 1, 2, 2, 2, 2],
        "cycle": [1, 2, 3, 4, 1, 2, 3, 4],
        "sensor_1": [1.0, 2.0, 4.0, 8.0, 100.0, 101.0, 103.0, 106.0],
        "sensor_2": [7.0] * 8,
        "setting_1": [0.0, 0.1, 0.0, -0.1, 0.2, 0.1, 0.0, -0.1],
    })


class CausalFeatureTests(unittest.TestCase):
    def setUp(self):
        self.config = CausalFeatureConfig(windows=(2, 3))

    def test_forbidden_fields_are_absent_and_constants_are_train_selected(self):
        engineer = CausalTelemetryFeatures(self.config).fit_frame(_telemetry())
        self.assertEqual(engineer.dropped_constant_columns, ("sensor_2",))
        canonical = {name.lower() for name in engineer.feature_names}
        self.assertTrue(canonical.isdisjoint(FORBIDDEN_FEATURE_NAMES))
        self.assertFalse(any(name.startswith(("failure_within_", "future_"))
                             for name in canonical))
        self.assertIn("age_cycle", engineer.feature_names)

    def test_future_suffix_cannot_change_existing_features(self):
        training = _telemetry()
        engineer = CausalTelemetryFeatures(self.config).fit_frame(training)
        prefix = training.loc[training.unit_id == 1].iloc[:3].reset_index(drop=True)
        extended = pd.concat([prefix, pd.DataFrame({
            "unit_id": [1, 1], "cycle": [4, 5], "sensor_1": [-1e9, 1e9],
            "sensor_2": [7.0, 7.0], "setting_1": [999.0, -999.0],
        })], ignore_index=True)
        before = engineer.transform_frame(prefix)
        after = engineer.transform_frame(extended).iloc[:len(prefix)]
        pd.testing.assert_frame_equal(before.reset_index(drop=True), after.reset_index(drop=True))

    def test_windows_and_accumulation_never_cross_unit_id(self):
        engineer = CausalTelemetryFeatures(self.config).fit_frame(_telemetry())
        result = engineer.transform_frame(_telemetry())
        first_unit_2 = result.loc[result.unit_id == 2].iloc[0]
        self.assertEqual(first_unit_2["sensor_1__mean_w3"], 100.0)
        self.assertEqual(first_unit_2["sensor_1__min_w3"], 100.0)
        self.assertEqual(first_unit_2["sensor_1__max_w3"], 100.0)
        self.assertEqual(first_unit_2["sensor_1__cumulative_abs_change"], 0.0)

    def test_feature_artifact_round_trip_preserves_transform(self):
        telemetry = _telemetry()
        engineer = CausalTelemetryFeatures(self.config).fit_frame(telemetry)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "features.json"
            engineer.save(path)
            loaded = CausalTelemetryFeatures.load(path)
            pd.testing.assert_frame_equal(
                engineer.transform_frame(telemetry), loaded.transform_frame(telemetry),
            )

    def test_nonfinite_telemetry_is_rejected(self):
        telemetry = _telemetry()
        telemetry.loc[2, "sensor_1"] = np.inf
        with self.assertRaisesRegex(ValueError, "finite numeric"):
            CausalTelemetryFeatures(self.config).fit_frame(telemetry)


if __name__ == "__main__":
    unittest.main()
