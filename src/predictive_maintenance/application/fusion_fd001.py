"""Fit leakage-controlled FD001 probability fusion and evaluate one frozen holdout."""

from __future__ import annotations

import argparse
from hashlib import sha256
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import tempfile
import tomllib

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "predictive_maintenance_matplotlib"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from predictive_maintenance.application.classical_ml_fd001 import grouped_unit_folds
from predictive_maintenance.core.records import FeatureRecord
from predictive_maintenance.evaluation.probability import (
    evaluate_binary_probabilities,
    threshold_metrics,
)
from predictive_maintenance.features.causal import CausalTelemetryFeatures
from predictive_maintenance.models.anomaly.isolation_forest import IsolationForestAnomalyDetector
from predictive_maintenance.models.fusion.probabilistic import (
    AlertThresholds,
    FrozenEvaluationGate,
    LogisticStackingFusion,
    ProbabilityCalibrator,
    RISK_COMPONENTS,
    StackingConfig,
    alert_metrics_by_unit,
    assign_alert_levels,
)
from predictive_maintenance.models.ml.classical import RandomForestRiskModel, XGBoostRiskModel
from predictive_maintenance.models.reliability.weibull import Weibull2Parameter, WeibullFitConfig
from predictive_maintenance.models.temporal.discrete_hazard import DiscreteHazardRiskModel


HORIZONS = (15, 30)
PRIMARY_METHOD = "stacking"


def _sha(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                               indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _read_manifest(processed: Path) -> dict[str, object]:
    manifest = json.loads((processed / "split_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("dataset") != "FD001" or manifest.get("official_evaluation", {}).get("used"):
        raise ValueError("fusion requires the isolated FD001 internal split")
    units = {name: set(map(int, manifest["units"][name]))
             for name in ("train", "validation", "test_internal")}
    if units["train"] & units["validation"] or units["train"] & units["test_internal"] or units["validation"] & units["test_internal"]:
        raise ValueError("split manifest contains unit overlap")
    return manifest


def load_fusion_development(processed: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    """Read only train and validation before the frozen evaluation gate."""
    manifest = _read_manifest(processed)
    frames = []
    for name in ("train", "validation"):
        frame = pd.read_parquet(processed / f"{name}.parquet")
        _validate_partition(frame, name, manifest)
        frames.append(frame)
    return frames[0], frames[1], manifest


def _validate_partition(frame: pd.DataFrame, name: str, manifest: dict[str, object]) -> None:
    if frame.empty or not {"unit_id", "cycle"} <= set(frame.columns):
        raise ValueError(f"invalid {name} partition")
    if frame.duplicated(["unit_id", "cycle"]).any():
        raise ValueError(f"duplicate keys in {name}")
    if set(frame.unit_id.astype(int)) != set(map(int, manifest["units"][name])):
        raise ValueError(f"{name} units differ from split manifest")
    if len(frame) != int(manifest["rows"][name]):
        raise ValueError(f"{name} row count differs from split manifest")


def _operational(frame: pd.DataFrame) -> pd.DataFrame:
    final_cycle = frame.groupby("unit_id", sort=False).cycle.transform("max")
    output = frame.loc[final_cycle.gt(frame.cycle), ["unit_id", "cycle"]].copy()
    output["RUL"] = (final_cycle.loc[output.index] - frame.loc[output.index, "cycle"]).astype(int)
    return output


def generate_weibull_oof(train: pd.DataFrame, fold_manifest_path: Path,
                         output_path: Path) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    """Refit one age-only Weibull in every grouped base-model fold."""
    manifest = json.loads(fold_manifest_path.read_text(encoding="utf-8"))
    all_units = set(train.unit_id.astype(int))
    frames: list[pd.DataFrame] = []
    audits: list[dict[str, object]] = []
    for fold in manifest["folds"]:
        fitting = set(map(int, fold["fitting_units"]))
        holdout = set(map(int, fold["holdout_units"]))
        if fitting & holdout or fitting | holdout != all_units:
            raise ValueError("Weibull OOF fold is not a disjoint unit cover")
        lifetimes = train.loc[train.unit_id.isin(fitting)].groupby("unit_id").cycle.max()
        model = Weibull2Parameter(WeibullFitConfig(
            model_name="weibull_2p_population_age_fd001_oof", model_version="1.0.0"))
        model.fit_lifetimes(lifetimes.to_numpy(float), np.ones(len(lifetimes), dtype=int),
                            unit_ids=[str(int(unit)) for unit in lifetimes.index])
        origins = _operational(train.loc[train.unit_id.isin(holdout)].reset_index(drop=True))
        for horizon in HORIZONS:
            risk = np.asarray([model.conditional_risk(float(age), horizon)
                               for age in origins.cycle], dtype=float)
            frames.append(pd.DataFrame({
                "unit_id": origins.unit_id.astype(int), "cycle": origins.cycle.astype(int),
                "horizon": horizon, "risk_score": risk,
                "label": origins.RUL.le(horizon).astype("int8"),
                "fold": int(fold["fold"]), "partition": "train_oof",
                "model_name": model.config.model_name,
                "model_version": model.config.model_version,
                "prediction_status": "available", "input_validity": "valid",
            }))
        audits.append({"fold": int(fold["fold"]), "fitting_units": sorted(fitting),
                       "holdout_units": sorted(holdout), "overlap": [],
                       "beta": model.beta, "eta": model.eta})
    output = pd.concat(frames, ignore_index=True).sort_values(
        ["unit_id", "cycle", "horizon"]).reset_index(drop=True)
    expected = len(_operational(train)) * len(HORIZONS)
    if len(output) != expected or output.duplicated(["unit_id", "cycle", "horizon"]).any():
        raise RuntimeError("Weibull OOF coverage is incomplete")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_parquet(output_path, index=False)
    return output, audits


def _validate_component_frame(frame: pd.DataFrame, *, score: str, keys: list[str],
                              probability: bool) -> None:
    required = {*keys, score, "prediction_status", "input_validity"}
    if frame.empty or not required <= set(frame.columns) or frame.duplicated(keys).any():
        raise ValueError(f"invalid component frame for {score}")
    values = frame[score].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (probability and ((values < 0).any() or (values > 1).any())):
        raise ValueError(f"invalid values in {score}")
    if not frame.prediction_status.eq("available").all() or not frame.input_validity.eq("valid").all():
        raise ValueError(f"development artifact contains unavailable {score}")


def align_prediction_artifacts(classical: pd.DataFrame, hazard: pd.DataFrame,
                               weibull: pd.DataFrame, anomaly: pd.DataFrame,
                               *, partition: str) -> pd.DataFrame:
    """Align by key, never by row position; anomaly remains a separate covariate."""
    keys = ["unit_id", "cycle", "horizon"]
    if set(classical.algorithm.unique()) != {"random_forest", "xgboost"}:
        raise ValueError("classical artifact must contain RF and XGBoost")
    _validate_component_frame(hazard, score="risk_score", keys=keys, probability=True)
    _validate_component_frame(weibull, score="risk_score", keys=keys, probability=True)
    _validate_component_frame(anomaly, score="anomaly_score", keys=["unit_id", "cycle"], probability=False)
    if classical.duplicated([*keys, "algorithm"]).any():
        raise ValueError("duplicate classical component keys")
    for _, subset in classical.groupby("algorithm"):
        _validate_component_frame(subset, score="risk_score", keys=keys, probability=True)
    if not classical.groupby(keys).label.nunique().eq(1).all():
        raise ValueError("classical labels disagree")
    labels = classical.drop_duplicates(keys)[[*keys, "label"]]
    pivot = classical.pivot(index=keys, columns="algorithm", values="risk_score").reset_index()
    output = pivot.rename(columns={"random_forest": "risk_random_forest",
                                   "xgboost": "risk_xgboost"})
    output = output.merge(labels, on=keys, validate="one_to_one")
    hazard_columns = [*keys, "risk_score", "label"]
    hazard_part = hazard[hazard_columns].rename(columns={"risk_score": "risk_discrete_hazard",
                                                         "label": "hazard_label"})
    output = output.merge(hazard_part, on=keys, validate="one_to_one")
    if not output.label.eq(output.hazard_label).all():
        raise ValueError("hazard labels disagree with classical labels")
    output = output.drop(columns="hazard_label")
    weibull_columns = [*keys, "risk_score"]
    output = output.merge(weibull[weibull_columns].rename(
        columns={"risk_score": "risk_weibull"}), on=keys, validate="one_to_one")
    output = output.merge(anomaly[["unit_id", "cycle", "RUL", "anomaly_score"]],
                          on=["unit_id", "cycle"], validate="many_to_one")
    if output.isna().any().any() or output.duplicated(keys).any():
        raise ValueError("aligned fusion inputs are incomplete")
    risk = output.loc[:, RISK_COMPONENTS].to_numpy(float)
    output["simple_raw"] = risk.mean(axis=1)
    output["disagreement"] = risk.max(axis=1) - risk.min(axis=1)
    output["partition"] = partition
    return output.sort_values(keys).reset_index(drop=True)


def _crossfit_meta(train: pd.DataFrame, config: dict[str, object], artifacts: Path):
    folds = grouped_unit_folds(train.unit_id.tolist(), folds=int(config["cross_validation"]["folds"]),
                               seed=int(config["cross_validation"]["seed"]),)
    output = train.copy()
    output["meta_raw"] = np.nan
    output["meta_fold"] = -1
    models: dict[int, LogisticStackingFusion] = {}
    fold_rows: list[dict[str, object]] = []
    for horizon in HORIZONS:
        selected = output.horizon.eq(horizon)
        for fold_index, holdout in enumerate(folds):
            holdout_mask = selected & output.unit_id.isin(holdout)
            fitting_mask = selected & ~output.unit_id.isin(holdout)
            model = LogisticStackingFusion(_stacking_config(config, horizon, fold_index))
            model.fit_frame(output.loc[fitting_mask])
            output.loc[holdout_mask, "meta_raw"] = model.predict_frame(output.loc[holdout_mask])
            output.loc[holdout_mask, "meta_fold"] = fold_index
            fold_rows.append({"horizon": horizon, "fold": fold_index,
                              "fitting_units": sorted(output.loc[fitting_mask, "unit_id"].unique().tolist()),
                              "holdout_units": holdout, "overlap": []})
        final = LogisticStackingFusion(_stacking_config(config, horizon)).fit_frame(output.loc[selected])
        final.save(artifacts / f"stacking_h{horizon}.joblib")
        models[horizon] = final
    if output.meta_raw.isna().any() or not output.groupby(["unit_id", "horizon"]).meta_fold.nunique().eq(1).all():
        raise RuntimeError("meta-model cross-fitting did not cover each unit once")
    return output, models, fold_rows


def _stacking_config(config: dict[str, object], horizon: int, fold_offset: int = 0) -> StackingConfig:
    model = config["stacking"]
    return StackingConfig(
        horizon=horizon, model_version=str(model["model_version"]),
        random_seed=int(model["random_seed"]) + fold_offset,
        regularization_c=float(model["regularization_c"]),
        max_iterations=int(model["max_iterations"]),
        anomaly_feature_name=("anomaly_score" if bool(model["include_anomaly_covariate"]) else None),
    )


def _crossfit_calibrator(frame: pd.DataFrame, source: str, method: str,
                         folds: list[list[int]], seed: int) -> np.ndarray:
    output = np.full(len(frame), np.nan)
    for fold_index, holdout in enumerate(folds):
        holdout_mask = frame.unit_id.isin(holdout).to_numpy()
        calibrator = ProbabilityCalibrator(method, seed=seed + fold_index).fit(
            frame.loc[~holdout_mask, source], frame.loc[~holdout_mask, "label"])
        output[holdout_mask] = calibrator.predict(frame.loc[holdout_mask, source])
    if not np.isfinite(output).all():
        raise RuntimeError("calibrator cross-fitting did not cover every row")
    return output


def calibrate_crossfitted(train: pd.DataFrame, config: dict[str, object], artifacts: Path):
    folds = grouped_unit_folds(train.unit_id.tolist(), folds=int(config["calibration"]["folds"]),
                               seed=int(config["calibration"]["seed"]))
    methods = [str(value) for value in config["calibration"]["methods"]]
    results: dict[str, object] = {}
    selected: dict[str, dict[int, str]] = {"simple": {}, "stacking": {}}
    calibrators: dict[tuple[str, int], ProbabilityCalibrator] = {}
    output = train.copy()
    for fusion, source in (("simple", "simple_raw"), ("stacking", "meta_raw")):
        results[fusion] = {}
        for horizon in HORIZONS:
            subset = output.horizon.eq(horizon)
            local = output.loc[subset].copy()
            candidates: dict[str, object] = {}
            candidate_scores: dict[str, np.ndarray] = {}
            for method in methods:
                scores = _crossfit_calibrator(local, source, method, folds,
                                              int(config["calibration"]["seed"]))
                metrics = evaluate_binary_probabilities(local.label, scores,
                    reliability_bins=int(config["evaluation"]["reliability_bins"]),
                    log_loss_epsilon=float(config["evaluation"]["log_loss_epsilon"]))
                candidates[method] = metrics
                candidate_scores[method] = scores
            calibrated_methods = [method for method in methods if method != "none"] or methods
            chosen = min(calibrated_methods, key=lambda method: (
                candidates[method]["log_loss"], candidates[method]["brier_score"], method))
            selected[fusion][horizon] = chosen
            results[fusion][str(horizon)] = {"candidates": candidates, "selected": chosen,
                                             "selection_rule": "minimum grouped-cross-fit log loss among Platt/isotonic, then Brier; none is a reference"}
            output.loc[subset, f"{fusion}_calibrated"] = candidate_scores[chosen]
            final = ProbabilityCalibrator(chosen, seed=int(config["calibration"]["seed"])).fit(
                local[source], local.label)
            final.save(artifacts / f"{fusion}_calibrator_h{horizon}.joblib")
            calibrators[(fusion, horizon)] = final
    return output, calibrators, selected, results


def _feature_records(engineered: pd.DataFrame, names: tuple[str, ...]) -> list[FeatureRecord]:
    matrix = engineered.loc[:, names].to_numpy(dtype=float)
    return [FeatureRecord(unit_id=str(int(unit)), cycle=int(cycle),
                          values=dict(zip(names, row, strict=True)))
            for unit, cycle, row in zip(engineered.unit_id, engineered.cycle, matrix, strict=True)]


def predict_base_artifacts(frame: pd.DataFrame, report_root: Path) -> pd.DataFrame:
    """Exercise the exact frozen inference route on a complete internal partition."""
    origins = _operational(frame)
    pieces: list[pd.DataFrame] = []
    classical_engineer = CausalTelemetryFeatures.load(
        report_root / "classical_ml/artifacts/causal_feature_engineer.json")
    classical_features = classical_engineer.transform_frame(frame).loc[origins.index]
    classical_records = _feature_records(classical_features, classical_engineer.feature_names)
    for algorithm, model_class in (("random_forest", RandomForestRiskModel),
                                    ("xgboost", XGBoostRiskModel)):
        for horizon in HORIZONS:
            model = model_class.load(report_root / f"classical_ml/artifacts/models/{algorithm}_h{horizon}.joblib")
            pieces.append(_risk_frame(model.predict_risk(classical_records, horizon=horizon),
                                      algorithm, origins, horizon))
    hazard_engineer = CausalTelemetryFeatures.load(
        report_root / "discrete_hazard/artifacts/causal_feature_engineer.json")
    hazard_features = hazard_engineer.transform_frame(frame).loc[origins.index]
    hazard_records = _feature_records(hazard_features, hazard_engineer.feature_names)
    hazard_model = DiscreteHazardRiskModel.load(report_root / "discrete_hazard/artifacts/model.joblib")
    for horizon in HORIZONS:
        pieces.append(_risk_frame(hazard_model.predict_risk(hazard_records, horizon=horizon),
                                  "discrete_hazard", origins, horizon))
    anomaly_engineer = CausalTelemetryFeatures.load(
        report_root / "anomaly_detection/artifacts/causal_feature_engineer.json")
    anomaly_features = anomaly_engineer.transform_frame(frame).loc[origins.index]
    anomaly_records = _feature_records(anomaly_features, anomaly_engineer.feature_names)
    detector = IsolationForestAnomalyDetector.load(
        report_root / "anomaly_detection/artifacts/isolation_forest.joblib")
    anomaly_predictions = detector.detect(anomaly_records)
    anomaly = pd.DataFrame({"unit_id": origins.unit_id.to_numpy(int),
        "cycle": origins.cycle.to_numpy(int), "RUL": origins.RUL.to_numpy(int),
        "anomaly_score": [item.anomaly_score for item in anomaly_predictions],
        "model_name": [item.model_name for item in anomaly_predictions],
        "model_version": [item.model_version for item in anomaly_predictions],
        "prediction_status": [item.prediction_status for item in anomaly_predictions],
        "input_validity": [item.input_validity for item in anomaly_predictions]})
    weibull_model = Weibull2Parameter.load(report_root / "weibull/artifacts/weibull_2p_model.json")
    weibull_parts = []
    for horizon in HORIZONS:
        risk = np.asarray([weibull_model.conditional_risk(float(age), horizon)
                           for age in origins.cycle], dtype=float)
        weibull_parts.append(pd.DataFrame({"unit_id": origins.unit_id.to_numpy(int),
            "cycle": origins.cycle.to_numpy(int), "horizon": horizon, "risk_score": risk,
            "prediction_status": "available", "input_validity": "valid"}))
    classical = pd.concat([piece for piece in pieces if piece.algorithm.isin(["random_forest", "xgboost"]).all()])
    hazard = pd.concat([piece for piece in pieces if piece.algorithm.eq("discrete_hazard").all()])
    return align_prediction_artifacts(classical, hazard, pd.concat(weibull_parts), anomaly,
                                      partition="inference")


def _risk_frame(predictions, algorithm: str, origins: pd.DataFrame, horizon: int) -> pd.DataFrame:
    return pd.DataFrame({"unit_id": origins.unit_id.to_numpy(int),
        "cycle": origins.cycle.to_numpy(int), "horizon": horizon,
        "risk_score": [item.risk_score for item in predictions],
        "prediction_status": [item.prediction_status for item in predictions],
        "input_validity": [item.input_validity for item in predictions],
        "label": origins.RUL.le(horizon).astype("int8").to_numpy(), "algorithm": algorithm})


def _apply_fusion(frame: pd.DataFrame, models: dict[int, LogisticStackingFusion],
                  calibrators: dict[tuple[str, int], ProbabilityCalibrator]) -> pd.DataFrame:
    output = frame.copy()
    for horizon in HORIZONS:
        selected = output.horizon.eq(horizon)
        output.loc[selected, "meta_raw"] = models[horizon].predict_frame(output.loc[selected])
        output.loc[selected, "stacking_calibrated"] = calibrators[("stacking", horizon)].predict(
            output.loc[selected, "meta_raw"])
        output.loc[selected, "simple_calibrated"] = calibrators[("simple", horizon)].predict(
            output.loc[selected, "simple_raw"])
    output["risk_score"] = output.stacking_calibrated
    output["survival_score"] = 1.0 - output.risk_score
    output["health_score"] = 100.0 * output.survival_score
    output["model_name"] = "fd001_logistic_probability_stacking"
    output["model_version"] = "1.0.0"
    output["prediction_status"] = "valid"
    output["input_validity"] = "valid"
    return output


def _probability_metrics(frame: pd.DataFrame, config: dict[str, object],
                         *, thresholds: AlertThresholds | None = None) -> dict[str, object]:
    result: dict[str, object] = {}
    for method, column in (("simple", "simple_calibrated"), ("stacking", "stacking_calibrated")):
        result[method] = {}
        for horizon in HORIZONS:
            part = frame.loc[frame.horizon.eq(horizon)]
            metrics = evaluate_binary_probabilities(part.label, part[column],
                reliability_bins=int(config["evaluation"]["reliability_bins"]),
                log_loss_epsilon=float(config["evaluation"]["log_loss_epsilon"]))
            if thresholds is not None:
                threshold = thresholds.critical if horizon == thresholds.critical_horizon else thresholds.alert
                metrics["classification"] = threshold_metrics(part.label, part[column], threshold=threshold)
            result[method][str(horizon)] = metrics
    return result


def select_alert_thresholds(validation: pd.DataFrame, config: dict[str, object]) -> tuple[AlertThresholds, dict[str, object]]:
    """Select an ordered experimental policy using validation only."""
    policy = config["alert_policy"]
    h30 = validation.loc[validation.horizon.eq(30)]
    h15 = validation.loc[validation.horizon.eq(15)]
    alert = _best_f1_threshold(h30.label.to_numpy(), h30.risk_score.to_numpy(),
                               min_precision=float(policy["alert_min_precision"]))
    attention = _recall_threshold(h30.label.to_numpy(), h30.risk_score.to_numpy(),
                                  target=float(policy["attention_min_recall"]), upper=alert)
    critical = _recall_threshold(h15.label.to_numpy(), h15.risk_score.to_numpy(),
                                 target=float(policy["critical_min_recall"]), lower=alert)
    thresholds = AlertThresholds(attention=attention, alert=alert, critical=critical,
        persistence_cycles=int(policy["persistence_cycles"]))
    evidence = {
        "partition": "validation", "criteria": {
            "attention": f"largest positive H30 threshold below alert with recall >= {policy['attention_min_recall']}; if infeasible, maximum attainable recall then largest threshold",
            "alert": f"maximum H30 F1 with precision >= {policy['alert_min_precision']}",
            "critical": f"largest H15 threshold above alert with recall >= {policy['critical_min_recall']}; if infeasible, maximum attainable recall then largest threshold",
            "persistence": f"{policy['persistence_cycles']} consecutive cycles before emitting a level",
        },
        "realized": {
            "attention_h30": threshold_metrics(h30.label, h30.risk_score, threshold=attention),
            "alert_h30": threshold_metrics(h30.label, h30.risk_score, threshold=alert),
            "critical_h15": threshold_metrics(h15.label, h15.risk_score, threshold=critical),
        }}
    return thresholds, evidence


def _candidate_thresholds(scores: np.ndarray) -> np.ndarray:
    return np.unique(np.concatenate(([0.0], np.asarray(scores, float), [1.0])))


def _best_f1_threshold(labels: np.ndarray, scores: np.ndarray, *, min_precision: float) -> float:
    rows = [threshold_metrics(labels, scores, threshold=float(value))
            for value in _candidate_thresholds(scores)]
    eligible = [row for row in rows if row["precision"] >= min_precision and 0 < row["threshold"] < 1]
    if not eligible:
        eligible = [row for row in rows if 0 < row["threshold"] < 1]
    return float(max(eligible, key=lambda row: (row["f1"], row["recall"], row["threshold"]))["threshold"])


def _recall_threshold(labels: np.ndarray, scores: np.ndarray, *, target: float,
                      lower: float = 0.0, upper: float = 1.0) -> float:
    epsilon = 1e-9
    rows = [threshold_metrics(labels, scores, threshold=float(value))
            for value in _candidate_thresholds(scores) if lower + epsilon < value < upper - epsilon]
    eligible = [row for row in rows if row["recall"] >= target]
    if not eligible:
        if not rows:
            raise RuntimeError("no positive validation threshold satisfies the ordering constraint")
        best_recall = max(row["recall"] for row in rows)
        eligible = [row for row in rows if row["recall"] == best_recall]
    return float(max(eligible, key=lambda row: row["threshold"])["threshold"])


def _unit_metrics(frame: pd.DataFrame, thresholds: AlertThresholds, partition: str) -> pd.DataFrame:
    rows = []
    for horizon, threshold in ((15, thresholds.critical), (30, thresholds.alert)):
        part = frame.loc[frame.horizon.eq(horizon),
                         ["unit_id", "cycle", "risk_score", "label", "RUL"]]
        metrics = alert_metrics_by_unit(part, threshold=threshold,
                                        persistence_cycles=thresholds.persistence_cycles)
        metrics["partition"], metrics["horizon"], metrics["threshold"] = partition, horizon, threshold
        rows.append(metrics)
    return pd.concat(rows, ignore_index=True)


def _horizon_coherence(frame: pd.DataFrame) -> dict[str, object]:
    pivot = frame.pivot(index=["unit_id", "cycle"], columns="horizon", values="risk_score")
    if not set(HORIZONS) <= set(pivot.columns) or pivot.loc[:, list(HORIZONS)].isna().any().any():
        raise ValueError("horizon coherence requires aligned H15/H30 predictions")
    excess = pivot[15] - pivot[30]
    violations = excess.gt(1e-12)
    return {"origins": len(pivot), "violations": int(violations.sum()),
            "fraction": float(violations.mean()),
            "maximum_excess": float(excess.loc[violations].max()) if violations.any() else 0.0}


def _write_policy(path: Path, thresholds: AlertThresholds, evidence: dict[str, object]) -> None:
    lines = ["# Generated from validation only; experimental demonstrator policy.",
             "policy_version = \"1.0.0\"", "source_partition = \"validation\"",
             "primary_fusion = \"stacking\"", "",
             "[thresholds]", f"attention = {thresholds.attention:.17g}",
             f"alert = {thresholds.alert:.17g}", f"critical = {thresholds.critical:.17g}", "",
             "[horizons]", f"attention = {thresholds.attention_horizon}",
             f"alert = {thresholds.alert_horizon}", f"critical = {thresholds.critical_horizon}", "",
             "[persistence]", f"cycles = {thresholds.persistence_cycles}", "",
             "[interpretation]",
             "statement = \"Experimental FD001 demonstrator levels; not real aeronautical limits.\""]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _load_policy(path: Path) -> AlertThresholds:
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    return AlertThresholds(attention=float(payload["thresholds"]["attention"]),
        alert=float(payload["thresholds"]["alert"]), critical=float(payload["thresholds"]["critical"]),
        attention_horizon=int(payload["horizons"]["attention"]),
        alert_horizon=int(payload["horizons"]["alert"]),
        critical_horizon=int(payload["horizons"]["critical"]),
        persistence_cycles=int(payload["persistence"]["cycles"]))


def run_fusion_development(processed: Path = Path("data/processed/fd001"),
                           config_path: Path = Path("configs/fusion.toml"),
                           report_root: Path = Path("reports")) -> dict[str, object]:
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    train, validation, manifest = load_fusion_development(processed)
    root, artifacts = report_root / "fusion", report_root / "fusion/artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    if (root / "test_evaluation_receipt.json").exists():
        raise RuntimeError("this frozen phase already evaluated test_internal")
    weibull_oof, weibull_folds = generate_weibull_oof(
        train, report_root / "classical_ml/artifacts/fold_manifest.json",
        artifacts / "weibull_train_oof_predictions.parquet")
    train_inputs = align_prediction_artifacts(
        pd.read_parquet(report_root / "classical_ml/artifacts/train_oof_predictions.parquet"),
        pd.read_parquet(report_root / "discrete_hazard/artifacts/train_oof_predictions.parquet"),
        weibull_oof,
        pd.read_parquet(report_root / "anomaly_detection/artifacts/train_oof_anomaly_scores.parquet"),
        partition="train_oof")
    validation_inputs = align_prediction_artifacts(
        pd.read_parquet(report_root / "classical_ml/artifacts/validation_predictions.parquet"),
        pd.read_parquet(report_root / "discrete_hazard/artifacts/validation_predictions.parquet"),
        pd.read_parquet(report_root / "weibull/artifacts/validation_predictions.parquet"),
        pd.read_parquet(report_root / "anomaly_detection/artifacts/validation_anomaly_scores.parquet"),
        partition="validation")
    train_inputs.to_parquet(artifacts / "train_oof_inputs.parquet", index=False)
    validation_inputs.to_parquet(artifacts / "validation_inputs.parquet", index=False)
    train_meta, models, meta_folds = _crossfit_meta(train_inputs, config, artifacts)
    train_fusion, calibrators, selected, calibration = calibrate_crossfitted(
        train_meta, config, artifacts)
    train_fusion["risk_score"] = train_fusion.stacking_calibrated
    train_fusion["survival_score"] = 1.0 - train_fusion.risk_score
    train_fusion["health_score"] = 100.0 * train_fusion.survival_score
    train_fusion["prediction_status"] = "valid"
    train_fusion["input_validity"] = "valid"
    train_fusion.to_parquet(artifacts / "train_oof_fusion_predictions.parquet", index=False)
    validation_fusion = _apply_fusion(validation_inputs, models, calibrators)
    validation_fusion.to_parquet(artifacts / "validation_fusion_predictions.parquet", index=False)

    # Exercise all serialized base models and preprocessors on validation before freeze.
    regenerated = predict_base_artifacts(validation, report_root)
    compare_columns = [*RISK_COMPONENTS, "anomaly_score", "simple_raw", "disagreement", "label", "RUL"]
    left = validation_inputs.sort_values(["unit_id", "cycle", "horizon"])[compare_columns].reset_index(drop=True)
    right = regenerated.sort_values(["unit_id", "cycle", "horizon"])[compare_columns].reset_index(drop=True)
    inference_check = {column: bool(np.allclose(left[column], right[column], rtol=0, atol=1e-12))
                       for column in compare_columns}
    if not all(inference_check.values()):
        raise RuntimeError(f"frozen inference route differs from validation artifacts: {inference_check}")

    thresholds, threshold_evidence = select_alert_thresholds(validation_fusion, config)
    policy_path = Path("configs/fusion_alert_policy.toml")
    _write_policy(policy_path, thresholds, threshold_evidence)
    alert_levels = assign_alert_levels(validation_fusion[["unit_id", "cycle", "horizon", "risk_score"]], thresholds)
    alert_levels.to_parquet(artifacts / "validation_alert_levels.parquet", index=False)
    unit_metrics = _unit_metrics(validation_fusion, thresholds, "validation")
    unit_metrics.to_parquet(artifacts / "validation_metrics_by_unit.parquet", index=False)
    metrics = {"train_oof": _probability_metrics(train_fusion, config),
               "validation": _probability_metrics(validation_fusion, config, thresholds=thresholds),
               "cross_horizon_coherence": {
                   "train_oof": _horizon_coherence(train_fusion),
                   "validation": _horizon_coherence(validation_fusion),
               },
               "calibration_selection": calibration,
               "calibration_selected": {name: {str(k): v for k, v in values.items()}
                                          for name, values in selected.items()},
               "threshold_selection": threshold_evidence,
               "test_internal": {"status": "not_read_before_freeze"}}
    _write_json(root / "metrics.json", metrics)
    audit_paths = [
        report_root / "classical_ml/artifacts/train_oof_predictions.parquet",
        report_root / "discrete_hazard/artifacts/train_oof_predictions.parquet",
        report_root / "anomaly_detection/artifacts/train_oof_anomaly_scores.parquet",
        report_root / "classical_ml/artifacts/validation_predictions.parquet",
        report_root / "discrete_hazard/artifacts/validation_predictions.parquet",
        report_root / "weibull/artifacts/validation_predictions.parquet",
        report_root / "anomaly_detection/artifacts/validation_anomaly_scores.parquet",
    ]
    audit = {"train_rows_per_horizon": int(len(train_inputs) / 2),
             "validation_rows_per_horizon": int(len(validation_inputs) / 2),
             "train_units": int(train_inputs.unit_id.nunique()),
             "validation_units": int(validation_inputs.unit_id.nunique()),
             "aligned_missing_values": int(train_inputs.isna().sum().sum() + validation_inputs.isna().sum().sum()),
             "duplicate_keys": int(train_inputs.duplicated(["unit_id", "cycle", "horizon"]).sum()),
             "weibull_refit_by_fold": weibull_folds, "meta_folds": meta_folds,
             "anomaly_role": "separate stacking covariate; never averaged as probability",
             "input_sha256": {path.as_posix(): _sha(path) for path in audit_paths},
             "test_internal_read": False, "official_test_read": False}
    _write_json(root / "oof_audit.json", audit)
    artifact_paths = [artifacts / f"stacking_h{h}.joblib" for h in HORIZONS] + [
        artifacts / f"{method}_calibrator_h{h}.joblib"
        for method in ("simple", "stacking") for h in HORIZONS]
    freeze = {"state": "frozen", "phase_version": "0.9.0", "primary_fusion": PRIMARY_METHOD,
        "horizons": list(HORIZONS), "calibration_selected": metrics["calibration_selected"],
        "thresholds": {**thresholds.__dict__}, "configuration_sha256": _sha(config_path),
        "policy_sha256": _sha(policy_path), "artifact_sha256": {path.as_posix(): _sha(path) for path in artifact_paths},
        "development_input_sha256": audit["input_sha256"], "validation_inference_check": inference_check,
        "test_internal_read": False, "official_test_read": False,
        "selection_complete": True, "post_test_changes_allowed": False}
    _write_json(root / "freeze_manifest.json", freeze)
    card = {"model_name": "fd001_logistic_probability_stacking", "model_version": "1.0.0",
        "training_data_manifest": manifest, "configuration": config, "base_probability_features": list(RISK_COMPONENTS),
        "auxiliary_covariates": ["anomaly_score"],
        "anomaly_semantics": "analytical abnormality indicator; not probability and not part of arithmetic mean",
        "input_contract": "aligned base OOF probabilities and OOF anomaly score by unit_id/cycle/horizon",
        "output_contract": "risk probability with explicit horizon/status; survival=1-risk; health=100*survival",
        "calibration": metrics["calibration_selected"], "thresholds": freeze["thresholds"],
        "assumptions": ["ASM022", "ASM023", "ASM024", "ASM025"],
        "limitations": ["FD001 development population only", "validation reused for threshold policy",
                        "shared dependencies prevent independence claims", "test_internal is one frozen phase evaluation"],
        "dependencies": {"python": platform.python_version(), **{name: version(name) for name in
            ("numpy", "pandas", "scikit-learn", "joblib")}},
        "artifact_sha256": freeze["artifact_sha256"], "test_internal_read": False,
        "official_test_read": False}
    _write_json(root / "model_card.json", card)
    _plot_reliability(validation_fusion, root / "figures/reliability_validation.png", config)
    _write_report(report_root / "fusion_report.md", metrics, thresholds, audit, None)
    return {"metrics": metrics, "thresholds": thresholds.__dict__, "audit": audit,
            "freeze_manifest": str(root / "freeze_manifest.json")}


def evaluate_frozen_test(processed: Path = Path("data/processed/fd001"),
                         config_path: Path = Path("configs/fusion.toml"),
                         report_root: Path = Path("reports")) -> dict[str, object]:
    root, artifacts = report_root / "fusion", report_root / "fusion/artifacts"
    gate = FrozenEvaluationGate(root / "freeze_manifest.json", root / "test_evaluation_receipt.json")
    freeze = gate.authorize_single_read()
    manifest = _read_manifest(processed)
    test_path = processed / "test_internal.parquet"
    test = pd.read_parquet(test_path)
    receipt = {"status": "in_progress", "read_count": 1, "partition": "test_internal",
               "rows_read": len(test), "units_read": int(test.unit_id.nunique()),
               "freeze_manifest_sha256": _sha(root / "freeze_manifest.json"),
               "test_internal_sha256": _sha(test_path), "official_test_read": False}
    _write_json(root / "test_evaluation_receipt.json", receipt)
    _validate_partition(test, "test_internal", manifest)
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    policy = _load_policy(Path("configs/fusion_alert_policy.toml"))
    models = {h: LogisticStackingFusion.load(artifacts / f"stacking_h{h}.joblib") for h in HORIZONS}
    calibrators = {(method, h): ProbabilityCalibrator.load(
        artifacts / f"{method}_calibrator_h{h}.joblib")
        for method in ("simple", "stacking") for h in HORIZONS}
    test_inputs = predict_base_artifacts(test, report_root)
    test_fusion = _apply_fusion(test_inputs, models, calibrators)
    test_fusion.to_parquet(artifacts / "test_internal_fusion_predictions.parquet", index=False)
    levels = assign_alert_levels(test_fusion[["unit_id", "cycle", "horizon", "risk_score"]], policy)
    levels.to_parquet(artifacts / "test_internal_alert_levels.parquet", index=False)
    unit_metrics = _unit_metrics(test_fusion, policy, "test_internal")
    unit_metrics.to_parquet(artifacts / "test_internal_metrics_by_unit.parquet", index=False)
    metrics = json.loads((root / "metrics.json").read_text(encoding="utf-8"))
    metrics["test_internal"] = _probability_metrics(test_fusion, config, thresholds=policy)
    metrics["cross_horizon_coherence"]["test_internal"] = _horizon_coherence(test_fusion)
    metrics["test_internal"]["evaluation_protocol"] = {
        "frozen_manifest": str(root / "freeze_manifest.json"), "read_count": 1,
        "models_calibrators_thresholds_changed_after_read": False,
        "used_for_selection": False}
    _write_json(root / "metrics.json", metrics)
    _plot_reliability(test_fusion, root / "figures/reliability_test_internal.png", config)
    receipt.update({"status": "complete", "prediction_rows": len(test_fusion),
                    "metrics_sha256": _sha(root / "metrics.json"),
                    "test_predictions_sha256": _sha(artifacts / "test_internal_fusion_predictions.parquet"),
                    "models_calibrators_thresholds_changed_after_read": False})
    _write_json(root / "test_evaluation_receipt.json", receipt)
    card = json.loads((root / "model_card.json").read_text(encoding="utf-8"))
    card["frozen_test_evaluation"] = {"partition": "test_internal", "read_count": 1,
        "used_for_selection": False, "metrics": metrics["test_internal"]}
    card["test_internal_read"] = True
    _write_json(root / "model_card.json", card)
    _write_report(report_root / "fusion_report.md", metrics, policy,
                  json.loads((root / "oof_audit.json").read_text(encoding="utf-8")), receipt)
    return metrics["test_internal"]


def _plot_reliability(frame: pd.DataFrame, path: Path, config: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for axis, horizon in zip(axes, HORIZONS, strict=True):
        part = frame.loc[frame.horizon.eq(horizon)]
        for label, column in (("simple", "simple_calibrated"), ("stacking", "stacking_calibrated")):
            curve = evaluate_binary_probabilities(part.label, part[column],
                reliability_bins=int(config["evaluation"]["reliability_bins"]))["reliability_curve"]
            axis.plot([row["mean_predicted"] for row in curve],
                      [row["observed_frequency"] for row in curve], marker="o", label=label)
        axis.plot([0, 1], [0, 1], "--", color="black", linewidth=.8)
        axis.set(title=f"H={horizon}", xlabel="Mean predicted", ylabel="Observed frequency")
        axis.legend()
    fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig)


def _write_report(path: Path, metrics: dict[str, object], thresholds: AlertThresholds,
                  audit: dict[str, object], receipt: dict[str, object] | None) -> None:
    lines = ["# Fusão probabilística e política inicial de alertas — FD001", "",
        "## Protocolo sem leakage", "",
        "RF, XGBoost e hazard usam previsões OOF existentes; a Weibull é reajustada dentro de cada fold por unidade. "
        "O stacking logístico é treinado apenas nessas previsões OOF. Sua saída de treino é novamente cross-fitted por `unit_id`. "
        "Platt e isotonic são comparados por cross-fitting agrupado; o calibrador final aprende apenas de scores cross-fitted. "
        "Validation escolhe thresholds depois de modelos e calibradores congelados. `test_internal` é aberto uma única vez após o manifesto de freeze.", "",
        "O ensemble simples é a média das quatro probabilidades comparáveis. `anomaly_score` entra somente como covariável do stacking e mantém semântica de anormalidade. "
        "`disagreement=max(risk)-min(risk)` entre os quatro riscos; é divergência entre modelos, não intervalo de confiança.", "",
        "## Auditoria OOF", "",
        f"Foram alinhadas {audit['train_rows_per_horizon']} origens de {audit['train_units']} unidades por horizonte no treino e "
        f"{audit['validation_rows_per_horizon']} origens de {audit['validation_units']} unidades por horizonte em validation. "
        f"Ausências alinhadas: {audit['aligned_missing_values']}; chaves duplicadas: {audit['duplicate_keys']}.", "",
        "Platt foi selecionado para ensemble simples e stacking em H15/H30 porque apresentou o menor log loss "
        "cross-fitted entre Platt e isotonic; a opção sem calibração permaneceu referência. Isotonic obteve Brier "
        "ligeiramente menor em alguns casos, mas gerou extremos 0/1 e log loss pior.", "",
        "## Calibração e métricas por linha", ""]
    for partition in ("train_oof", "validation", "test_internal"):
        if partition not in metrics or "stacking" not in metrics[partition]:
            continue
        lines += [f"### {partition}", "", "| Método | H | Brier | Log loss | ROC AUC | PR AUC | Precision | Recall | F1 |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for method in ("simple", "stacking"):
            for horizon in HORIZONS:
                item = metrics[partition][method][str(horizon)]
                cls = item.get("classification", {})
                lines.append(f"| {method} | {horizon} | {item['brier_score']:.6f} | {item['log_loss']:.6f} | "
                             f"{item['roc_auc']:.6f} | {item['pr_auc_average_precision']:.6f} | "
                             f"{cls.get('precision', float('nan')):.6f} | {cls.get('recall', float('nan')):.6f} | {cls.get('f1', float('nan')):.6f} |")
        lines.append("")
    coherence = metrics.get("cross_horizon_coherence", {})
    if coherence:
        lines += ["## Coerência entre horizontes", "",
                  "| Partição | Origens | Violações p15>p30 | Fração | Excesso máximo |",
                  "| --- | ---: | ---: | ---: | ---: |"]
        for partition in ("train_oof", "validation", "test_internal"):
            if partition in coherence:
                item = coherence[partition]
                lines.append(f"| {partition} | {item['origins']} | {item['violations']} | "
                             f"{item['fraction']:.4%} | {item['maximum_excess']:.6f} |")
        lines += ["", "Os modelos e calibradores são separados por horizonte, por isso a coerência não é garantida. "
                  "As violações permanecem visíveis; nenhuma correção pós-teste foi aplicada.", ""]
    lines += ["## Política inicial", "",
        f"Thresholds validation: atenção={thresholds.attention:.6f} em H30; alerta={thresholds.alert:.6f} em H30; "
        f"crítico={thresholds.critical:.6f} em H15. Um nível é emitido após {thresholds.persistence_cycles} ciclos consecutivos. "
        "São parâmetros experimentais do demonstrador, não limites aeronáuticos reais.", "",
        "Métricas por unidade incluem primeiro alerta, antecedência, episódios/duração de falsos alertas, persistência, maior sequência e fração de vida. "
        "Os Parquets ficam em `reports/fusion/artifacts/*_metrics_by_unit.parquet`.", "",
        "## Estados e dependências", "",
        "Com todos os componentes válidos, a saída é `valid`. A média simples pode operar como `degraded` com ao menos dois riscos comparáveis; "
        "o stacking exige todas as covariáveis e fica `unavailable` se uma faltar. Entrada inválida ou antiga torna a saída indisponível; ausência nunca vira risco zero.", "",
        "Telemetria, preprocessing, features, treino, alvo, runtime, horizonte, thresholds e serialização são dependências comuns. "
        "A diversidade algorítmica não sustenta alegação de independência.", "",
        "![Reliability validation](fusion/figures/reliability_validation.png)"]
    lines += ["", "## Resumo temporal por unidade", "",
              "| Partição | H | Unidades alertadas | Lead time mediano | Lead time mínimo | Episódios falsos | Duração falsa total | Fração média da vida sob alerta |",
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for partition in ("validation", "test_internal"):
        unit_path = path.parent / f"fusion/artifacts/{partition}_metrics_by_unit.parquet"
        if unit_path.exists():
            unit_metrics = pd.read_parquet(unit_path)
            for horizon in HORIZONS:
                part = unit_metrics.loc[unit_metrics.horizon.eq(horizon)]
                lines.append(f"| {partition} | {horizon} | {part.first_alert_cycle.notna().sum()} | "
                             f"{part.lead_time.median():.1f} | {part.lead_time.min():.1f} | "
                             f"{part.false_alert_episode_count.sum()} | {part.false_alert_episode_duration.sum()} | "
                             f"{part.fraction_life_under_alert.mean():.4%} |")
    if receipt and receipt.get("status") == "complete":
        lines += ["", "![Reliability test_internal](fusion/figures/reliability_test_internal.png)", "",
                  f"Avaliação congelada: `test_internal`, {receipt['rows_read']} linhas brutas, {receipt['units_read']} unidades, "
                  f"{receipt['prediction_rows']} previsões H15/H30, uma leitura registrada. Nenhum resultado foi usado para nova seleção."]
    else:
        lines += ["", "`test_internal` ainda não havia sido lido quando este relatório de desenvolvimento foi gerado."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("development", "test"), required=True)
    parser.add_argument("--config", type=Path, default=Path("configs/fusion.toml"))
    args = parser.parse_args()
    result = (run_fusion_development(config_path=args.config) if args.stage == "development"
              else evaluate_frozen_test(config_path=args.config))
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
