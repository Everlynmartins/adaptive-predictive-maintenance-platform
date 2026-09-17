import tempfile
from pathlib import Path
import unittest

import numpy as np

from predictive_maintenance.core.records import AnomalyPrediction, FeatureRecord
from predictive_maintenance.models.anomaly.isolation_forest import (
    IsolationForestAnomalyDetector, IsolationForestConfig,
)


def records():
    result = []
    for unit, offset in (("1", 0.0), ("2", .2), ("3", -.1)):
        for cycle in range(1, 10):
            result.append(FeatureRecord(unit, cycle, {
                "age_cycle": float(cycle), "sensor_2__current": offset + cycle / 10,
            }))
    return result


class IsolationForestAnomalyTests(unittest.TestCase):
    def test_orientation_finiteness_and_reproducibility(self):
        source = records()
        config = IsolationForestConfig(n_estimators=40, max_samples=16, random_seed=9)
        first = IsolationForestAnomalyDetector(("age_cycle", "sensor_2__current"), config).fit(source)
        second = IsolationForestAnomalyDetector(("age_cycle", "sensor_2__current"), config).fit(source)
        scores_a = first.detect(source)
        scores_b = second.detect(source)
        np.testing.assert_allclose([x.anomaly_score for x in scores_a], [x.anomaly_score for x in scores_b])
        self.assertTrue(all(x.prediction_status == "available" and x.input_validity == "valid" for x in scores_a))
        self.assertTrue(all(np.isfinite(x.anomaly_score) and 0 <= x.anomaly_score <= 1 for x in scores_a))
        ordinary = FeatureRecord("4", 5, {"age_cycle": 5., "sensor_2__current": .5})
        unusual = FeatureRecord("4", 5, {"age_cycle": 100., "sensor_2__current": 100.})
        self.assertGreater(first.detect([unusual])[0].anomaly_score, first.detect([ordinary])[0].anomaly_score)

    def test_save_load_and_invalid_input_status(self):
        source = records()
        detector = IsolationForestAnomalyDetector(("age_cycle", "sensor_2__current"),
                                                   IsolationForestConfig(n_estimators=25, max_samples=16)).fit(source)
        bad = FeatureRecord("x", 1, {"age_cycle": 1.})
        output = detector.detect([bad])[0]
        self.assertEqual((output.prediction_status, output.input_validity), ("unavailable", "invalid"))
        self.assertIsNone(output.anomaly_score)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "detector.joblib"
            detector.save(path)
            loaded = IsolationForestAnomalyDetector.load(path)
            self.assertEqual(loaded.config, detector.config)
            self.assertEqual(loaded.detect(source), detector.detect(source))

    def test_prohibited_feature_names_and_anomaly_record_states(self):
        for name in ("RUL", "failure_within_horizon", "normalized_life", "future_sensor"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                IsolationForestAnomalyDetector(("age_cycle", name))
        unavailable = AnomalyPrediction("u", 1, None, "monitor", "test", "unavailable", "invalid", "bad schema")
        self.assertIsNone(unavailable.anomaly_score)
        with self.assertRaises(ValueError):
            AnomalyPrediction("u", 1, .2, "monitor", "test", "unavailable", "invalid", "bad schema")
