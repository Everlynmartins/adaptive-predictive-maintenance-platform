"""Receiver-aware causal feature tests for filtered telemetry experiments."""

from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from predictive_maintenance.features.causal import CausalFeatureConfig, CausalTelemetryFeatures


def _full_telemetry() -> pd.DataFrame:
    return pd.DataFrame({
        "unit_id": [1, 1, 1, 1, 2, 2, 2, 2],
        "cycle": [1, 2, 3, 4, 1, 2, 3, 4],
        "sensor_1": [1.0, 2.0, 4.0, 8.0, 100.0, 101.0, 103.0, 106.0],
        "sensor_2": [7.0] * 8,
        "setting_1": [0.0, 0.1, 0.0, -0.1, 0.2, 0.1, 0.0, -0.1],
    })


def _sparse_receiver() -> tuple[pd.DataFrame, pd.DataFrame]:
    telemetry = pd.DataFrame({
        "unit_id": [1, 1, 1, 1, 1],
        "cycle": [1, 2, 3, 4, 5],
        "sensor_1": [1.0, 1.0, 3.0, 3.0, 9.0],
    })
    observed = pd.DataFrame({"sensor_1": [True, False, True, False, True]})
    return telemetry, observed


class ReceiverAwareFeatureTests(unittest.TestCase):
    def setUp(self):
        self.config = CausalFeatureConfig(windows=(2, 3))

    def test_all_observed_is_numerically_and_schema_compatible(self):
        telemetry = _full_telemetry()
        observed = pd.DataFrame(
            True,
            index=telemetry.index,
            columns=[name for name in telemetry if name not in {"unit_id", "cycle"}],
        )
        regular = CausalTelemetryFeatures(self.config).fit_frame(telemetry)
        receiver = CausalTelemetryFeatures(self.config).fit_receiver_frame(
            telemetry, observed
        )

        self.assertEqual(regular.artifact_schema, receiver.artifact_schema)
        self.assertEqual(regular.raw_columns, receiver.raw_columns)
        self.assertEqual(regular.feature_names, receiver.feature_names)
        self.assertEqual(regular.imputation_medians, receiver.imputation_medians)
        pd.testing.assert_frame_equal(
            regular.transform_frame(telemetry),
            receiver.transform_receiver_frame(telemetry, observed),
        )

    def test_holds_copy_features_without_updating_history(self):
        telemetry, observed = _sparse_receiver()
        engineer = CausalTelemetryFeatures(self.config).fit_receiver_frame(
            telemetry, observed
        )
        result = engineer.transform_receiver_frame(telemetry, observed)

        self.assertEqual(result.loc[1, "age_cycle"], 2.0)
        self.assertEqual(result.loc[1, "sensor_1__current"], 1.0)
        self.assertEqual(result.loc[1, "sensor_1__mean_w3"], 1.0)
        self.assertEqual(result.loc[1, "sensor_1__cumulative_abs_change"], 0.0)
        self.assertEqual(result.loc[2, "sensor_1__delta"], 2.0)
        self.assertEqual(result.loc[3, "sensor_1__delta"], 2.0)
        self.assertEqual(result.loc[2, "sensor_1__mean_w3"], 2.0)
        self.assertEqual(result.loc[3, "sensor_1__mean_w3"], 2.0)
        self.assertEqual(result.loc[2, "sensor_1__cumulative_abs_change"], 2.0)
        self.assertEqual(result.loc[3, "sensor_1__cumulative_abs_change"], 2.0)

    def test_sparse_slope_uses_real_cycles(self):
        telemetry, observed = _sparse_receiver()
        engineer = CausalTelemetryFeatures(self.config).fit_receiver_frame(
            telemetry, observed
        )
        result = engineer.transform_receiver_frame(telemetry, observed)

        # Observations are (cycle, value) = (1, 1), (3, 3), (5, 9).
        # OLS on real cycles gives slope 2.0; treating them as adjacent gives 4.0.
        self.assertAlmostEqual(result.loc[4, "sensor_1__slope_w3"], 2.0)
        self.assertAlmostEqual(result.loc[4, "sensor_1__slope_w2"], 3.0)

    def test_values_on_unobserved_rows_cannot_affect_features(self):
        telemetry, observed = _sparse_receiver()
        engineer = CausalTelemetryFeatures(self.config).fit_receiver_frame(
            telemetry, observed
        )
        expected = engineer.transform_receiver_frame(telemetry, observed)
        changed = telemetry.copy()
        changed.loc[~observed.sensor_1, "sensor_1"] = [1e12, -1e12]
        actual = engineer.transform_receiver_frame(changed, observed)
        pd.testing.assert_frame_equal(expected, actual)

    def test_future_transmission_cannot_change_prefix(self):
        telemetry, observed = _sparse_receiver()
        engineer = CausalTelemetryFeatures(self.config).fit_receiver_frame(
            telemetry, observed
        )
        prefix_frame = telemetry.iloc[:4].copy()
        prefix_mask = observed.iloc[:4].copy()
        expected = engineer.transform_receiver_frame(prefix_frame, prefix_mask)
        changed = telemetry.copy()
        changed.loc[4, "sensor_1"] = 1e9
        actual = engineer.transform_receiver_frame(changed, observed).iloc[:4]
        pd.testing.assert_frame_equal(expected, actual)

    def test_history_never_crosses_unit_boundary(self):
        telemetry = pd.DataFrame({
            "unit_id": [1, 1, 1, 2, 2, 2],
            "cycle": [1, 2, 3, 1, 2, 3],
            "sensor_1": [1.0, 1.0, 5.0, 100.0, 100.0, 106.0],
        })
        observed = pd.DataFrame({
            "sensor_1": [True, False, True, True, False, True],
        })
        engineer = CausalTelemetryFeatures(self.config).fit_receiver_frame(
            telemetry, observed
        )
        result = engineer.transform_receiver_frame(telemetry, observed)
        first_unit_2 = result.loc[result.unit_id == 2].iloc[0]
        held_unit_2 = result.loc[result.unit_id == 2].iloc[1]

        self.assertEqual(first_unit_2["sensor_1__current"], 100.0)
        self.assertEqual(first_unit_2["sensor_1__mean_w3"], 100.0)
        self.assertEqual(first_unit_2["sensor_1__cumulative_abs_change"], 0.0)
        self.assertEqual(held_unit_2["sensor_1__current"], 100.0)

    def test_selection_uses_only_new_observations_in_fit_population(self):
        telemetry = pd.DataFrame({
            "unit_id": [1, 1, 1, 1],
            "cycle": [1, 2, 3, 4],
            "sensor_variable": [1.0, 999.0, 2.0, -999.0],
            "sensor_observed_constant": [5.0, 8.0, 5.0, 9.0],
        })
        observed = pd.DataFrame({
            "sensor_variable": [True, False, True, False],
            "sensor_observed_constant": [True, False, True, False],
        })
        engineer = CausalTelemetryFeatures(self.config).fit_receiver_frame(
            telemetry, observed
        )

        self.assertEqual(engineer.raw_columns, ("sensor_variable",))
        self.assertEqual(engineer.dropped_constant_columns, ("sensor_observed_constant",))

    def test_observed_mask_requires_exact_boolean_alignment(self):
        telemetry, observed = _sparse_receiver()
        cases = [
            observed.rename(columns={"sensor_1": "other"}),
            observed.set_axis(pd.RangeIndex(10, 15)),
            observed.astype(int),
        ]
        for invalid in cases:
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "observed_mask"):
                    CausalTelemetryFeatures(self.config).fit_receiver_frame(
                        telemetry, invalid
                    )

    def test_save_load_preserves_receiver_transform(self):
        telemetry, observed = _sparse_receiver()
        engineer = CausalTelemetryFeatures(self.config).fit_receiver_frame(
            telemetry, observed
        )
        expected = engineer.transform_receiver_frame(telemetry, observed)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "features.json"
            engineer.save(path)
            loaded = CausalTelemetryFeatures.load(path)
            actual = loaded.transform_receiver_frame(telemetry, observed)
        pd.testing.assert_frame_equal(expected, actual)

    def test_non_finite_telemetry_is_rejected_even_when_not_observed(self):
        telemetry, observed = _sparse_receiver()
        telemetry.loc[1, "sensor_1"] = np.inf
        with self.assertRaisesRegex(ValueError, "finite numeric"):
            CausalTelemetryFeatures(self.config).fit_receiver_frame(
                telemetry, observed
            )


if __name__ == "__main__":
    unittest.main()
