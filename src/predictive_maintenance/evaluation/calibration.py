"""Calibration diagnostics for already-fitted probabilistic predictors."""

from __future__ import annotations

from typing import Sequence

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit

from predictive_maintenance.evaluation.probability import (
    evaluate_binary_probabilities,
    reliability_curve,
)


def expected_calibration_error(
    labels: Sequence[int | bool], probabilities: Sequence[float], *, bins: int = 10,
) -> float:
    """Return count-weighted absolute calibration error in equal-width bins."""
    curve = reliability_curve(labels, probabilities, bins)
    total = sum(int(item["count"]) for item in curve)
    if total == 0:
        raise ValueError("calibration error requires observations")
    return float(sum(
        int(item["count"]) * abs(
            float(item["observed_frequency"]) - float(item["mean_predicted"])
        )
        for item in curve
    ) / total)


def calibration_intercept_slope(
    labels: Sequence[int | bool], probabilities: Sequence[float], *, epsilon: float = 1e-8,
) -> dict[str, float | str | None]:
    """Fit ``logit(P(Y=1)) = intercept + slope * logit(p)`` for audit.

    This diagnostic fit does not replace or recalibrate the supplied scores.
    Degenerate labels or predictions are returned explicitly as unavailable.
    """
    y = np.asarray(labels, dtype=float)
    p = np.asarray(probabilities, dtype=float)
    if y.ndim != 1 or p.ndim != 1 or len(y) == 0 or len(y) != len(p):
        raise ValueError("labels and probabilities must be aligned non-empty vectors")
    if not np.isin(y, (0.0, 1.0)).all():
        raise ValueError("labels must be binary")
    if not np.isfinite(p).all() or (p < 0).any() or (p > 1).any():
        raise ValueError("probabilities must be finite and within [0, 1]")
    if np.unique(y).size < 2:
        return {"intercept": None, "slope": None, "status": "unavailable_single_class"}
    x = np.log(np.clip(p, epsilon, 1.0 - epsilon) / np.clip(1.0 - p, epsilon, 1.0))
    if float(np.ptp(x)) <= 1e-12:
        return {"intercept": None, "slope": None, "status": "unavailable_constant_prediction"}

    def objective(theta: np.ndarray) -> tuple[float, np.ndarray]:
        linear = theta[0] + theta[1] * x
        fitted = expit(linear)
        loss = float(np.sum(np.logaddexp(0.0, linear) - y * linear))
        residual = fitted - y
        gradient = np.asarray([residual.sum(), np.dot(residual, x)], dtype=float)
        return loss, gradient

    result = minimize(
        objective, np.asarray([0.0, 1.0]), jac=True, method="L-BFGS-B",
        options={"maxiter": 2000, "ftol": 1e-12, "gtol": 1e-9},
    )
    if not result.success or not np.isfinite(result.x).all():
        return {"intercept": None, "slope": None, "status": "unavailable_fit_failed"}
    return {
        "intercept": float(result.x[0]),
        "slope": float(result.x[1]),
        "status": "available",
    }


def calibration_audit(
    labels: Sequence[int | bool], probabilities: Sequence[float], *, bins: int = 10,
) -> dict[str, object]:
    """Combine proper-score, reliability, ECE and logistic calibration audit."""
    base = evaluate_binary_probabilities(labels, probabilities, reliability_bins=bins)
    fit = calibration_intercept_slope(labels, probabilities)
    return {
        "n_observations": base["n_observations"],
        "n_positive": base["n_positive"],
        "prevalence": base["prevalence"],
        "mean_predicted_risk": base["mean_predicted_risk"],
        "brier_score": base["brier_score"],
        "expected_calibration_error": expected_calibration_error(
            labels, probabilities, bins=bins,
        ),
        "calibration_intercept": fit["intercept"],
        "calibration_slope": fit["slope"],
        "calibration_fit_status": fit["status"],
        "reliability_curve": base["reliability_curve"],
    }
