"""Binary probability metrics with explicit definitions and tie handling."""

from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd


def evaluate_binary_probabilities(
    labels: Sequence[bool | int],
    probabilities: Sequence[float],
    *,
    reliability_bins: int = 10,
    log_loss_epsilon: float = 1e-15,
) -> dict[str, object]:
    y, p = _validated(labels, probabilities)
    if type(reliability_bins) is not int or reliability_bins < 2:
        raise ValueError("reliability_bins must be an integer of at least 2")
    if not 0 < log_loss_epsilon < 0.5:
        raise ValueError("log_loss_epsilon must be in (0, 0.5)")
    clipped = np.clip(p, log_loss_epsilon, 1.0 - log_loss_epsilon)
    observed = float(y.mean())
    predicted = float(p.mean())
    return {
        "n_observations": int(len(y)),
        "n_positive": int(y.sum()),
        "prevalence": observed,
        "mean_predicted_risk": predicted,
        "calibration_in_the_large": predicted - observed,
        "brier_score": float(np.mean((p - y) ** 2)),
        "roc_auc": roc_auc(y, p),
        "pr_auc_average_precision": average_precision(y, p),
        "log_loss": float(-np.mean(y * np.log(clipped) + (1.0 - y) * np.log1p(-clipped))),
        "reliability_curve": reliability_curve(y, p, reliability_bins),
    }


def threshold_metrics(
    labels: Sequence[bool | int], probabilities: Sequence[float], *, threshold: float,
) -> dict[str, float | int]:
    """Return exploratory binary metrics for an explicitly supplied threshold."""
    y, p = _validated(labels, probabilities)
    if not np.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be finite and within [0, 1]")
    predicted = p >= threshold
    truth = y.astype(bool)
    true_positive = int(np.sum(predicted & truth))
    false_positive = int(np.sum(predicted & ~truth))
    false_negative = int(np.sum(~predicted & truth))
    true_negative = int(np.sum(~predicted & ~truth))
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "threshold": float(threshold), "true_positive": true_positive,
        "false_positive": false_positive, "false_negative": false_negative,
        "true_negative": true_negative, "precision": float(precision),
        "recall": float(recall), "f1": float(f1),
    }


def roc_auc(labels: Sequence[bool | int], probabilities: Sequence[float]) -> float:
    y, p = _validated(labels, probabilities)
    positives = int(y.sum())
    negatives = len(y) - positives
    if positives == 0 or negatives == 0:
        raise ValueError("ROC AUC requires both classes")
    order = np.argsort(p, kind="mergesort")
    sorted_scores = p[order]
    ranks = np.empty(len(p), dtype=float)
    start = 0
    while start < len(p):
        end = start + 1
        while end < len(p) and sorted_scores[end] == sorted_scores[start]:
            end += 1
        ranks[order[start:end]] = (start + 1 + end) / 2.0
        start = end
    return float((ranks[y.astype(bool)].sum() - positives * (positives + 1) / 2)
                 / (positives * negatives))


def average_precision(
    labels: Sequence[bool | int], probabilities: Sequence[float],
) -> float:
    """Area under the stepwise precision-recall curve (average precision)."""
    y, p = _validated(labels, probabilities)
    positives = int(y.sum())
    if positives == 0:
        raise ValueError("PR AUC requires at least one positive")
    order = np.argsort(-p, kind="mergesort")
    y_sorted, p_sorted = y[order], p[order]
    tp = fp = 0
    previous_recall = area = 0.0
    start = 0
    while start < len(y):
        end = start + 1
        while end < len(y) and p_sorted[end] == p_sorted[start]:
            end += 1
        group_positive = int(y_sorted[start:end].sum())
        tp += group_positive
        fp += end - start - group_positive
        recall = tp / positives
        precision = tp / (tp + fp)
        area += (recall - previous_recall) * precision
        previous_recall = recall
        start = end
    return float(area)


def reliability_curve(
    labels: Sequence[bool | int], probabilities: Sequence[float], bins: int,
) -> list[dict[str, float | int]]:
    y, p = _validated(labels, probabilities)
    index = np.minimum((p * bins).astype(int), bins - 1)
    result: list[dict[str, float | int]] = []
    for bin_index in range(bins):
        selected = index == bin_index
        if selected.any():
            result.append({
                "bin": bin_index,
                "lower": bin_index / bins,
                "upper": (bin_index + 1) / bins,
                "count": int(selected.sum()),
                "mean_predicted": float(p[selected].mean()),
                "observed_frequency": float(y[selected].mean()),
            })
    return result


def evaluate_by_unit(
    frame: pd.DataFrame,
    *,
    label_column: str = "label",
    probability_column: str = "risk_score",
    reliability_bins: int = 10,
    log_loss_epsilon: float = 1e-15,
) -> pd.DataFrame:
    required = {"unit_id", label_column, probability_column}
    if frame.empty or not required <= set(frame.columns):
        raise ValueError(f"frame must be non-empty and contain {sorted(required)}")
    rows = []
    for unit_id, unit in frame.groupby("unit_id", sort=True):
        metrics = evaluate_binary_probabilities(
            unit[label_column], unit[probability_column],
            reliability_bins=reliability_bins, log_loss_epsilon=log_loss_epsilon,
        )
        rows.append({"unit_id": unit_id, **{name: value for name, value in metrics.items()
                                            if name != "reliability_curve"}})
    return pd.DataFrame(rows)


def _validated(
    labels: Sequence[bool | int], probabilities: Sequence[float],
) -> tuple[np.ndarray, np.ndarray]:
    y = np.asarray(labels, dtype=float)
    p = np.asarray(probabilities, dtype=float)
    if y.ndim != 1 or p.ndim != 1 or len(y) == 0 or len(y) != len(p):
        raise ValueError("labels and probabilities must be aligned non-empty vectors")
    if not np.isfinite(y).all() or not np.isin(y, [0.0, 1.0]).all():
        raise ValueError("labels must contain only 0 and 1")
    if not np.isfinite(p).all() or (p < 0).any() or (p > 1).any():
        raise ValueError("probabilities must be finite and within [0, 1]")
    return y, p
