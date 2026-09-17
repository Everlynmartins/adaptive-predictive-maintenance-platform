"""Bootstrap, goodness-of-fit and sensitivity for the Weibull baseline."""

from __future__ import annotations

from math import log
from typing import Sequence

import numpy as np

from predictive_maintenance.models.reliability.weibull import (
    Weibull2Parameter,
    maximum_likelihood_estimate,
)


def parameter_bootstrap(
    lifetimes: Sequence[float],
    *,
    samples: int,
    seed: int,
    confidence_level: float,
) -> dict[str, object]:
    """Nonparametric percentile intervals, resampling whole unit lifetimes."""
    times = np.asarray(lifetimes, dtype=float)
    _validate_bootstrap(samples, confidence_level)
    generator = np.random.default_rng(seed)
    estimates = np.empty((samples, 2), dtype=float)
    completed = attempts = 0
    while completed < samples and attempts < samples * 20:
        attempts += 1
        resampled = generator.choice(times, size=len(times), replace=True)
        try:
            estimates[completed] = maximum_likelihood_estimate(resampled)
        except RuntimeError:
            continue
        completed += 1
    if completed < samples:
        raise RuntimeError("insufficient non-degenerate unit bootstrap samples")
    alpha = 1.0 - confidence_level
    lower, upper = np.quantile(estimates, [alpha / 2.0, 1.0 - alpha / 2.0], axis=0)
    return {
        "method": "nonparametric percentile bootstrap by unit",
        "confidence_level": confidence_level,
        "samples": samples,
        "seed": seed,
        "beta": {"lower": float(lower[0]), "upper": float(upper[0])},
        "eta": {"lower": float(lower[1]), "upper": float(upper[1])},
        "successful_fits": samples,
        "attempts": attempts,
    }


def goodness_of_fit(
    lifetimes: Sequence[float],
    model: Weibull2Parameter,
    *,
    samples: int,
    seed: int,
    significance_level: float,
) -> dict[str, object]:
    """Cramér-von Mises with parametric bootstrap and MLE refit per sample."""
    if type(samples) is not int or samples <= 0:
        raise ValueError("samples must be a positive integer")
    if not 0 < significance_level < 1:
        raise ValueError("significance_level must be in (0, 1)")
    times = np.asarray(lifetimes, dtype=float)
    observed = cramer_von_mises(times, model)
    generator = np.random.default_rng(seed)
    replicated = np.empty(samples, dtype=float)
    beta, eta = model._parameters()
    for index in range(samples):
        uniforms = generator.random(len(times))
        simulated = eta * np.power(-np.log1p(-uniforms), 1.0 / beta)
        # FD001 event ages are recorded at integer-cycle resolution. Reproduce
        # that observation rule while retaining the continuous Weibull likelihood.
        simulated = np.maximum(1.0, np.rint(simulated))
        fitted = Weibull2Parameter().fit_lifetimes(simulated)
        replicated[index] = cramer_von_mises(simulated, fitted)
    exceedances = int(np.count_nonzero(replicated >= observed))
    p_value = (1.0 + exceedances) / (samples + 1.0)
    critical = float(np.quantile(replicated, 1.0 - significance_level))
    sorted_times = np.sort(times)
    fitted_cdf = np.asarray(model.cumulative_distribution(sorted_times))
    empirical_right = np.arange(1, len(times) + 1) / len(times)
    empirical_left = np.arange(0, len(times)) / len(times)
    ks_distance = float(max(np.max(empirical_right - fitted_cdf),
                            np.max(fitted_cdf - empirical_left)))
    log_likelihood = float(model.log_likelihood)
    return {
        "test": "Cramer-von Mises parametric-bootstrap with parameter refit",
        "statistic": observed,
        "p_value": p_value,
        "bootstrap_exceedances": exceedances,
        "critical_value": critical,
        "critical_value_method": "linear empirical quantile at 1 - significance_level",
        "significance_level": significance_level,
        "bootstrap_samples": samples,
        "seed": seed,
        "observation_resolution": "continuous draws rounded to nearest positive integer cycle",
        "decision": "reject" if observed > critical else "do_not_reject",
        "monte_carlo_standard_error_at_p": float(np.sqrt(p_value * (1 - p_value) / (samples + 1))),
        "ks_distance_descriptive": ks_distance,
        "log_likelihood": log_likelihood,
        "aic": -2.0 * log_likelihood + 4.0,
        "bic": -2.0 * log_likelihood + 2.0 * log(len(times)),
        "systematic_deviation": systematic_survival_deviation(times, model),
    }


def cramer_von_mises(lifetimes: Sequence[float], model: Weibull2Parameter) -> float:
    times = np.sort(np.asarray(lifetimes, dtype=float))
    fitted = np.asarray(model.cumulative_distribution(times))
    plotting = (2 * np.arange(1, len(times) + 1) - 1) / (2 * len(times))
    return float(1.0 / (12 * len(times)) + np.square(fitted - plotting).sum())


def systematic_survival_deviation(
    lifetimes: Sequence[float], model: Weibull2Parameter,
) -> list[dict[str, float | int | str]]:
    times = np.sort(np.asarray(lifetimes, dtype=float))
    n = len(times)
    empirical = (n - np.arange(1, n + 1)) / n
    fitted = np.asarray(model.survival(times))
    residual = empirical - fitted
    groups = np.array_split(np.arange(n), 4)
    labels = ("shortest_lifetimes", "lower_middle", "upper_middle", "longest_lifetimes")
    return [{
        "region": label,
        "n_units": int(len(indices)),
        "minimum_lifetime": float(times[indices[0]]),
        "maximum_lifetime": float(times[indices[-1]]),
        "mean_empirical_minus_fitted_survival": float(residual[indices].mean()),
        "max_absolute_deviation": float(np.abs(residual[indices]).max()),
    } for label, indices in zip(labels, groups, strict=True)]


def sensitivity_analysis(
    model: Weibull2Parameter,
    intervals: dict[str, object],
    *,
    ages: Sequence[int],
    horizons: Sequence[int],
) -> list[dict[str, float | int]]:
    beta, eta = model._parameters()
    beta_interval = intervals["beta"]
    eta_interval = intervals["eta"]
    rows = []
    for age in ages:
        for horizon in horizons:
            def risk(shape: float, scale: float) -> float:
                delta = ((age + horizon) / scale) ** shape - (age / scale) ** shape
                return float(min(1.0, max(0.0, -np.expm1(-delta))))

            row: dict[str, float | int] = {"age": age, "horizon": horizon,
                                           "risk_mle": model.conditional_risk(age, horizon)}
            for label, altered_beta, altered_eta in (
                ("beta_lower", beta_interval["lower"], eta),
                ("beta_upper", beta_interval["upper"], eta),
                ("eta_lower", beta, eta_interval["lower"]),
                ("eta_upper", beta, eta_interval["upper"]),
            ):
                row[f"risk_{label}"] = risk(float(altered_beta), float(altered_eta))
            corners = [risk(float(shape), float(scale))
                       for shape in (beta_interval["lower"], beta_interval["upper"])
                       for scale in (eta_interval["lower"], eta_interval["upper"])]
            row["risk_parameter_rectangle_min"] = min(corners)
            row["risk_parameter_rectangle_max"] = max(corners)
            rows.append(row)
    return rows


def probability_plot_data(
    lifetimes: Sequence[float], model: Weibull2Parameter,
) -> dict[str, np.ndarray | float]:
    times = np.sort(np.asarray(lifetimes, dtype=float))
    ranks = np.arange(1, len(times) + 1)
    median_rank = (ranks - 0.3) / (len(times) + 0.4)
    x = np.log(times)
    y = np.log(-np.log1p(-median_rank))
    beta, eta = model._parameters()
    fitted = beta * x - beta * np.log(eta)
    residual = y - fitted
    r_squared = 1.0 - float(np.square(residual).sum() / np.square(y - y.mean()).sum())
    return {"log_lifetime": x, "weibull_quantile": y,
            "fitted_quantile": fitted, "r_squared_descriptive": r_squared}


def _validate_bootstrap(samples: int, confidence_level: float) -> None:
    if type(samples) is not int or samples <= 0:
        raise ValueError("samples must be a positive integer")
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level must be in (0, 1)")
