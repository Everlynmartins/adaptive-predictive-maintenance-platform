from pathlib import Path
import tempfile
import unittest

import numpy as np
import torch

from predictive_maintenance.core.records import FeatureRecord, TargetRecord
from predictive_maintenance.models.temporal.tcn import (
    CausalConv1d,
    SmallTCN,
    TCNConfig,
    TCNRiskModel,
)


class TCNTests(unittest.TestCase):
    def _records(self):
        features = []
        targets = []
        for unit in range(1, 5):
            for cycle in range(1, 13):
                features.append(FeatureRecord(
                    unit_id=str(unit), cycle=cycle,
                    values={"sensor_a": float(cycle + unit), "sensor_b": float(cycle * unit)},
                ))
                remaining = 13 - cycle
                targets.append(TargetRecord(
                    unit_id=str(unit), cycle=cycle,
                    values={
                        "failure_within_h3": int(remaining <= 3),
                        "failure_within_h5": int(remaining <= 5),
                    },
                ))
        return features, targets

    def _config(self):
        return TCNConfig(
            horizons=(3, 5), sequence_length=5, channels=(4,), kernel_size=2,
            dropout=0.0, batch_size=16, max_epochs=2, patience=1,
            random_seed=7, torch_threads=1,
        )

    def test_causal_convolution_prefix_invariance(self):
        torch.manual_seed(1)
        layer = CausalConv1d(2, 3, kernel_size=3, dilation=2)
        prefix = torch.randn(1, 2, 8)
        suffix_a = torch.randn(1, 2, 4)
        suffix_b = torch.randn(1, 2, 4)
        out_a = layer(torch.cat((prefix, suffix_a), dim=-1))
        out_b = layer(torch.cat((prefix, suffix_b), dim=-1))
        self.assertTrue(torch.allclose(out_a[:, :, :8], out_b[:, :, :8]))

    def test_joint_head_implements_nested_probabilities_without_repair(self):
        network = SmallTCN(input_features=2, channels=(3,), kernel_size=2, dropout=0.0)
        for parameter in network.parameters():
            torch.nn.init.zeros_(parameter)
        sequence = torch.ones((2, 4, 2), dtype=torch.float32)
        mask = torch.ones((2, 4), dtype=torch.float32)
        probability = network(sequence, mask)
        np.testing.assert_allclose(probability.detach().numpy()[:, 0], 0.5, atol=1e-7)
        np.testing.assert_allclose(probability.detach().numpy()[:, 1], 0.75, atol=1e-7)
        self.assertTrue(torch.all(probability[:, 1] >= probability[:, 0]))

    def test_mask_rejects_nonbinary_or_right_padding_and_masks_left_values(self):
        torch.manual_seed(2)
        network = SmallTCN(input_features=2, channels=(3,), kernel_size=2, dropout=0.0).eval()
        left = torch.randn((1, 5, 2))
        changed = left.clone()
        changed[:, :3] = 10000.0
        mask = torch.tensor([[0.0, 0.0, 0.0, 1.0, 1.0]])
        self.assertTrue(torch.allclose(network(left, mask), network(changed, mask)))
        with self.assertRaises(ValueError):
            network(left, torch.tensor([[0.0, 1.0, 0.0, 1.0, 1.0]]))
        with self.assertRaises(ValueError):
            network(left, torch.tensor([[0.0, 0.5, 1.0, 1.0, 1.0]]))

    def test_short_sequences_are_left_padded_and_masked(self):
        features, _ = self._records()
        model = TCNRiskModel(self._config(), ("sensor_a", "sensor_b"))
        matrix = model._matrix(features, strict=True)
        model._fit_normalizer(matrix)
        sequences, masks, keys = model._sequence_arrays(features, allow_invalid=False)
        first = keys.index(("1", 1))
        self.assertEqual(masks[first].tolist(), [0.0, 0.0, 0.0, 0.0, 1.0])
        self.assertTrue(np.allclose(sequences[first, :4], 0.0))

    def test_sequence_builder_is_unit_scoped_causal_and_origin_aligned(self):
        records = [
            FeatureRecord("1", 1, {"sensor_a": 1.0, "sensor_b": 10.0}),
            FeatureRecord("2", 1, {"sensor_a": 101.0, "sensor_b": 110.0}),
            FeatureRecord("1", 2, {"sensor_a": 2.0, "sensor_b": 20.0}),
            FeatureRecord("2", 2, {"sensor_a": 102.0, "sensor_b": 120.0}),
            FeatureRecord("1", 3, {"sensor_a": 3.0, "sensor_b": 30.0}),
        ]
        model = TCNRiskModel(self._config(), ("sensor_a", "sensor_b"))
        model.mean = np.zeros(2)
        model.scale = np.ones(2)
        sequences, masks, keys = model._sequence_arrays(records, allow_invalid=False)
        by_key = {key: (sequences[index], masks[index]) for index, key in enumerate(keys)}
        sequence, mask = by_key[("1", 3)]
        np.testing.assert_allclose(sequence[mask.astype(bool), 0], [1.0, 2.0, 3.0])
        self.assertEqual(sequence[-1, 0], 3.0)
        self.assertFalse(np.isin(sequence[mask.astype(bool), 0], [101.0, 102.0]).any())

        extended = records + [FeatureRecord("1", 4, {"sensor_a": 9999.0, "sensor_b": 9999.0})]
        future_sequences, _, future_keys = model._sequence_arrays(extended, allow_invalid=False)
        future_by_key = {key: future_sequences[index] for index, key in enumerate(future_keys)}
        np.testing.assert_allclose(by_key[("1", 3)][0], future_by_key[("1", 3)])

    def test_training_bounds_coherence_save_load_and_invalid_input(self):
        features, targets = self._records()
        model = TCNRiskModel(self._config(), ("sensor_a", "sensor_b")).fit(features, targets)
        short = model.predict_risk(features, horizon=3)
        long = model.predict_risk(features, horizon=5)
        for a, b in zip(short, long, strict=True):
            self.assertEqual(a.prediction_status, "available")
            self.assertGreaterEqual(a.risk_score, 0.0)
            self.assertLessEqual(a.risk_score, 1.0)
            self.assertGreaterEqual(b.risk_score + 1e-12, a.risk_score)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tcn.pt"
            model.save(path)
            restored = TCNRiskModel.load(path)
            original = [item.risk_score for item in model.predict_risk(features, horizon=5)]
            loaded = [item.risk_score for item in restored.predict_risk(features, horizon=5)]
            np.testing.assert_allclose(original, loaded, rtol=0, atol=1e-8)
            incompatible = Path(directory) / "incompatible.pt"
            torch.save({"schema": "another-model/v1"}, incompatible)
            with self.assertRaisesRegex(ValueError, "incompatible TCN artifact"):
                TCNRiskModel.load(incompatible)
        invalid = list(features)
        invalid[4] = FeatureRecord("1", 5, {"sensor_a": 5.0, "sensor_b": float("nan")})
        predictions = model.predict_risk(invalid, horizon=3)
        self.assertEqual(predictions[4].prediction_status, "unavailable")
        self.assertEqual(predictions[4].input_validity, "invalid")
        # The invalid history remains inside the next sequence window.
        self.assertEqual(predictions[5].prediction_status, "unavailable")

    def test_training_is_reproducible_with_fixed_seed(self):
        features, targets = self._records()
        first = TCNRiskModel(self._config(), ("sensor_a", "sensor_b")).fit(features, targets)
        second = TCNRiskModel(self._config(), ("sensor_a", "sensor_b")).fit(features, targets)
        first_scores = [item.risk_score for item in first.predict_risk(features, horizon=5)]
        second_scores = [item.risk_score for item in second.predict_risk(features, horizon=5)]
        np.testing.assert_allclose(first_scores, second_scores, rtol=0, atol=0)

    def test_forbidden_feature_names_are_rejected(self):
        forbidden = (
            "RUL", "normalized_life", "final_cycle", "max_cycle",
            "failure_within_horizon", "failure_within_critical_horizon",
            "target_h15", "label", "event_cycle", "observed_end",
            "sensor_at_future",
        )
        for name in forbidden:
            with self.subTest(name=name), self.assertRaises(ValueError):
                TCNRiskModel(self._config(), ("sensor_a", name))

    def test_early_stopping_fit_rejects_unit_overlap(self):
        features, targets = self._records()
        with self.assertRaises(ValueError):
            TCNRiskModel(self._config(), ("sensor_a", "sensor_b")).fit_with_validation(
                features[:24], targets[:24], features[12:36], targets[12:36],
            )


if __name__ == "__main__":
    unittest.main()
