"""Verification of causal sequential telemetry filtering and receiver state."""

import math
import unittest

from predictive_maintenance.core.records import TelemetryRecord
from predictive_maintenance.filtering import (
    AdaptiveTelemetryConfig,
    AdaptiveTelemetryFilter,
    FixedIntervalFilter,
    FullTelemetryFilter,
    SensorSubsetFilter,
    TelemetryReceiver,
)


def record(cycle: int, a: float, b: float = 10.0, *, unit: str = "u1") -> TelemetryRecord:
    return TelemetryRecord(unit_id=unit, cycle=cycle, values={"sensor_a": a, "sensor_b": b})


class SequentialFilterTests(unittest.TestCase):
    def test_full_policy_transmits_every_value_every_cycle(self):
        policy = FullTelemetryFilter(metadata_overhead_bytes=16, value_bytes=8)
        output = policy.filter([record(1, 1.0), record(2, 2.0), record(3, 3.0)])
        self.assertTrue(all(item.packet is not None for item in output))
        self.assertTrue(all(item.packet.value_count == 2 for item in output))
        self.assertEqual(policy.metrics.observations_transmitted, 3)
        self.assertEqual(policy.metrics.values_transmitted, 6)
        self.assertEqual(policy.metrics.estimated_bytes, 96)
        self.assertEqual(policy.metrics.byte_reduction_fraction, 0.0)

    def test_processing_is_strictly_sequential_per_unit(self):
        policy = FullTelemetryFilter()
        policy.process(record(2, 2.0))
        policy.process(record(1, 1.0, unit="u2"))
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            policy.process(record(2, 3.0))

    def test_prefix_results_do_not_depend_on_future_suffix(self):
        config = AdaptiveTelemetryConfig(
            stable_interval_cycles=4,
            absolute_change_threshold=3.0,
            high_frequency_duration_cycles=2,
        )
        prefix = [record(i, value) for i, value in enumerate([0, 0, 4], start=1)]
        first = AdaptiveTelemetryFilter(config=config).filter(prefix)
        second = AdaptiveTelemetryFilter(config=config).filter(
            prefix + [record(4, 1000), record(5, -1000)]
        )[:len(prefix)]
        self.assertEqual(
            [(x.packet.send_reason if x.packet else None,
              x.receiver_state.sensors["sensor_a"].value) for x in first],
            [(x.packet.send_reason if x.packet else None,
              x.receiver_state.sensors["sensor_a"].value) for x in second],
        )

    def test_forbidden_rul_and_target_fields_are_rejected(self):
        policy = FullTelemetryFilter()
        for name in ("RUL", "failure_within_horizon", "target_failure", "label"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                policy.reset()
                policy.process(TelemetryRecord(unit_id="u", cycle=1, values={name: 1.0}))


class ReceiverAndFixedIntervalTests(unittest.TestCase):
    def test_fixed_interval_k_hold_last_value_age_and_staleness(self):
        receiver = TelemetryReceiver(stale_after_cycles=1, inference_cadence="each_cycle")
        policy = FixedIntervalFilter(interval_cycles=3, receiver=receiver)
        output = policy.filter([record(i, float(i)) for i in range(1, 8)])
        transmitted_cycles = [item.packet.cycle for item in output if item.packet]
        self.assertEqual(transmitted_cycles, [1, 4, 7])

        cycle2 = output[1].receiver_state.sensors["sensor_a"]
        self.assertEqual(cycle2.value, 1.0)
        self.assertEqual(cycle2.last_observed_cycle, 1)
        self.assertEqual(cycle2.sensor_age_cycles, 1)
        self.assertFalse(cycle2.was_transmitted_this_cycle)
        self.assertEqual(cycle2.value_validity, "valid_held")
        self.assertFalse(output[1].receiver_state.telemetry_stale)

        cycle3 = output[2].receiver_state.sensors["sensor_a"]
        self.assertEqual(cycle3.value, 1.0)
        self.assertEqual(cycle3.sensor_age_cycles, 2)
        self.assertEqual(cycle3.value_validity, "stale")
        self.assertTrue(output[2].receiver_state.telemetry_stale)
        self.assertFalse(cycle3.was_transmitted_this_cycle)

        cycle4 = output[3].receiver_state.sensors["sensor_a"]
        self.assertEqual(cycle4.value, 4.0)
        self.assertEqual(cycle4.sensor_age_cycles, 0)
        self.assertTrue(cycle4.was_transmitted_this_cycle)

    def test_on_transmission_inference_cadence(self):
        policy = FixedIntervalFilter(
            interval_cycles=3,
            receiver=TelemetryReceiver(inference_cadence="on_transmission"),
        )
        output = policy.filter([record(i, float(i)) for i in range(1, 5)])
        self.assertEqual([x.receiver_state.inference_due for x in output], [True, False, False, True])

    def test_byte_accounting_uses_configured_types_and_metadata(self):
        policy = FixedIntervalFilter(
            interval_cycles=3, metadata_overhead_bytes=16, value_bytes=8,
        )
        policy.filter([record(i, float(i)) for i in range(1, 8)])
        metrics = policy.metrics
        self.assertEqual(metrics.observations_generated, 7)
        self.assertEqual(metrics.observations_transmitted, 3)
        self.assertEqual(metrics.values_transmitted, 6)
        self.assertEqual(metrics.estimated_bytes, 96)
        self.assertEqual(metrics.full_telemetry_estimated_bytes, 224)
        self.assertAlmostEqual(metrics.byte_reduction_fraction, 1 - 96 / 224)
        self.assertAlmostEqual(metrics.effective_frequency, 3 / 7)
        self.assertGreaterEqual(metrics.policy_time_seconds, 0.0)


class SubsetAndAdaptiveTests(unittest.TestCase):
    def test_subset_transmits_only_train_selected_sensors(self):
        policy = SensorSubsetFilter(
            selected_sensors=("sensor_b",), selection_source="train",
            metadata_overhead_bytes=16, value_bytes=8,
        )
        output = policy.filter([record(1, 1.0), record(2, 2.0)])
        self.assertEqual(list(output[0].packet.transmitted_values), ["sensor_b"])
        self.assertEqual(set(output[0].receiver_state.sensors), {"sensor_b"})
        self.assertEqual(policy.metrics.values_transmitted, 2)
        self.assertEqual(policy.metrics.estimated_bytes, 48)
        with self.assertRaisesRegex(ValueError, "selection_source='train'"):
            SensorSubsetFilter(selected_sensors=("sensor_b",), selection_source="validation")

    def test_adaptive_activation_high_mode_duration_and_reproducibility(self):
        config = AdaptiveTelemetryConfig(
            stable_interval_cycles=4,
            high_frequency_interval_cycles=1,
            high_frequency_duration_cycles=3,
            monitored_sensors=("sensor_a",),
            absolute_change_threshold=5.0,
            moving_window=3,
        )
        trajectory = [record(i, value) for i, value in enumerate([0, 0, 0, 10, 10, 10, 10], start=1)]
        first_policy = AdaptiveTelemetryFilter(config=config)
        second_policy = AdaptiveTelemetryFilter(config=config)
        first = first_policy.filter(trajectory)
        second = second_policy.filter(trajectory)
        signature = lambda rows: [
            (row.packet.cycle, row.packet.send_reason) if row.packet else None for row in rows
        ]
        self.assertEqual(signature(first), signature(second))
        self.assertEqual([x.packet.cycle for x in first if x.packet], [1, 4, 5, 6])
        self.assertEqual(first_policy.metrics.adaptive_activations, 1)
        self.assertEqual(first_policy.metrics.high_frequency_cycles, 3)
        self.assertEqual(first_policy.metrics.high_frequency_durations, (3,))
        self.assertEqual(
            first_policy.metrics.adaptive_activation_reasons,
            {"absolute_change:sensor_a": 1},
        )

    def test_adaptive_can_use_separate_anomaly_indicator(self):
        policy = AdaptiveTelemetryFilter(config=AdaptiveTelemetryConfig(
            stable_interval_cycles=10,
            anomaly_score_threshold=0.9,
            high_frequency_duration_cycles=2,
        ))
        first = policy.process(record(1, 0.0), anomaly_score=0.1)
        second = policy.process(record(2, 0.0), anomaly_score=0.95)
        self.assertIsNotNone(first.packet)
        self.assertIn("anomaly_score", second.packet.send_reason)
        self.assertEqual(policy.metrics.adaptive_activations, 1)

    def test_adaptive_rejects_nonfinite_anomaly_when_criterion_enabled(self):
        policy = AdaptiveTelemetryFilter(config=AdaptiveTelemetryConfig(
            anomaly_score_threshold=0.9,
        ))
        with self.assertRaises(ValueError):
            policy.process(record(1, 0.0), anomaly_score=math.nan)


if __name__ == "__main__":
    unittest.main()
