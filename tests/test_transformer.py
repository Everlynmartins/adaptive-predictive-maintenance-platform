from pathlib import Path
import tempfile
import unittest

import numpy as np
import torch

from predictive_maintenance.core.records import FeatureRecord, TargetRecord
from predictive_maintenance.models.temporal.transformer import (
    SinusoidalPositionalEncoding,
    SmallCausalTransformer,
    TemporalSequenceDataset,
    TransformerConfig,
    TransformerRiskModel,
)


class TransformerTests(unittest.TestCase):
    def _config(self):
        return TransformerConfig(
            horizons=(3, 5), sequence_length=6, d_model=8, num_heads=2,
            num_layers=1, feedforward_dim=16, dropout=0.0, batch_size=16,
            max_epochs=2, patience=1, random_seed=11, torch_threads=1,
        )

    def _records(self):
        features, targets = [], []
        for unit in range(1, 5):
            for cycle in range(1, 13):
                features.append(FeatureRecord(
                    str(unit), cycle,
                    {"sensor_a": float(cycle + unit), "sensor_b": float(cycle * unit)},
                ))
                remaining = 13 - cycle
                targets.append(TargetRecord(
                    str(unit), cycle,
                    {"failure_within_h3": int(remaining <= 3),
                     "failure_within_h5": int(remaining <= 5)},
                ))
        return features, targets

    def test_temporal_dataset_alignment(self):
        sequences = np.zeros((3, 6, 2), dtype=np.float32)
        masks = np.ones((3, 6), dtype=np.float32)
        dataset = TemporalSequenceDataset(sequences, masks, np.zeros((3, 2)))
        self.assertEqual(len(dataset), 3)
        self.assertEqual(dataset[0][0].shape, (6, 2))
        with self.assertRaises(ValueError):
            TemporalSequenceDataset(sequences, masks[:2])

    def test_positional_encoding_is_deterministic_and_position_dependent(self):
        positional = SinusoidalPositionalEncoding(8, 6)
        values = torch.zeros((1, 6, 8))
        first = positional(values)
        second = positional(values)
        self.assertTrue(torch.equal(first, second))
        self.assertFalse(torch.equal(first[:, 0], first[:, 1]))

    def test_causal_mask_blocks_future_observations(self):
        torch.manual_seed(3)
        network = SmallCausalTransformer(2, self._config()).eval()
        prefix = torch.randn((1, 3, 2))
        suffix_a = torch.randn((1, 3, 2))
        suffix_b = torch.randn((1, 3, 2)) * 100.0
        mask = torch.ones((1, 6))
        encoded_a = network.encode(torch.cat((prefix, suffix_a), dim=1), mask)
        encoded_b = network.encode(torch.cat((prefix, suffix_b), dim=1), mask)
        self.assertTrue(torch.allclose(encoded_a[:, :3], encoded_b[:, :3], atol=1e-6))
        expected = torch.triu(torch.ones((6, 6), dtype=torch.bool), diagonal=1)
        self.assertTrue(torch.equal(network.causal_attention_mask(6), expected))

    def test_padding_mask_and_sequence_length_are_enforced(self):
        network = SmallCausalTransformer(2, self._config()).eval()
        sequence = torch.randn((1, 6, 2))
        valid = torch.tensor([[0.0, 0.0, 1.0, 1.0, 1.0, 1.0]])
        changed_padding = sequence.clone()
        changed_padding[:, :2] = 1.0e6
        self.assertTrue(torch.allclose(network(sequence, valid), network(changed_padding, valid)))
        with self.assertRaises(ValueError):
            network(sequence[:, :5], valid[:, :5])
        with self.assertRaises(ValueError):
            network(sequence, torch.tensor([[0.0, 1.0, 0.0, 1.0, 1.0, 1.0]]))
        with self.assertRaises(ValueError):
            network(sequence, torch.tensor([[0.0, 0.0, 1.0, 1.0, 1.0, 0.0]]))

    def test_joint_head_is_bounded_and_monotone_without_repair(self):
        network = SmallCausalTransformer(2, self._config()).eval()
        for parameter in network.parameters():
            torch.nn.init.zeros_(parameter)
        probability = network(torch.zeros((2, 6, 2)), torch.ones((2, 6)))
        np.testing.assert_allclose(probability.detach().numpy()[:, 0], 0.5, atol=1e-7)
        np.testing.assert_allclose(probability.detach().numpy()[:, 1], 0.75, atol=1e-7)

    def test_sequence_builder_is_unit_scoped_causal_and_origin_aligned(self):
        records = [
            FeatureRecord("1", 1, {"sensor_a": 1.0, "sensor_b": 10.0}),
            FeatureRecord("2", 1, {"sensor_a": 101.0, "sensor_b": 110.0}),
            FeatureRecord("1", 2, {"sensor_a": 2.0, "sensor_b": 20.0}),
            FeatureRecord("2", 2, {"sensor_a": 102.0, "sensor_b": 120.0}),
            FeatureRecord("1", 3, {"sensor_a": 3.0, "sensor_b": 30.0}),
        ]
        model = TransformerRiskModel(self._config(), ("sensor_a", "sensor_b"))
        model.mean = np.zeros(2)
        model.scale = np.ones(2)
        sequences, masks, keys = model._sequence_arrays(records, allow_invalid=False)
        by_key = {key: (sequences[index], masks[index]) for index, key in enumerate(keys)}
        sequence, mask = by_key[("1", 3)]
        np.testing.assert_allclose(sequence[mask.astype(bool), 0], [1.0, 2.0, 3.0])
        self.assertEqual(sequence[-1, 0], 3.0)
        self.assertFalse(np.isin(sequence[mask.astype(bool), 0], [101.0, 102.0]).any())
        extended = records + [FeatureRecord("1", 4, {"sensor_a": 9999.0, "sensor_b": 9999.0})]
        future, _, future_keys = model._sequence_arrays(extended, allow_invalid=False)
        np.testing.assert_allclose(sequence, future[future_keys.index(("1", 3))])

    def test_training_reproducibility_save_load_invalid_input_and_memory(self):
        features, targets = self._records()
        first = TransformerRiskModel(self._config(), ("sensor_a", "sensor_b")).fit(features, targets)
        second = TransformerRiskModel(self._config(), ("sensor_a", "sensor_b")).fit(features, targets)
        score_a = first.predict_probabilities(features)
        score_b = second.predict_probabilities(features)
        np.testing.assert_allclose(score_a, score_b, rtol=0, atol=0)
        self.assertTrue(np.all((score_a >= 0) & (score_a <= 1)))
        self.assertTrue(np.all(score_a[:, 1] >= score_a[:, 0]))
        self.assertGreater(first.parameter_memory_bytes(), 0)
        self.assertGreater(first.approximate_inference_working_memory_bytes(), 0)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "transformer.pt"
            first.save(path)
            restored = TransformerRiskModel.load(path)
            np.testing.assert_allclose(score_a, restored.predict_probabilities(features), atol=1e-8)
            incompatible = Path(directory) / "bad.pt"
            torch.save({"schema": "other/v1"}, incompatible)
            with self.assertRaisesRegex(ValueError, "incompatible Transformer artifact"):
                TransformerRiskModel.load(incompatible)
        invalid = list(features)
        invalid[0] = FeatureRecord("1", 1, {"sensor_a": float("nan"), "sensor_b": 1.0})
        self.assertEqual(first.predict_risk(invalid, horizon=3)[0].prediction_status, "unavailable")

    def test_forbidden_features_and_early_stopping_overlap_are_rejected(self):
        for name in ("RUL", "normalized_life", "final_cycle", "max_cycle",
                     "failure_within_horizon", "target_h15", "label", "sensor_at_future"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                TransformerRiskModel(self._config(), ("sensor_a", name))
        features, targets = self._records()
        with self.assertRaises(ValueError):
            TransformerRiskModel(self._config(), ("sensor_a", "sensor_b")).fit_with_validation(
                features[:24], targets[:24], features[12:36], targets[12:36],
            )


if __name__ == "__main__":
    unittest.main()
