"""FD001 telemetry-reduction experiment with a phase-specific holdout gate."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import tempfile
from time import perf_counter
import tomllib
from typing import Mapping, Sequence

os.environ.setdefault(
    "MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "predictive_maintenance_matplotlib")
)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from predictive_maintenance.application.classical_ml_fd001 import (
    _feature_records,
    _make_model,
    _operational_target,
    _prediction_frame,
    _target_records,
    grouped_unit_folds,
    load_development_partitions,
)
from predictive_maintenance.core.records import TargetRecord
from predictive_maintenance.evaluation.probability import evaluate_binary_probabilities
from predictive_maintenance.features.causal import CausalFeatureConfig, CausalTelemetryFeatures
from predictive_maintenance.filtering.experiment import (
    ReceiverReconstruction,
    build_filter,
    reconstruct_receiver_stream,
)
from predictive_maintenance.models.anomaly.isolation_forest import (
    IsolationForestAnomalyDetector,
    IsolationForestConfig,
)
from predictive_maintenance.models.fusion.probabilistic import (
    RISK_COMPONENTS,
    LogisticStackingFusion,
    ProbabilityCalibrator,
    StackingConfig,
)
from predictive_maintenance.models.ml.classical import RandomForestRiskModel, XGBoostRiskModel
from predictive_maintenance.models.reliability.weibull import Weibull2Parameter, WeibullFitConfig
from predictive_maintenance.models.temporal.discrete_hazard import (
    DiscreteHazardRiskModel,
    HazardConfig,
)


HORIZONS = (15, 30)
MODELS = ("xgboost", "discrete_hazard", "fusion")
KEYS = ["unit_id", "cycle", "horizon"]


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True,
                               allow_nan=False) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _config(path: Path) -> dict[str, object]:
    config = tomllib.loads(path.read_text(encoding="utf-8"))
    if tuple(int(value) for value in config["experiment"]["horizons"]) != HORIZONS:
        raise ValueError("telemetry experiment requires the reviewed H15/H30 contract")
    if config["experiment"]["inference_cadence"] != "each_cycle":
        raise ValueError("this experiment fixes inference cadence to each logical cycle")
    policy_ids = [str(item["id"]) for item in config["policies"]]
    if not policy_ids or len(set(policy_ids)) != len(policy_ids) or policy_ids[0] != "full":
        raise ValueError("policy grid must contain unique IDs and start with full")
    return config


def _feature_config(config: Mapping[str, object]) -> CausalFeatureConfig:
    raw = config["features"]
    return CausalFeatureConfig(
        windows=tuple(int(value) for value in raw["windows"]),
        relative_epsilon=float(raw["relative_epsilon"]),
        variance_epsilon=float(raw["variance_epsilon"]),
        include_cycle=bool(raw["include_cycle"]),
    )


def _policy(config: Mapping[str, object], policy_id: str) -> Mapping[str, object]:
    matches = [item for item in config["policies"] if item["id"] == policy_id]
    if len(matches) != 1:
        raise ValueError(f"unknown policy id: {policy_id}")
    return matches[0]


def _reconstruct(
    frame: pd.DataFrame,
    training_reference: pd.DataFrame,
    config: Mapping[str, object],
    policy_id: str,
) -> ReceiverReconstruction:
    instance, resolved = build_filter(
        _policy(config, policy_id), training_reference=training_reference,
        accounting=config["accounting"],
        stale_after_cycles=int(config["receiver"]["stale_after_cycles"]),
        inference_cadence=str(config["experiment"]["inference_cadence"]),
    )
    return reconstruct_receiver_stream(frame, instance, resolved_policy=resolved)


def _operational_metadata(source: pd.DataFrame, reconstruction: ReceiverReconstruction) -> pd.DataFrame:
    final = source.groupby("unit_id", sort=False).cycle.transform("max")
    frame = source.loc[final.gt(source.cycle), ["unit_id", "cycle"]].copy()
    frame["RUL"] = (final.loc[frame.index] - source.loc[frame.index, "cycle"]).astype(int)
    state = reconstruction.states.set_index(["unit_id", "cycle"])
    joined = frame.join(state, on=["unit_id", "cycle"], validate="one_to_one")
    if joined.isna().any().any() or len(joined) != len(source) - source.unit_id.nunique():
        raise RuntimeError("receiver state does not cover every operational origin")
    return joined.reset_index(drop=True)


def _compatible(engineer: CausalTelemetryFeatures, reconstruction: ReceiverReconstruction) -> bool:
    return set(engineer.raw_columns) <= set(reconstruction.values.columns)


def _receiver_features(
    engineer: CausalTelemetryFeatures,
    reconstruction: ReceiverReconstruction,
) -> pd.DataFrame:
    columns = ["unit_id", "cycle", *engineer.raw_columns]
    return engineer.transform_receiver_frame(
        reconstruction.values.loc[:, columns],
        reconstruction.observed_mask.loc[:, list(engineer.raw_columns)],
    )


def _available_rows(metadata: pd.DataFrame) -> np.ndarray:
    return (metadata.inference_due.astype(bool) & ~metadata.telemetry_stale.astype(bool)).to_numpy()


def _base_output(
    metadata: pd.DataFrame,
    *, horizon: int,
    risk: np.ndarray | None,
    model: str,
    compatible: bool = True,
) -> pd.DataFrame:
    frame = metadata.loc[:, ["unit_id", "cycle", "RUL", "telemetry_stale",
                             "max_sensor_age_cycles", "inference_due"]].copy()
    frame["horizon"] = horizon
    frame["label"] = frame.RUL.le(horizon).astype("int8")
    valid = _available_rows(metadata) & compatible
    frame["risk_score"] = np.nan
    if risk is not None:
        if len(risk) != int(valid.sum()):
            raise RuntimeError("model score count differs from valid receiver origins")
        frame.loc[valid, "risk_score"] = np.asarray(risk, dtype=float)
    frame["prediction_status"] = "unavailable"
    frame.loc[valid & frame.max_sensor_age_cycles.eq(0), "prediction_status"] = "valid"
    frame.loc[valid & frame.max_sensor_age_cycles.gt(0), "prediction_status"] = "degraded"
    frame["input_validity"] = np.where(
        frame.telemetry_stale, "stale", np.where(compatible, "valid", "invalid"))
    frame["model"] = model
    if frame.loc[valid, "risk_score"].isna().any():
        raise RuntimeError("available receiver origins lack probabilities")
    numeric = frame.loc[valid, "risk_score"].to_numpy(dtype=float)
    if not np.isfinite(numeric).all() or ((numeric < 0) | (numeric > 1)).any():
        raise RuntimeError("model produced probability outside [0, 1]")
    return frame


def predict_frozen_full_models(
    source: pd.DataFrame,
    reconstruction: ReceiverReconstruction,
    report_root: Path,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Apply frozen full-trained components only to receiver-visible state."""
    metadata = _operational_metadata(source, reconstruction)
    valid = _available_rows(metadata)
    outputs: list[pd.DataFrame] = []
    audit: dict[str, object] = {}

    classical_engineer = CausalTelemetryFeatures.load(
        report_root / "classical_ml/artifacts/causal_feature_engineer.json")
    classical_ok = _compatible(classical_engineer, reconstruction)
    audit["classical_schema_compatible"] = classical_ok
    classical_records = []
    if classical_ok:
        engineered = _receiver_features(classical_engineer, reconstruction)
        indexed = engineered.set_index(["unit_id", "cycle"])
        selected = indexed.loc[pd.MultiIndex.from_frame(metadata.loc[valid, ["unit_id", "cycle"]])].reset_index()
        classical_records = _feature_records(selected, classical_engineer.feature_names)
    for horizon in HORIZONS:
        scores = None
        if classical_ok:
            model = XGBoostRiskModel.load(
                report_root / f"classical_ml/artifacts/models/xgboost_h{horizon}.joblib")
            scores = np.asarray([item.risk_score for item in
                                 model.predict_risk(classical_records, horizon=horizon)], dtype=float)
        outputs.append(_base_output(metadata, horizon=horizon, risk=scores,
                                    model="xgboost", compatible=classical_ok))

    hazard_engineer = CausalTelemetryFeatures.load(
        report_root / "discrete_hazard/artifacts/causal_feature_engineer.json")
    hazard_ok = _compatible(hazard_engineer, reconstruction)
    audit["hazard_schema_compatible"] = hazard_ok
    hazard_records = []
    hazard_model = DiscreteHazardRiskModel.load(
        report_root / "discrete_hazard/artifacts/model.joblib")
    if hazard_ok:
        engineered = _receiver_features(hazard_engineer, reconstruction)
        indexed = engineered.set_index(["unit_id", "cycle"])
        selected = indexed.loc[pd.MultiIndex.from_frame(metadata.loc[valid, ["unit_id", "cycle"]])].reset_index()
        hazard_records = _feature_records(selected, hazard_engineer.feature_names)
    hazard_scores: dict[int, np.ndarray] = {}
    for horizon in HORIZONS:
        scores = None
        if hazard_ok:
            hazards = hazard_model.predict_hazards(hazard_records, horizon=horizon)
            scores = 1.0 - np.prod(1.0 - hazards, axis=1)
            hazard_scores[horizon] = scores
        outputs.append(_base_output(metadata, horizon=horizon, risk=scores,
                                    model="discrete_hazard", compatible=hazard_ok))

    anomaly_engineer = CausalTelemetryFeatures.load(
        report_root / "anomaly_detection/artifacts/causal_feature_engineer.json")
    anomaly_ok = _compatible(anomaly_engineer, reconstruction)
    audit["anomaly_schema_compatible"] = anomaly_ok
    anomaly_score: np.ndarray | None = None
    if anomaly_ok:
        engineered = _receiver_features(anomaly_engineer, reconstruction)
        indexed = engineered.set_index(["unit_id", "cycle"])
        selected = indexed.loc[pd.MultiIndex.from_frame(metadata.loc[valid, ["unit_id", "cycle"]])].reset_index()
        records = _feature_records(selected, anomaly_engineer.feature_names)
        detector = IsolationForestAnomalyDetector.load(
            report_root / "anomaly_detection/artifacts/isolation_forest.joblib")
        raw = detector.raw_anomaly_score(records)
        anomaly_score = np.searchsorted(detector.healthy_raw_scores, raw, side="right") / len(detector.healthy_raw_scores)

    fusion_ok = classical_ok and hazard_ok and anomaly_ok
    audit["fusion_schema_compatible"] = fusion_ok
    if fusion_ok:
        rf_scores: dict[int, np.ndarray] = {}
        for horizon in HORIZONS:
            model = RandomForestRiskModel.load(
                report_root / f"classical_ml/artifacts/models/random_forest_h{horizon}.joblib")
            rf_scores[horizon] = np.asarray([item.risk_score for item in
                model.predict_risk(classical_records, horizon=horizon)], dtype=float)
        weibull = Weibull2Parameter.load(report_root / "weibull/artifacts/weibull_2p_model.json")
        for horizon in HORIZONS:
            subset = metadata.loc[valid, ["unit_id", "cycle", "RUL"]].copy()
            subset["horizon"] = horizon
            subset["label"] = subset.RUL.le(horizon).astype("int8")
            subset["risk_random_forest"] = rf_scores[horizon]
            xgb = next(item for item in outputs if item.model.eq("xgboost").all()
                       and item.horizon.eq(horizon).all())
            subset["risk_xgboost"] = xgb.loc[valid, "risk_score"].to_numpy(float)
            subset["risk_discrete_hazard"] = hazard_scores[horizon]
            subset["risk_weibull"] = [weibull.conditional_risk(int(age), horizon)
                                       for age in subset.cycle]
            subset["anomaly_score"] = anomaly_score
            subset["simple_raw"] = subset.loc[:, RISK_COMPONENTS].mean(axis=1)
            subset["disagreement"] = (subset.loc[:, RISK_COMPONENTS].max(axis=1)
                                        - subset.loc[:, RISK_COMPONENTS].min(axis=1))
            stack = LogisticStackingFusion.load(
                report_root / f"fusion/artifacts/stacking_h{horizon}.joblib")
            calibrator = ProbabilityCalibrator.load(
                report_root / f"fusion/artifacts/stacking_calibrator_h{horizon}.joblib")
            risk = calibrator.predict(stack.predict_frame(subset))
            outputs.append(_base_output(metadata, horizon=horizon, risk=risk,
                                        model="fusion", compatible=True))
    else:
        for horizon in HORIZONS:
            outputs.append(_base_output(metadata, horizon=horizon, risk=None,
                                        model="fusion", compatible=False))
    return pd.concat(outputs, ignore_index=True), audit


def _best_threshold(labels: Sequence[int], scores: Sequence[float], minimum_precision: float) -> float:
    y = np.asarray(labels, dtype=int)
    p = np.asarray(scores, dtype=float)
    candidates = np.unique(np.r_[0.0, p, 1.0])
    rows = []
    for threshold in candidates:
        selected = p >= threshold
        tp = int(np.sum(selected & (y == 1)))
        fp = int(np.sum(selected & (y == 0)))
        fn = int(np.sum(~selected & (y == 1)))
        precision = tp / (tp + fp) if tp + fp else 1.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        rows.append((precision >= minimum_precision, f1, recall, precision, -threshold, threshold))
    eligible = [row for row in rows if row[0]] or rows
    return float(max(eligible)[-1])


def select_model_thresholds(
    full_predictions: pd.DataFrame,
    config: Mapping[str, object],
) -> dict[str, dict[str, float]]:
    thresholds: dict[str, dict[str, float]] = {}
    minimum_precision = float(config["alerting"]["minimum_precision"])
    policy = tomllib.loads(Path("configs/fusion_alert_policy.toml").read_text(encoding="utf-8"))
    for model in MODELS:
        thresholds[model] = {}
        for horizon in HORIZONS:
            if model == "fusion":
                threshold = (float(policy["thresholds"]["critical"]) if horizon == 15
                             else float(policy["thresholds"]["alert"]))
            else:
                part = full_predictions.loc[(full_predictions.model == model)
                    & (full_predictions.horizon == horizon)]
                threshold = _best_threshold(part.label, part.risk_score, minimum_precision)
            thresholds[model][str(horizon)] = threshold
    return thresholds


def _episode_lengths(mask: np.ndarray, cycles: np.ndarray) -> list[int]:
    lengths: list[int] = []
    run = 0
    previous: int | None = None
    for active, cycle in zip(mask, cycles, strict=True):
        if active:
            run = run + 1 if previous is not None and cycle == previous + 1 else 1
        elif run:
            lengths.append(run)
            run = 0
        previous = int(cycle)
    if run:
        lengths.append(run)
    return lengths


def alert_metrics_by_unit_complete(
    predictions: pd.DataFrame,
    *,
    threshold: float,
    persistence_cycles: int,
) -> pd.DataFrame:
    """Keep every inference opportunity; unavailable breaks alert persistence."""
    rows: list[dict[str, object]] = []
    for unit_id, part in predictions.sort_values(["unit_id", "cycle"]).groupby("unit_id"):
        cycles = part.cycle.to_numpy(dtype=int)
        available = part.prediction_status.isin(["valid", "degraded"]).to_numpy()
        above = available & part.risk_score.fillna(-np.inf).ge(threshold).to_numpy()
        false = above & part.label.eq(0).to_numpy()
        episodes = _episode_lengths(above, cycles)
        false_episodes = _episode_lengths(false, cycles)
        run = 0
        previous: int | None = None
        first: int | None = None
        for active, cycle in zip(above, cycles, strict=True):
            run = run + 1 if active and previous is not None and cycle == previous + 1 else int(active)
            if run >= persistence_cycles and first is None:
                first = int(cycle)
            previous = int(cycle)
        terminal = (part.cycle + part.RUL).astype(int)
        if terminal.nunique() != 1:
            raise RuntimeError("one terminal cycle is required per unit")
        rows.append({
            "unit_id": int(unit_id), "first_alert_cycle": first,
            "lead_time": int(terminal.iloc[0]) - first if first is not None else None,
            "false_alert_episode_count": len(false_episodes),
            "false_alert_episode_duration": int(sum(false_episodes)),
            "alert_persistence": (sum(length >= persistence_cycles for length in episodes) / len(episodes)
                                  if episodes else 0.0),
            "longest_consecutive_alert": max(episodes, default=0),
            "fraction_life_under_alert": float(above.mean()),
            "alert_episode_count": len(episodes),
        })
    return pd.DataFrame(rows)


def evaluate_prediction_table(
    predictions: pd.DataFrame,
    *,
    threshold: float,
    persistence_cycles: int,
    reference_unit_metrics: pd.DataFrame | None = None,
) -> tuple[dict[str, object], pd.DataFrame]:
    available = predictions.prediction_status.isin(["valid", "degraded"]) & predictions.risk_score.notna()
    numeric = predictions.loc[available]
    probability = evaluate_binary_probabilities(numeric.label, numeric.risk_score) if len(numeric) else {
        "n_observations": 0, "brier_score": None, "log_loss": None, "roc_auc": None,
        "pr_auc_average_precision": None, "mean_predicted_risk": None,
        "calibration_in_the_large": None, "reliability_curve": [],
    }
    alerts = available & predictions.risk_score.fillna(-np.inf).ge(threshold)
    y = predictions.label.eq(1)
    tp = int((alerts & y).sum())
    fp = int((alerts & ~y).sum())
    fn = int((~alerts & y).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    unit = alert_metrics_by_unit_complete(predictions, threshold=threshold,
                                          persistence_cycles=persistence_cycles)
    missed = 0
    latency_values: list[float] = []
    if reference_unit_metrics is not None:
        paired = reference_unit_metrics[["unit_id", "first_alert_cycle"]].merge(
            unit[["unit_id", "first_alert_cycle"]], on="unit_id", suffixes=("_full", "_filtered"),
            validate="one_to_one")
        missed = int((paired.first_alert_cycle_full.notna()
                      & paired.first_alert_cycle_filtered.isna()).sum())
        both = paired.dropna(subset=["first_alert_cycle_full", "first_alert_cycle_filtered"])
        latency_values = (both.first_alert_cycle_filtered - both.first_alert_cycle_full).astype(float).tolist()
        unit = unit.merge(paired.assign(alert_latency_cycles=(
            paired.first_alert_cycle_filtered - paired.first_alert_cycle_full))[
                ["unit_id", "alert_latency_cycles"]], on="unit_id", validate="one_to_one")
    statuses = predictions.prediction_status.value_counts()
    metrics = dict(probability)
    metrics.update({
        "threshold": threshold, "opportunities": int(len(predictions)),
        "available_predictions": int(available.sum()), "coverage": float(available.mean()),
        "valid_fraction": float(statuses.get("valid", 0) / len(predictions)),
        "degraded_fraction": float(statuses.get("degraded", 0) / len(predictions)),
        "unavailable_fraction": float(statuses.get("unavailable", 0) / len(predictions)),
        "stale_fraction": float(predictions.telemetry_stale.mean()),
        "maximum_data_age_cycles": int(predictions.max_sensor_age_cycles.max()),
        "precision": precision, "recall": recall, "f1": f1,
        "true_positive": tp, "false_positive": fp, "false_negative": fn,
        "first_alert_units": int(unit.first_alert_cycle.notna().sum()),
        "median_lead_time": _finite_or_none(unit.lead_time.median()),
        "false_alert_episodes_per_unit": float(unit.false_alert_episode_count.mean()),
        "mean_alert_persistence": float(unit.alert_persistence.mean()),
        "missed_anticipated_failures": missed,
        "median_alert_latency_cycles": (_finite_or_none(np.median(latency_values)) if latency_values else None),
        "p90_alert_latency_cycles": (_finite_or_none(np.quantile(latency_values, 0.9)) if latency_values else None),
    })
    return metrics, unit


def _finite_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _full_equivalence(
    predictions: pd.DataFrame,
    report_root: Path,
) -> dict[str, object]:
    sources = {
        "xgboost": report_root / "classical_ml/artifacts/validation_predictions.parquet",
        "discrete_hazard": report_root / "discrete_hazard/artifacts/validation_predictions.parquet",
        "fusion": report_root / "fusion/artifacts/validation_fusion_predictions.parquet",
    }
    result: dict[str, object] = {}
    for model, path in sources.items():
        prior = pd.read_parquet(path)
        if model == "xgboost":
            prior = prior.loc[prior.algorithm.eq("xgboost")]
        current = predictions.loc[predictions.model.eq(model)]
        merged = current.merge(prior[[*KEYS, "risk_score"]], on=KEYS,
                               suffixes=("_current", "_prior"), validate="one_to_one")
        expected = len(current)
        difference = np.abs(merged.risk_score_current - merged.risk_score_prior)
        result[model] = {
            "expected_rows": expected, "matched_rows": len(merged),
            "maximum_absolute_score_difference": float(difference.max()),
            "within_tolerance_1e_12": bool(len(merged) == expected and difference.max() <= 1e-12),
        }
    if not all(item["within_tolerance_1e_12"] for item in result.values()):
        raise RuntimeError("FullTelemetryFilter did not reproduce frozen validation predictions")
    return result


def _acceptance(
    metrics: Mapping[str, object],
    reference: Mapping[str, object],
    communication: Mapping[str, object],
    criteria: Mapping[str, object],
) -> dict[str, object]:
    checks: dict[str, bool] = {}
    reduction = float(communication["byte_reduction_fraction"])
    checks["minimum_byte_reduction"] = reduction >= float(criteria["minimum_byte_reduction_fraction"])
    checks["maximum_stale_fraction"] = float(metrics["stale_fraction"]) <= float(criteria["maximum_stale_fraction"])
    checks["maximum_degraded_fraction"] = float(metrics["degraded_fraction"]) <= float(criteria["maximum_degraded_fraction"])
    checks["maximum_unavailable_fraction"] = float(metrics["unavailable_fraction"]) <= float(criteria["maximum_unavailable_fraction"])
    checks["maximum_data_age"] = int(metrics["maximum_data_age_cycles"]) <= int(criteria["maximum_data_age_cycles"])
    comparable = all(metrics.get(name) is not None and reference.get(name) is not None for name in
                     ("pr_auc_average_precision", "roc_auc", "brier_score"))
    checks["probability_metrics_available"] = comparable
    if comparable:
        checks["pr_auc_loss"] = (float(reference["pr_auc_average_precision"])
            - float(metrics["pr_auc_average_precision"]) <= float(criteria["maximum_pr_auc_absolute_loss"]))
        checks["roc_auc_loss"] = (float(reference["roc_auc"])
            - float(metrics["roc_auc"]) <= float(criteria["maximum_roc_auc_absolute_loss"]))
        checks["brier_increase"] = (float(metrics["brier_score"])
            - float(reference["brier_score"]) <= float(criteria["maximum_brier_increase"]))
    else:
        checks.update({"pr_auc_loss": False, "roc_auc_loss": False, "brier_increase": False})
    checks["recall_loss"] = (float(reference["recall"]) - float(metrics["recall"])
        <= float(criteria["maximum_recall_absolute_loss"]))
    checks["precision_loss"] = (float(reference["precision"]) - float(metrics["precision"])
        <= float(criteria["maximum_precision_absolute_loss"]))
    ref_lead, lead = reference.get("median_lead_time"), metrics.get("median_lead_time")
    checks["median_lead_time_loss"] = bool(ref_lead is not None and lead is not None and
        float(ref_lead) - float(lead) <= float(criteria["maximum_median_lead_time_loss_cycles"]))
    latency = metrics.get("median_alert_latency_cycles")
    p90 = metrics.get("p90_alert_latency_cycles")
    checks["median_alert_latency"] = bool(latency is not None and
        float(latency) <= float(criteria["maximum_median_alert_latency_cycles"]))
    checks["p90_alert_latency"] = bool(p90 is not None and
        float(p90) <= float(criteria["maximum_p90_alert_latency_cycles"]))
    checks["false_alert_episodes"] = (float(metrics["false_alert_episodes_per_unit"])
        - float(reference["false_alert_episodes_per_unit"])
        <= float(criteria["maximum_false_alert_episodes_per_unit_increase"]))
    checks["missed_anticipated_failures"] = (int(metrics["missed_anticipated_failures"])
        <= int(criteria["maximum_missed_anticipated_failures"]))
    return {"passed": all(checks.values()), "checks": checks}


def _select_matched_candidates(
    config: Mapping[str, object],
    scenario_results: Mapping[str, object],
) -> list[str]:
    pool = [str(value) for value in config["selection"]["matched_candidate_pool"]]
    max_candidates = int(config["experiment"]["max_matched_candidates"])
    kinds = {str(item["id"]): str(item["kind"]) for item in config["policies"]}
    passed = []
    for policy_id in pool:
        scenario = scenario_results[policy_id]
        if all(scenario["acceptance"][model][str(horizon)]["passed"]
               for model in MODELS for horizon in HORIZONS):
            passed.append(policy_id)
    passed.sort(key=lambda policy_id: (
        -float(scenario_results[policy_id]["communication"]["byte_reduction_fraction"]), policy_id))
    selected: list[str] = passed[:1]
    # The second point is deterministic and may be a diagnostic non-passing candidate.
    remaining = [policy_id for policy_id in pool if policy_id not in selected]
    if selected:
        distinct = [policy_id for policy_id in remaining if kinds[policy_id] != kinds[selected[0]]]
        remaining = distinct or remaining
    if remaining and len(selected) < max_candidates:
        remaining.sort(key=lambda policy_id: (
            -sum(scenario_results[policy_id]["acceptance"][model][str(h)]["passed"]
                 for model in MODELS for h in HORIZONS),
            -float(scenario_results[policy_id]["communication"]["byte_reduction_fraction"]),
            policy_id,
        ))
        selected.append(remaining[0])
    return selected


def _plot_tradeoffs(metrics_frame: pd.DataFrame, figures: Path) -> None:
    figures.mkdir(parents=True, exist_ok=True)
    plots = [
        ("pr_auc_average_precision", "PR AUC", "bytes_vs_pr_auc.png"),
        ("recall", "Recall", "bytes_vs_recall.png"),
        ("median_lead_time", "Median lead time (cycles)", "bytes_vs_lead_time.png"),
        ("false_alert_episodes_per_unit", "False alert episodes / unit", "bytes_vs_false_alerts.png"),
        ("degraded_fraction", "Degraded output fraction", "bytes_vs_degraded.png"),
    ]
    for column, label, filename in plots:
        fig, axes = plt.subplots(1, len(MODELS), figsize=(15, 4), sharex=True)
        for axis, model in zip(axes, MODELS, strict=True):
            part = metrics_frame.loc[metrics_frame.model.eq(model)]
            for horizon, marker in zip(HORIZONS, ("o", "s"), strict=True):
                values = part.loc[part.horizon.eq(horizon)]
                axis.scatter(values.bytes_relative, values[column], label=f"H={horizon}", marker=marker)
                for row in values.itertuples():
                    axis.annotate(row.policy_id, (row.bytes_relative, getattr(row, column)), fontsize=7)
            axis.set_title(model)
            axis.set_xlabel("Relative estimated bytes")
            axis.grid(alpha=.25)
        axes[0].set_ylabel(label)
        axes[-1].legend()
        fig.tight_layout()
        fig.savefig(figures / filename, dpi=160)
        plt.close(fig)
    fig, axis = plt.subplots(figsize=(7, 5))
    for model in MODELS:
        part = metrics_frame.loc[(metrics_frame.model.eq(model)) & metrics_frame.horizon.eq(30)]
        error = part.calibration_in_the_large.abs()
        axis.scatter(part.stale_fraction, error, label=model)
        for row, y in zip(part.itertuples(), error, strict=True):
            axis.annotate(row.policy_id, (row.stale_fraction, y), fontsize=7)
    axis.set(xlabel="Stale opportunity fraction", ylabel="Absolute calibration-in-the-large error")
    axis.grid(alpha=.25)
    axis.legend()
    fig.tight_layout()
    fig.savefig(figures / "staleness_vs_calibration_error.png", dpi=160)
    plt.close(fig)


def run_full_trained_development(
    processed: Path = Path("data/processed/fd001"),
    config_path: Path = Path("configs/telemetry_reduction_experiment.toml"),
    report_root: Path = Path("reports"),
) -> dict[str, object]:
    """Evaluate the frozen full-trained pipeline on validation only."""
    config = _config(config_path)
    train, validation, manifest = load_development_partitions(processed)
    root = report_root / "telemetry_filtering"
    artifacts = root / "artifacts"
    figures = root / "figures"
    artifacts.mkdir(parents=True, exist_ok=True)
    all_predictions: list[pd.DataFrame] = []
    reconstructions: dict[str, ReceiverReconstruction] = {}
    audits: dict[str, object] = {}
    timing: dict[str, float] = {}
    for policy_spec in config["policies"]:
        policy_id = str(policy_spec["id"])
        reconstruction = _reconstruct(validation, train, config, policy_id)
        reconstructions[policy_id] = reconstruction
        policy_dir = artifacts / "full_trained" / policy_id
        policy_dir.mkdir(parents=True, exist_ok=True)
        reconstruction.values.to_parquet(policy_dir / "receiver_values.parquet", index=False)
        reconstruction.observed_mask.to_parquet(policy_dir / "receiver_observed_mask.parquet", index=False)
        reconstruction.states.to_parquet(policy_dir / "receiver_states.parquet", index=False)
        reconstruction.packets.to_parquet(policy_dir / "packets.parquet", index=False)
        start = perf_counter()
        prediction, audit = predict_frozen_full_models(validation, reconstruction, report_root)
        timing[policy_id] = perf_counter() - start
        prediction["policy_id"] = policy_id
        prediction["regime"] = "full_trained_filtered_inference"
        prediction.to_parquet(policy_dir / "validation_predictions.parquet", index=False)
        all_predictions.append(prediction)
        audits[policy_id] = audit
    predictions = pd.concat(all_predictions, ignore_index=True)
    predictions.to_parquet(artifacts / "full_trained_validation_predictions.parquet", index=False)
    full = predictions.loc[predictions.policy_id.eq("full")].copy()
    equivalence = _full_equivalence(full, report_root)
    thresholds = select_model_thresholds(full, config)
    _write_json(artifacts / "alert_thresholds.json", {
        "source_partition": "validation", "selected_before_filtered_comparison": True,
        "persistence_cycles": int(config["alerting"]["persistence_cycles"]),
        "thresholds": thresholds,
    })
    reference_units: dict[tuple[str, int], pd.DataFrame] = {}
    reference_metrics: dict[tuple[str, int], dict[str, object]] = {}
    for model in MODELS:
        for horizon in HORIZONS:
            part = full.loc[(full.model.eq(model)) & (full.horizon.eq(horizon))]
            metric, units = evaluate_prediction_table(
                part, threshold=thresholds[model][str(horizon)],
                persistence_cycles=int(config["alerting"]["persistence_cycles"]),
            )
            reference_units[(model, horizon)] = units
            reference_metrics[(model, horizon)] = metric
    scenarios: dict[str, object] = {}
    metric_rows: list[dict[str, object]] = []
    unit_frames: list[pd.DataFrame] = []
    for policy_spec in config["policies"]:
        policy_id = str(policy_spec["id"])
        communication = dict(reconstructions[policy_id].communication_metrics)
        scenario = {"communication": communication, "resolved_policy": dict(
            reconstructions[policy_id].resolved_policy), "inference_time_seconds": timing[policy_id],
            "metrics": {}, "acceptance": {}}
        local = predictions.loc[predictions.policy_id.eq(policy_id)]
        for model in MODELS:
            scenario["metrics"][model] = {}
            scenario["acceptance"][model] = {}
            for horizon in HORIZONS:
                part = local.loc[(local.model.eq(model)) & (local.horizon.eq(horizon))]
                metric, units = evaluate_prediction_table(
                    part, threshold=thresholds[model][str(horizon)],
                    persistence_cycles=int(config["alerting"]["persistence_cycles"]),
                    reference_unit_metrics=reference_units[(model, horizon)],
                )
                scenario["metrics"][model][str(horizon)] = metric
                accepted = _acceptance(metric, reference_metrics[(model, horizon)],
                                       communication, config["acceptance"])
                scenario["acceptance"][model][str(horizon)] = accepted
                row = {"regime": "full_trained", "partition": "validation",
                       "policy_id": policy_id, "model": model, "horizon": horizon,
                       "bytes_relative": 1.0 - float(communication["byte_reduction_fraction"]),
                       "byte_reduction_fraction": float(communication["byte_reduction_fraction"]),
                       "inference_time_seconds": timing[policy_id], "accepted": accepted["passed"],
                       **{name: value for name, value in metric.items()
                          if name != "reliability_curve"}}
                metric_rows.append(row)
                units = units.assign(policy_id=policy_id, model=model, horizon=horizon,
                                     regime="full_trained", partition="validation")
                unit_frames.append(units)
        scenarios[policy_id] = scenario
    selected = _select_matched_candidates(config, scenarios)
    metrics_frame = pd.DataFrame(metric_rows)
    metrics_frame.to_parquet(artifacts / "development_metrics.parquet", index=False)
    pd.concat(unit_frames, ignore_index=True).to_parquet(
        artifacts / "development_metrics_by_unit.parquet", index=False)
    _plot_tradeoffs(metrics_frame, figures)
    payload = {
        "protocol": {
            "phase": "development_full_trained_filtered_inference",
            "train_rows": len(train), "validation_rows": len(validation),
            "train_units": int(train.unit_id.nunique()),
            "validation_units": int(validation.unit_id.nunique()),
            "test_internal_read": False, "official_nasa_test_read": False,
            "features_recomputed_from_receiver_state": True,
            "held_values_counted_as_new_observations": False,
            "criteria_config_sha256": _sha(config_path),
        },
        "full_equivalence": equivalence, "thresholds": thresholds,
        "scenario_results": scenarios, "matched_candidates_selected": selected,
        "audits": audits,
    }
    _write_json(root / "development_results.json", payload)
    return payload


def _tree_config(config: Mapping[str, object]) -> dict[str, object]:
    raw = config["matched_models"]
    return {
        "models": {"version": str(raw["model_version"]),
                   "random_seed": int(raw["random_seed"])},
        "random_forest": dict(raw["random_forest"]),
        "xgboost": dict(raw["xgboost"]),
    }


def _observed_values(reconstruction: ReceiverReconstruction) -> pd.DataFrame:
    return reconstruction.observed_mask.drop(columns=["unit_id", "cycle"])


def _fit_policy_components(
    source: pd.DataFrame,
    reconstruction: ReceiverReconstruction,
    config: Mapping[str, object],
    *, seed_offset: int = 0,
) -> dict[str, object]:
    operational, _ = _operational_target(source, 1)
    available = operational & (~reconstruction.states.telemetry_stale.to_numpy(bool))
    engineer = CausalTelemetryFeatures(_feature_config(config)).fit_receiver_frame(
        reconstruction.values, _observed_values(reconstruction), fit_mask=available)
    engineered = engineer.transform_receiver_frame(
        reconstruction.values.loc[:, ["unit_id", "cycle", *engineer.raw_columns]],
        reconstruction.observed_mask.loc[:, list(engineer.raw_columns)],
    )
    records = _feature_records(engineered.loc[available], engineer.feature_names)
    keys = source.loc[available, ["unit_id", "cycle"]]
    tree_models: dict[tuple[str, int], object] = {}
    tree_config = _tree_config(config)
    for algorithm in ("random_forest", "xgboost"):
        for horizon in HORIZONS:
            _, labels = _operational_target(source, horizon)
            # The horizon mask is identical for every positive horizon: operational origins only.
            model = _make_model(algorithm, horizon, engineer.feature_names, tree_config,
                                seed_offset=seed_offset)
            model.fit(records, _target_records(keys, labels[
                (~reconstruction.states.loc[operational, "telemetry_stale"].to_numpy(bool))
            ], horizon))
            tree_models[(algorithm, horizon)] = model

    hcfg = config["matched_models"]["hazard"]
    hazard = DiscreteHazardRiskModel(engineer.feature_names, HazardConfig(
        max_horizon=int(hcfg["max_horizon"]), regularization=float(hcfg["regularization"]),
        max_iterations=int(hcfg["max_iterations"]), tolerance=float(hcfg["tolerance"]),
        model_version=str(config["matched_models"]["model_version"]),
    ))
    endpoints = source.groupby("unit_id").cycle.max()
    outcomes = [TargetRecord(unit_id=record.unit_id, cycle=record.cycle,
        values={"observed_end": int(endpoints.loc[int(record.unit_id)]), "event_observed": 1})
        for record in records]
    hazard.fit(records, outcomes)

    acfg = config["matched_models"]["anomaly"]
    detector = IsolationForestAnomalyDetector(engineer.feature_names, IsolationForestConfig(
        model_version=str(acfg["model_version"]), random_seed=int(acfg["random_seed"]) + seed_offset,
        n_estimators=int(acfg["n_estimators"]), max_samples=int(acfg["max_samples"]),
        contamination=str(acfg["contamination"]),
    ))
    final = source.groupby("unit_id", sort=False).cycle.transform("max")
    rul = (final - source.cycle).to_numpy(dtype=int)
    healthy = rul[available] > int(acfg["healthy_minimum_rul_exclusive"])
    if healthy.sum() < 2:
        raise RuntimeError("matched anomaly healthy population is insufficient")
    detector.fit([record for record, keep in zip(records, healthy, strict=True) if keep])

    lifetimes = source.groupby("unit_id").cycle.max()
    weibull = Weibull2Parameter(WeibullFitConfig(
        model_name="weibull_2p_population_age_fd001_telemetry",
        model_version=str(config["matched_models"]["model_version"]),
    )).fit_lifetimes(lifetimes.to_numpy(float), np.ones(len(lifetimes), dtype=int),
                    unit_ids=[str(int(unit)) for unit in lifetimes.index])
    return {"engineer": engineer, "trees": tree_models, "hazard": hazard,
            "anomaly": detector, "weibull": weibull}


def _predict_policy_components(
    source: pd.DataFrame,
    reconstruction: ReceiverReconstruction,
    components: Mapping[str, object],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    metadata = _operational_metadata(source, reconstruction)
    valid = _available_rows(metadata)
    engineer: CausalTelemetryFeatures = components["engineer"]
    engineered = engineer.transform_receiver_frame(
        reconstruction.values.loc[:, ["unit_id", "cycle", *engineer.raw_columns]],
        reconstruction.observed_mask.loc[:, list(engineer.raw_columns)],
    )
    indexed = engineered.set_index(["unit_id", "cycle"])
    selected = indexed.loc[pd.MultiIndex.from_frame(
        metadata.loc[valid, ["unit_id", "cycle"]])].reset_index()
    records = _feature_records(selected, engineer.feature_names)
    anomaly: IsolationForestAnomalyDetector = components["anomaly"]
    raw_anomaly = anomaly.raw_anomaly_score(records)
    anomaly_score = np.searchsorted(anomaly.healthy_raw_scores, raw_anomaly, side="right") / len(anomaly.healthy_raw_scores)
    outputs: list[pd.DataFrame] = []
    base: list[pd.DataFrame] = []
    for horizon in HORIZONS:
        scores: dict[str, np.ndarray] = {}
        for algorithm in ("random_forest", "xgboost"):
            model = components["trees"][(algorithm, horizon)]
            scores[algorithm] = np.asarray([item.risk_score for item in
                model.predict_risk(records, horizon=horizon)], dtype=float)
        hazard: DiscreteHazardRiskModel = components["hazard"]
        hazards = hazard.predict_hazards(records, horizon=horizon)
        scores["discrete_hazard"] = 1.0 - np.prod(1.0 - hazards, axis=1)
        outputs.append(_base_output(metadata, horizon=horizon, risk=scores["xgboost"],
                                    model="xgboost"))
        outputs.append(_base_output(metadata, horizon=horizon, risk=scores["discrete_hazard"],
                                    model="discrete_hazard"))
        local = metadata.loc[valid, ["unit_id", "cycle", "RUL"]].copy()
        local["horizon"] = horizon
        local["label"] = local.RUL.le(horizon).astype("int8")
        local["risk_random_forest"] = scores["random_forest"]
        local["risk_xgboost"] = scores["xgboost"]
        local["risk_discrete_hazard"] = scores["discrete_hazard"]
        weibull: Weibull2Parameter = components["weibull"]
        local["risk_weibull"] = [weibull.conditional_risk(int(age), horizon)
                                  for age in local.cycle]
        local["anomaly_score"] = anomaly_score
        local["simple_raw"] = local.loc[:, RISK_COMPONENTS].mean(axis=1)
        local["disagreement"] = (local.loc[:, RISK_COMPONENTS].max(axis=1)
                                  - local.loc[:, RISK_COMPONENTS].min(axis=1))
        base.append(local)
    return pd.concat(base, ignore_index=True), pd.concat(outputs, ignore_index=True), metadata


def _stacking_config(config: Mapping[str, object], horizon: int, seed_offset: int = 0) -> StackingConfig:
    raw = config["matched_fusion"]
    return StackingConfig(
        horizon=horizon, model_version=str(raw["model_version"]),
        random_seed=int(raw["random_seed"]) + seed_offset,
        regularization_c=float(raw["regularization_c"]),
        max_iterations=int(raw["max_iterations"]),
        anomaly_feature_name="anomaly_score" if raw["include_anomaly_covariate"] else None,
    )


def _fit_matched_fusion(
    oof: pd.DataFrame,
    config: Mapping[str, object],
    artifact_dir: Path,
) -> tuple[pd.DataFrame, dict[int, LogisticStackingFusion], dict[int, ProbabilityCalibrator]]:
    result = oof.copy()
    result["meta_raw"] = np.nan
    result["meta_fold"] = -1
    meta_folds = grouped_unit_folds(result.unit_id.astype(int).tolist(),
        folds=int(config["cross_validation"]["folds"]),
        seed=int(config["cross_validation"]["seed"]) + 101)
    models: dict[int, LogisticStackingFusion] = {}
    calibrators: dict[int, ProbabilityCalibrator] = {}
    for horizon in HORIZONS:
        horizon_mask = result.horizon.eq(horizon)
        for fold_index, holdout in enumerate(meta_folds):
            holdout_mask = horizon_mask & result.unit_id.isin(holdout)
            fitting_mask = horizon_mask & ~result.unit_id.isin(holdout)
            model = LogisticStackingFusion(_stacking_config(config, horizon, fold_index))
            model.fit_frame(result.loc[fitting_mask])
            result.loc[holdout_mask, "meta_raw"] = model.predict_frame(result.loc[holdout_mask])
            result.loc[holdout_mask, "meta_fold"] = fold_index
        final = LogisticStackingFusion(_stacking_config(config, horizon)).fit_frame(
            result.loc[horizon_mask])
        final.save(artifact_dir / f"stacking_h{horizon}.joblib")
        models[horizon] = final
        # Calibrator training scores are themselves grouped cross-fit meta outputs.
        raw = config["matched_fusion"]
        calibrator = ProbabilityCalibrator(
            str(raw["calibration_method"]), seed=int(raw["calibration_seed"])
        ).fit(result.loc[horizon_mask, "meta_raw"], result.loc[horizon_mask, "label"])
        calibrator.save(artifact_dir / f"stacking_calibrator_h{horizon}.joblib")
        calibrators[horizon] = calibrator
        result.loc[horizon_mask, "fusion_oof_risk"] = calibrator.predict(
            result.loc[horizon_mask, "meta_raw"])
    if result.meta_raw.isna().any() or result.meta_fold.lt(0).any():
        raise RuntimeError("matched meta-model OOF coverage is incomplete")
    return result, models, calibrators


def _save_components(components: Mapping[str, object], artifact_dir: Path) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    components["engineer"].save(artifact_dir / "causal_feature_engineer.json")
    for (algorithm, horizon), model in components["trees"].items():
        model.save(artifact_dir / f"{algorithm}_h{horizon}.joblib")
    components["hazard"].save(artifact_dir / "discrete_hazard.joblib")
    components["anomaly"].save(artifact_dir / "isolation_forest.joblib")
    components["weibull"].save(artifact_dir / "weibull_2p.json")


def _load_components(artifact_dir: Path) -> dict[str, object]:
    return {
        "engineer": CausalTelemetryFeatures.load(artifact_dir / "causal_feature_engineer.json"),
        "trees": {(algorithm, horizon): (RandomForestRiskModel if algorithm == "random_forest"
                    else XGBoostRiskModel).load(artifact_dir / f"{algorithm}_h{horizon}.joblib")
                  for algorithm in ("random_forest", "xgboost") for horizon in HORIZONS},
        "hazard": DiscreteHazardRiskModel.load(artifact_dir / "discrete_hazard.joblib"),
        "anomaly": IsolationForestAnomalyDetector.load(artifact_dir / "isolation_forest.joblib"),
        "weibull": Weibull2Parameter.load(artifact_dir / "weibull_2p.json"),
    }


def train_matched_policy(
    policy_id: str,
    train: pd.DataFrame,
    validation: pd.DataFrame,
    config: Mapping[str, object],
    artifact_dir: Path,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Refit filter, preprocessing and base models inside grouped OOF folds."""
    folds = grouped_unit_folds(train.unit_id.astype(int).tolist(),
        folds=int(config["cross_validation"]["folds"]), seed=int(config["cross_validation"]["seed"]))
    all_units = set(train.unit_id.astype(int))
    oof_frames: list[pd.DataFrame] = []
    fold_audit: list[dict[str, object]] = []
    for fold_index, holdout in enumerate(folds):
        holdout_set = set(holdout)
        fitting = all_units - holdout_set
        fit_source = train.loc[train.unit_id.isin(fitting)].reset_index(drop=True)
        hold_source = train.loc[train.unit_id.isin(holdout_set)].reset_index(drop=True)
        fit_reconstruction = _reconstruct(fit_source, fit_source, config, policy_id)
        hold_reconstruction = _reconstruct(hold_source, fit_source, config, policy_id)
        components = _fit_policy_components(fit_source, fit_reconstruction, config,
                                            seed_offset=fold_index)
        base, _, _ = _predict_policy_components(hold_source, hold_reconstruction, components)
        base["fold"] = fold_index
        base["partition"] = "train_oof"
        oof_frames.append(base)
        fold_audit.append({
            "fold": fold_index, "fitting_units": sorted(fitting), "holdout_units": holdout,
            "unit_overlap": [], "resolved_policy": dict(hold_reconstruction.resolved_policy),
            "feature_count": len(components["engineer"].feature_names),
        })
    oof = pd.concat(oof_frames, ignore_index=True).sort_values(KEYS).reset_index(drop=True)
    expected = (len(train) - train.unit_id.nunique()) * len(HORIZONS)
    if len(oof) != expected or oof.duplicated(KEYS).any():
        raise RuntimeError("matched base OOF predictions do not cover every train origin once")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    stacked_oof, stacking, calibrators = _fit_matched_fusion(oof, config, artifact_dir)
    stacked_oof.to_parquet(artifact_dir / "train_oof_inputs_and_predictions.parquet", index=False)

    train_reconstruction = _reconstruct(train, train, config, policy_id)
    validation_reconstruction = _reconstruct(validation, train, config, policy_id)
    components = _fit_policy_components(train, train_reconstruction, config)
    _save_components(components, artifact_dir)
    base_validation, base_outputs, metadata = _predict_policy_components(
        validation, validation_reconstruction, components)
    fusion_frames: list[pd.DataFrame] = []
    for horizon in HORIZONS:
        local = base_validation.loc[base_validation.horizon.eq(horizon)].copy()
        risk = calibrators[horizon].predict(stacking[horizon].predict_frame(local))
        fusion_frames.append(_base_output(metadata, horizon=horizon, risk=risk, model="fusion"))
    predictions = pd.concat([base_outputs, *fusion_frames], ignore_index=True)
    predictions["policy_id"] = policy_id
    predictions["regime"] = "matched_training_and_inference"
    predictions.to_parquet(artifact_dir / "validation_predictions.parquet", index=False)
    validation_reconstruction.states.to_parquet(artifact_dir / "validation_receiver_states.parquet", index=False)
    _write_json(artifact_dir / "fold_manifest.json", {
        "folds": fold_audit, "test_internal_read": False, "official_nasa_test_read": False,
        "policy_id": policy_id,
    })
    return predictions, {
        "oof_rows": len(stacked_oof), "folds": fold_audit,
        "communication": dict(validation_reconstruction.communication_metrics),
        "resolved_policy": dict(validation_reconstruction.resolved_policy),
    }


def _policy_specific_thresholds(
    predictions: pd.DataFrame,
    config: Mapping[str, object],
) -> dict[str, dict[str, float]]:
    output: dict[str, dict[str, float]] = {}
    minimum = float(config["alerting"]["minimum_precision"])
    for model in MODELS:
        output[model] = {}
        for horizon in HORIZONS:
            part = predictions.loc[(predictions.model.eq(model)) & predictions.horizon.eq(horizon)]
            available = part.prediction_status.isin(["valid", "degraded"]) & part.risk_score.notna()
            output[model][str(horizon)] = _best_threshold(
                part.loc[available, "label"], part.loc[available, "risk_score"], minimum)
    return output


def _write_alert_configuration(
    path: Path,
    thresholds: Mapping[str, Mapping[str, Mapping[str, float]]],
) -> None:
    lines = [
        '# Generated from validation only for the FD001 telemetry experiment.',
        'version = "1.0.0"',
        'source_partition = "validation"',
        'persistence_cycles = 3',
        'interpretation = "Experimental FD001 thresholds; not real aeronautical limits."',
    ]
    for policy_id, models in thresholds.items():
        for model, horizons in models.items():
            section = f'{policy_id}.{model}'.replace('-', '_')
            lines += ["", f'[thresholds."{section}"]',
                      f'h15 = {float(horizons["15"]):.17g}',
                      f'h30 = {float(horizons["30"]):.17g}']
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _artifact_hashes(paths: Sequence[Path], root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    root = root.resolve()
    for path in sorted(paths, key=lambda item: item.as_posix()):
        candidate = path if path.is_absolute() else Path.cwd() / path
        candidate = candidate.resolve()
        if candidate.is_file():
            result[candidate.relative_to(root).as_posix()] = _sha(candidate)
    return result


def run_matched_development_and_freeze(
    processed: Path = Path("data/processed/fd001"),
    config_path: Path = Path("configs/telemetry_reduction_experiment.toml"),
    report_root: Path = Path("reports"),
) -> dict[str, object]:
    """Retrain selected policies, evaluate validation, then freeze the test plan."""
    config = _config(config_path)
    train, validation, split_manifest = load_development_partitions(processed)
    root = report_root / "telemetry_filtering"
    development_path = root / "development_results.json"
    development = json.loads(development_path.read_text(encoding="utf-8"))
    if development["protocol"]["criteria_config_sha256"] != _sha(config_path):
        raise RuntimeError("experiment configuration changed after full-trained development")
    selected = [str(value) for value in development["matched_candidates_selected"]]
    if not selected:
        raise RuntimeError("development did not select matched-training candidates")
    full_predictions = pd.read_parquet(
        root / "artifacts/full_trained/full/validation_predictions.parquet")
    full_thresholds = development["thresholds"]
    reference_units: dict[tuple[str, int], pd.DataFrame] = {}
    reference_metrics: dict[tuple[str, int], dict[str, object]] = {}
    for model in MODELS:
        for horizon in HORIZONS:
            part = full_predictions.loc[(full_predictions.model.eq(model))
                                        & full_predictions.horizon.eq(horizon)]
            metrics, units = evaluate_prediction_table(
                part, threshold=float(full_thresholds[model][str(horizon)]),
                persistence_cycles=int(config["alerting"]["persistence_cycles"]),
            )
            reference_metrics[(model, horizon)] = metrics
            reference_units[(model, horizon)] = units
    results: dict[str, object] = {}
    metric_rows: list[dict[str, object]] = []
    unit_rows: list[pd.DataFrame] = []
    threshold_config: dict[str, dict[str, dict[str, float]]] = {"full": full_thresholds}
    for policy_id in selected:
        policy_dir = root / "artifacts" / "matched" / policy_id
        predictions, training_audit = train_matched_policy(
            policy_id, train, validation, config, policy_dir)
        thresholds = _policy_specific_thresholds(predictions, config)
        threshold_config[policy_id] = thresholds
        communication = training_audit["communication"]
        scenario: dict[str, object] = {
            "training_audit": training_audit, "thresholds": thresholds,
            "metrics": {}, "acceptance": {},
        }
        for model in MODELS:
            scenario["metrics"][model] = {}
            scenario["acceptance"][model] = {}
            for horizon in HORIZONS:
                part = predictions.loc[(predictions.model.eq(model))
                                       & predictions.horizon.eq(horizon)]
                metrics, units = evaluate_prediction_table(
                    part, threshold=thresholds[model][str(horizon)],
                    persistence_cycles=int(config["alerting"]["persistence_cycles"]),
                    reference_unit_metrics=reference_units[(model, horizon)],
                )
                accepted = _acceptance(metrics, reference_metrics[(model, horizon)],
                                       communication, config["acceptance"])
                scenario["metrics"][model][str(horizon)] = metrics
                scenario["acceptance"][model][str(horizon)] = accepted
                metric_rows.append({
                    "regime": "matched", "partition": "validation", "policy_id": policy_id,
                    "model": model, "horizon": horizon,
                    "bytes_relative": 1.0 - float(communication["byte_reduction_fraction"]),
                    "byte_reduction_fraction": float(communication["byte_reduction_fraction"]),
                    "accepted": accepted["passed"],
                    **{name: value for name, value in metrics.items()
                       if name != "reliability_curve"},
                })
                unit_rows.append(units.assign(
                    policy_id=policy_id, model=model, horizon=horizon,
                    regime="matched", partition="validation"))
        results[policy_id] = scenario
    matched_metrics = pd.DataFrame(metric_rows)
    matched_metrics.to_parquet(root / "artifacts/matched_validation_metrics.parquet", index=False)
    pd.concat(unit_rows, ignore_index=True).to_parquet(
        root / "artifacts/matched_validation_metrics_by_unit.parquet", index=False)
    _write_alert_configuration(Path("configs/telemetry_reduction_alert_policy.toml"),
                               threshold_config)
    test_candidates = [policy_id for policy_id in selected if all(
        results[policy_id]["acceptance"][model][str(horizon)]["passed"]
        for model in MODELS for horizon in HORIZONS)]
    # Full is always the phase reference; it is not itself a reduction candidate.
    frozen_ids = ["full", *test_candidates]
    artifact_paths: list[Path] = [config_path, Path("configs/telemetry_reduction_alert_policy.toml"),
        Path("src/predictive_maintenance/application/telemetry_reduction_fd001.py"),
        Path("src/predictive_maintenance/filtering/experiment.py"),
        Path("src/predictive_maintenance/features/causal.py"),
        processed / "split_manifest.json", development_path,
        report_root / "fusion/test_evaluation_receipt.json"]
    for policy_id in test_candidates:
        artifact_paths.extend((root / "artifacts/matched" / policy_id).glob("*"))
    hashes = _artifact_hashes(artifact_paths, Path.cwd())
    validation_payload = {
        "matched_results": results, "test_candidates": test_candidates,
        "selection_rule": config["selection"]["test_rule"],
        "test_internal_read": False, "official_nasa_test_read": False,
    }
    _write_json(root / "matched_development_results.json", validation_payload)
    freeze = {
        "state": "frozen", "phase": "telemetry_reduction_0.11.0",
        "frozen_policy_ids": frozen_ids, "reduction_candidates": test_candidates,
        "matched_candidates_evaluated": selected,
        "criteria": config["acceptance"], "thresholds": threshold_config,
        "configuration_sha256": _sha(config_path),
        "validation_results_sha256": _sha(root / "matched_development_results.json"),
        "artifact_sha256": hashes,
        "test_internal_read": False, "official_nasa_test_read": False,
        "prior_project_test_internal_exposure": True,
        "prior_exposure_receipt": "reports/fusion/test_evaluation_receipt.json",
        "scope": "Phase-specific frozen comparison; test_internal was already exposed in phase 0.9.0.",
        "post_test_adjustment_allowed": False,
    }
    _write_json(root / "freeze_manifest.json", freeze)
    return {"selected": selected, "test_candidates": test_candidates,
            "results": results, "freeze": freeze}


def _matched_fusion_predictions(
    base: pd.DataFrame,
    metadata: pd.DataFrame,
    artifact_dir: Path,
) -> pd.DataFrame:
    outputs: list[pd.DataFrame] = []
    for horizon in HORIZONS:
        local = base.loc[base.horizon.eq(horizon)].copy()
        stack = LogisticStackingFusion.load(artifact_dir / f"stacking_h{horizon}.joblib")
        calibrator = ProbabilityCalibrator.load(artifact_dir / f"stacking_calibrator_h{horizon}.joblib")
        scores = calibrator.predict(stack.predict_frame(local))
        outputs.append(_base_output(metadata, horizon=horizon, risk=scores, model="fusion"))
    return pd.concat(outputs, ignore_index=True)


def run_frozen_test(
    processed: Path = Path("data/processed/fd001"),
    config_path: Path = Path("configs/telemetry_reduction_experiment.toml"),
    report_root: Path = Path("reports"),
) -> dict[str, object]:
    """Read test_internal once, after this phase's freeze, and never select from it."""
    root = report_root / "telemetry_filtering"
    freeze_path = root / "freeze_manifest.json"
    receipt_path = root / "test_evaluation_receipt.json"
    if receipt_path.exists():
        raise RuntimeError("telemetry-reduction test_internal evaluation already has a receipt")
    if not freeze_path.exists():
        raise RuntimeError("telemetry-reduction phase must be frozen before test_internal")
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    if freeze.get("state") != "frozen" or freeze.get("test_internal_read") is not False:
        raise RuntimeError("freeze manifest does not authorize this phase-specific holdout read")
    config = _config(config_path)
    train, validation, manifest = load_development_partitions(processed)
    test_path = processed / "test_internal.parquet"
    test = pd.read_parquet(test_path)
    declared = set(int(value) for value in manifest["units"]["test_internal"])
    actual = set(test.unit_id.astype(int))
    if actual != declared:
        raise ValueError("test_internal units do not match split manifest")
    if actual & set(train.unit_id.astype(int)) or actual & set(validation.unit_id.astype(int)):
        raise ValueError("test_internal overlaps development units")
    _write_json(receipt_path, {
        "status": "in_progress", "partition": "test_internal", "read_count": 1,
        "rows_read": len(test), "units_read": len(actual), "test_internal_sha256": _sha(test_path),
        "used_for_selection": False, "official_nasa_test_read": False,
        "prior_project_exposure": True,
    })
    predictions: list[pd.DataFrame] = []
    units: list[pd.DataFrame] = []
    thresholds = freeze["thresholds"]
    full_reconstruction = _reconstruct(test, train, config, "full")
    full_prediction, _ = predict_frozen_full_models(test, full_reconstruction, report_root)
    full_prediction["policy_id"] = "full"
    full_prediction["regime"] = "frozen_test_internal"
    predictions.append(full_prediction)
    full_units: dict[tuple[str, int], pd.DataFrame] = {}
    metrics: dict[str, object] = {}
    for model in MODELS:
        for horizon in HORIZONS:
            part = full_prediction.loc[(full_prediction.model.eq(model))
                                       & full_prediction.horizon.eq(horizon)]
            metric, unit = evaluate_prediction_table(
                part, threshold=float(thresholds["full"][model][str(horizon)]),
                persistence_cycles=int(config["alerting"]["persistence_cycles"]),
            )
            metrics[f"full/{model}/H{horizon}"] = metric
            full_units[(model, horizon)] = unit
            units.append(unit.assign(policy_id="full", model=model, horizon=horizon,
                                     partition="test_internal"))
    for policy_id in freeze["reduction_candidates"]:
        policy_dir = root / "artifacts/matched" / policy_id
        reconstruction = _reconstruct(test, train, config, policy_id)
        components = _load_components(policy_dir)
        base, base_outputs, metadata = _predict_policy_components(test, reconstruction, components)
        fusion = _matched_fusion_predictions(base, metadata, policy_dir)
        candidate = pd.concat([base_outputs, fusion], ignore_index=True)
        candidate["policy_id"] = policy_id
        candidate["regime"] = "frozen_test_internal"
        predictions.append(candidate)
        metrics[policy_id] = {}
        for model in MODELS:
            for horizon in HORIZONS:
                part = candidate.loc[(candidate.model.eq(model)) & candidate.horizon.eq(horizon)]
                threshold = float(thresholds[policy_id][model][str(horizon)])
                metric, unit = evaluate_prediction_table(
                    part, threshold=threshold,
                    persistence_cycles=int(config["alerting"]["persistence_cycles"]),
                    reference_unit_metrics=full_units[(model, horizon)],
                )
                metrics[policy_id][f"{model}/H{horizon}"] = metric
                units.append(unit.assign(policy_id=policy_id, model=model, horizon=horizon,
                                         partition="test_internal"))
    artifact_dir = root / "artifacts"
    pd.concat(predictions, ignore_index=True).to_parquet(
        artifact_dir / "test_internal_predictions.parquet", index=False)
    pd.concat(units, ignore_index=True).to_parquet(
        artifact_dir / "test_internal_metrics_by_unit.parquet", index=False)
    _write_json(artifact_dir / "test_internal_metrics.json", {
        "partition": "test_internal", "used_for_selection": False, "metrics": metrics,
    })
    receipt = {
        "status": "complete", "partition": "test_internal", "read_count": 1,
        "rows_read": len(test), "units_read": len(actual),
        "test_internal_sha256": _sha(test_path), "used_for_selection": False,
        "official_nasa_test_read": False, "prior_project_exposure": True,
        "frozen_policy_ids": freeze["frozen_policy_ids"],
        "no_post_test_adjustment": True,
    }
    _write_json(receipt_path, receipt)
    freeze["test_internal_read"] = True
    freeze["test_evaluation_receipt_sha256"] = _sha(receipt_path)
    _write_json(freeze_path, freeze)
    return {"metrics": metrics, "receipt": receipt}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("development", "matched", "test"),
                        default="development")
    args = parser.parse_args()
    if args.stage == "development":
        result = run_full_trained_development()
    elif args.stage == "matched":
        result = run_matched_development_and_freeze()
    else:
        result = run_frozen_test()
    print(json.dumps({"stage": args.stage, "keys": list(result)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
