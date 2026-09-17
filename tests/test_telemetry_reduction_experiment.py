import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from predictive_maintenance.application.telemetry_reduction_fd001 import (
    _acceptance,
    _config,
    alert_metrics_by_unit_complete,
    evaluate_prediction_table,
)
from predictive_maintenance.filtering.experiment import (
    adaptive_relative_threshold,
    build_filter,
    reconstruct_receiver_stream,
)


def _source(n=6):
    rows = []
    for unit in (1, 2):
        for cycle in range(1, n + 1):
            rows.append({"unit_id": unit, "cycle": cycle,
                         "sensor_1": float(unit * 10 + cycle),
                         "sensor_2": float(unit * 20 + 2 * cycle),
                         "setting_1": float(unit)})
    return pd.DataFrame(rows)


class TelemetryReductionTests(unittest.TestCase):
    def test_source_changes_after_hold_do_not_change_receiver(self):
        source = _source()
        policy = {"id": "k2", "kind": "fixed_interval", "interval_cycles": 2}
        filt, resolved = build_filter(policy, training_reference=source,
            accounting={"metadata_overhead_bytes": 32, "value_bytes": 8},
            stale_after_cycles=3)
        changed = source.copy()
        changed.loc[(changed.unit_id == 1) & (changed.cycle == 2), "sensor_1"] = 99999.0
        left = reconstruct_receiver_stream(source, filt, resolved_policy=resolved)
        filt2, resolved2 = build_filter(policy, training_reference=changed,
            accounting={"metadata_overhead_bytes": 32, "value_bytes": 8}, stale_after_cycles=3)
        right = reconstruct_receiver_stream(changed, filt2, resolved_policy=resolved2)
        self.assertEqual(left.values.loc[(left.values.unit_id == 1) & (left.values.cycle == 2), "sensor_1"].iloc[0],
                         right.values.loc[(right.values.unit_id == 1) & (right.values.cycle == 2), "sensor_1"].iloc[0])

    def test_bytes_and_sensor_accounting(self):
        source = _source()
        full_spec = {"id": "full", "kind": "full"}
        filt, resolved = build_filter(full_spec, training_reference=source,
            accounting={"metadata_overhead_bytes": 32, "value_bytes": 8}, stale_after_cycles=3)
        result = reconstruct_receiver_stream(source, filt, resolved_policy=resolved)
        self.assertEqual(result.communication_metrics["estimated_bytes"], len(source) * 56)
        self.assertEqual(result.communication_metrics["sensor_values_transmitted"], 2 * len(source))
        self.assertEqual(result.communication_metrics["observations_transmitted"], len(source))

    def test_adaptive_threshold_uses_only_training_prefix(self):
        source = _source()
        base = adaptive_relative_threshold(source, ("sensor_1",), 0.95)
        future = pd.concat([source, pd.DataFrame([{"unit_id": 1, "cycle": 7,
            "sensor_1": 1e9, "sensor_2": 1e9, "setting_1": 1.0}])], ignore_index=True)
        changed = adaptive_relative_threshold(future, ("sensor_1",), 0.95)
        self.assertNotEqual(base, changed)
        # The experiment computes this threshold from the explicitly supplied training frame.
        self.assertEqual(base, adaptive_relative_threshold(source, ("sensor_1",), 0.95))

    def test_missing_alert_is_not_finite_latency(self):
        rows = []
        for cycle in range(1, 6):
            rows.append({"unit_id": 1, "cycle": cycle, "RUL": 5 - cycle,
                         "horizon": 3, "label": int(cycle >= 3),
                         "risk_score": 0.9 if cycle >= 3 else 0.01,
                         "prediction_status": "valid", "telemetry_stale": False,
                         "max_sensor_age_cycles": 0, "inference_due": True})
        full = pd.DataFrame(rows)
        filtered = full.copy()
        filtered.loc[:, "risk_score"] = np.nan
        filtered.loc[:, "prediction_status"] = "unavailable"
        metrics, unit = evaluate_prediction_table(filtered, threshold=0.5,
            persistence_cycles=2,
            reference_unit_metrics=alert_metrics_by_unit_complete(full, threshold=0.5, persistence_cycles=2))
        self.assertTrue(pd.isna(unit.first_alert_cycle.iloc[0]))
        self.assertTrue(pd.isna(unit.alert_latency_cycles.iloc[0]))
        self.assertEqual(metrics["missed_anticipated_failures"], 1)

    def test_acceptance_keeps_unavailable_and_stale_explicit(self):
        criteria = {"minimum_byte_reduction_fraction": 0.2,
                    "maximum_stale_fraction": 0.0,
                    "maximum_degraded_fraction": 0.75,
                    "maximum_unavailable_fraction": 0.0,
                    "maximum_data_age_cycles": 3,
                    "maximum_pr_auc_absolute_loss": 0.03,
                    "maximum_roc_auc_absolute_loss": 0.015,
                    "maximum_brier_increase": 0.01,
                    "maximum_recall_absolute_loss": 0.05,
                    "maximum_precision_absolute_loss": 0.05,
                    "maximum_median_lead_time_loss_cycles": 3.0,
                    "maximum_median_alert_latency_cycles": 3.0,
                    "maximum_p90_alert_latency_cycles": 5.0,
                    "maximum_false_alert_episodes_per_unit_increase": 0.25,
                    "maximum_missed_anticipated_failures": 0}
        metric = {"stale_fraction": 0.1, "degraded_fraction": 0.1, "unavailable_fraction": 0.1,
                  "maximum_data_age_cycles": 4, "pr_auc_average_precision": 0.9,
                  "roc_auc": 0.9, "brier_score": 0.1, "recall": 0.9, "precision": 0.9,
                  "median_lead_time": 10, "median_alert_latency_cycles": 1,
                  "p90_alert_latency_cycles": 2, "false_alert_episodes_per_unit": 0,
                  "missed_anticipated_failures": 0}
        reference = {**metric, "stale_fraction": 0, "degraded_fraction": 0,
                     "unavailable_fraction": 0, "maximum_data_age_cycles": 0,
                     "pr_auc_average_precision": 0.9, "roc_auc": 0.9, "brier_score": 0.1,
                     "recall": 0.9, "precision": 0.9, "median_lead_time": 10,
                     "false_alert_episodes_per_unit": 0}
        outcome = _acceptance(metric, reference,
            {"byte_reduction_fraction": 0.4}, criteria)
        self.assertFalse(outcome["passed"])
        self.assertFalse(outcome["checks"]["maximum_stale_fraction"])
        self.assertFalse(outcome["checks"]["maximum_unavailable_fraction"])

    def test_grid_is_reproducible_and_criteria_predeclared(self):
        config = _config(Path("configs/telemetry_reduction_experiment.toml"))
        ids = [item["id"] for item in config["policies"]]
        self.assertEqual(ids[0], "full")
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(config["experiment"]["horizons"], [15, 30])
        self.assertIn("minimum_byte_reduction_fraction", config["acceptance"])


if __name__ == "__main__":
    unittest.main()
