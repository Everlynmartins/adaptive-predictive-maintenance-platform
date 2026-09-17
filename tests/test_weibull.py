"""Verification of the two-parameter population Weibull baseline."""

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from predictive_maintenance.core.records import FeatureRecord, TargetRecord
from predictive_maintenance.analysis.weibull import parameter_bootstrap
from predictive_maintenance.evaluation.probability import evaluate_binary_probabilities
from predictive_maintenance.models.reliability.weibull import (
    Weibull2Parameter,
    WeibullFitConfig,
    maximum_likelihood_estimate,
    weibull_log_likelihood,
)


class WeibullFunctionTests(unittest.TestCase):
    def setUp(self):
        self.model = Weibull2Parameter(WeibullFitConfig("fixture_weibull", "test-1"))
        self.model.fit_lifetimes([90, 105, 120, 140, 180, 220],
                                 unit_ids=[str(i) for i in range(6)])

    def test_distribution_survival_and_hazards_respect_bounds(self):
        self.assertAlmostEqual(self.model.survival(0), 1.0, places=14)
        times = np.linspace(0, 500, 101)
        survival = self.model.survival(times)
        cdf = self.model.cumulative_distribution(times)
        density = self.model.density(times)
        hazard = self.model.hazard(times)
        cumulative = self.model.cumulative_hazard(times)
        self.assertTrue(np.all((survival >= 0) & (survival <= 1)))
        self.assertTrue(np.all((cdf >= 0) & (cdf <= 1)))
        self.assertTrue(np.all(density >= 0))
        self.assertTrue(np.all(hazard >= 0))
        self.assertTrue(np.all(cumulative >= 0))
        np.testing.assert_allclose(cdf + survival, 1.0, atol=1e-14)
        positive = np.array([10., 100., 250.])
        np.testing.assert_allclose(self.model.density(positive) / self.model.survival(positive),
                                   self.model.hazard(positive), rtol=1e-12)

    def test_conditional_risk_bounds_zero_horizon_and_monotonic_horizon(self):
        for age in (0, 50, 150, 500):
            risks = [self.model.conditional_risk(age, horizon) for horizon in (0, 5, 15, 30, 60)]
            self.assertEqual(risks[0], 0.0)
            self.assertTrue(all(0 <= value <= 1 for value in risks))
            self.assertTrue(all(left <= right for left, right in zip(risks, risks[1:])))
            if age > 0:
                direct = 1 - self.model.survival(age + 30) / self.model.survival(age)
                self.assertAlmostEqual(risks[3], direct, places=14)

    def test_predict_risk_obeys_common_contract_for_configurable_horizons(self):
        features = [FeatureRecord("unit-a", 50, {}), FeatureRecord("unit-b", 150, {})]
        for horizon in (15, 30, 45):
            output = self.model.predict_risk(features, horizon=horizon)
            self.assertEqual([record.horizon for record in output], [horizon, horizon])
            self.assertTrue(all(record.prediction_status == "available" for record in output))
            self.assertTrue(all(record.input_validity == "valid" for record in output))
            self.assertTrue(all(0 <= record.risk_score <= 1 for record in output))
        short = self.model.predict_risk(features, horizon=15)
        long = self.model.predict_risk(features, horizon=30)
        self.assertTrue(all(a.risk_score <= b.risk_score for a, b in zip(short, long)))

    def test_save_load_preserve_configuration_and_predictions(self):
        features = [FeatureRecord("unit-a", 100, {})]
        expected = self.model.predict_risk(features, horizon=30)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            self.model.save(path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            restored = Weibull2Parameter.load(path)
            self.assertEqual(restored.predict_risk(features, horizon=30), expected)
            self.assertEqual(restored.config, self.model.config)
            self.assertEqual(restored.training_data_manifest, self.model.training_data_manifest)
            self.assertEqual(set(payload["parameters"]), {"beta", "eta"})
            self.assertEqual(payload["fit"]["location"], 0.0)

    def test_model_rejects_inputs_outside_age_only_contract(self):
        for feature in (
            FeatureRecord("unit-a", 10, {"sensor_1": 1.0}),
            FeatureRecord("unit-a", 10, {"age": 10.0}),
            FeatureRecord("unit-a", 0, {}),
            FeatureRecord("", 10, {}),
        ):
            with self.subTest(feature=feature), self.assertRaises(ValueError):
                self.model.predict_risk([feature], horizon=30)
        for horizon in (0, -1, 30.0, True):
            with self.subTest(horizon=horizon), self.assertRaises(ValueError):
                self.model.predict_risk([FeatureRecord("unit-a", 10, {})], horizon=horizon)
        with self.assertRaises(RuntimeError):
            Weibull2Parameter().predict_risk([], horizon=30)

    def test_common_fit_uses_one_lifetime_target_per_unit_and_no_features(self):
        features = [FeatureRecord("a", 1, {}), FeatureRecord("b", 1, {})]
        targets = [TargetRecord("a", 1, {"event_time": 100, "event_observed": 1}),
                   TargetRecord("b", 1, {"event_time": 150, "event_observed": 1})]
        model = Weibull2Parameter().fit(features, targets)
        self.assertEqual((model.n_observations, model.n_events), (2, 2))
        with self.assertRaises(ValueError):
            Weibull2Parameter().fit([FeatureRecord("a", 1, {"sensor_2": 1.})], targets[:1])


class WeibullEstimationAndMetricTests(unittest.TestCase):
    def test_mle_has_positive_parameters_and_supports_future_censor_indicators(self):
        durations, events = [10, 15, 20, 25], [1, 1, 0, 1]
        beta, eta = maximum_likelihood_estimate(durations, events)
        self.assertGreater(beta, 0)
        self.assertGreater(eta, 0)
        optimum = weibull_log_likelihood(durations, events, beta, eta)
        for candidate in ((beta * .9, eta), (beta * 1.1, eta),
                          (beta, eta * .9), (beta, eta * 1.1)):
            self.assertGreater(optimum, weibull_log_likelihood(durations, events, *candidate))
        with self.assertRaises(ValueError):
            maximum_likelihood_estimate([10, 15], [0, 0])

    def test_probability_metrics_known_perfect_ranking(self):
        metrics = evaluate_binary_probabilities([0, 0, 1, 1], [.1, .2, .8, .9],
                                                reliability_bins=5)
        self.assertAlmostEqual(metrics["roc_auc"], 1.0)
        self.assertAlmostEqual(metrics["pr_auc_average_precision"], 1.0)
        self.assertAlmostEqual(metrics["brier_score"], .025)
        self.assertEqual(sum(row["count"] for row in metrics["reliability_curve"]), 4)

    def test_parameter_bootstrap_resamples_unit_lifetimes_reproducibly(self):
        lifetimes = [100, 120, 150, 190, 240, 300]
        first = parameter_bootstrap(lifetimes, samples=25, seed=7, confidence_level=0.90)
        second = parameter_bootstrap(lifetimes, samples=25, seed=7, confidence_level=0.90)
        self.assertEqual(first, second)
        self.assertEqual(first["method"], "nonparametric percentile bootstrap by unit")
        self.assertEqual(first["successful_fits"], 25)
        self.assertGreater(first["beta"]["upper"], first["beta"]["lower"])
        self.assertGreater(first["eta"]["upper"], first["eta"]["lower"])


if __name__ == "__main__":
    unittest.main()
