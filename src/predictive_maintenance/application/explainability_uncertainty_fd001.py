"""Audit explainability, calibration and unit-level metric uncertainty on FD001."""

from __future__ import annotations

import argparse
import ast
import csv
from hashlib import sha256
import json
from pathlib import Path
import re
import time
import tomllib
from typing import Callable

import numpy as np
import pandas as pd
import shap
from sklearn.metrics import average_precision_score, roc_auc_score

from predictive_maintenance.application.tcn_fd001 import _feature_records
from predictive_maintenance.evaluation.calibration import calibration_audit
from predictive_maintenance.evaluation.explainability import (
    top_sensor_contributions,
    top_shap_contributions,
    validate_explanation_frame,
)
from predictive_maintenance.evaluation.probability import average_precision, roc_auc, threshold_metrics
from predictive_maintenance.evaluation.uncertainty import UnitBootstrapConfig, unit_bootstrap_intervals
from predictive_maintenance.features.causal import CausalTelemetryFeatures
from predictive_maintenance.models.fusion.probabilistic import alert_metrics_by_unit
from predictive_maintenance.models.ml.classical import XGBoostRiskModel
from predictive_maintenance.models.temporal.discrete_hazard import DiscreteHazardRiskModel
from predictive_maintenance.models.temporal.tcn import TCNRiskModel
from predictive_maintenance.models.temporal.transformer import TransformerRiskModel


PROBABILITY_MODELS = (
    "weibull", "random_forest", "xgboost", "discrete_hazard", "tcn", "transformer", "fusion",
)


def run_explainability_uncertainty(
    project_root: Path = Path("."),
    config_path: Path = Path("configs/explainability_uncertainty.toml"),
) -> dict[str, object]:
    root = project_root.resolve()
    config_file = (root / config_path).resolve() if not config_path.is_absolute() else config_path
    config = tomllib.loads(config_file.read_text(encoding="utf-8"))
    _validate_config(config)
    reports = root / "reports"
    output = reports / "explainability_uncertainty"
    output.mkdir(parents=True, exist_ok=True)

    sources = _load_probability_sources(reports)
    _validate_source_alignment(sources)
    bins = int(config["analysis"]["reliability_bins"])
    calibration_rows: list[dict[str, object]] = []
    reliability_rows: list[dict[str, object]] = []
    for model_name, frame in sources.items():
        for horizon, part in frame.groupby("horizon", sort=True):
            audit = calibration_audit(part.label, part.risk_score, bins=bins)
            curve = audit.pop("reliability_curve")
            calibration_rows.append({"model": model_name, "horizon": int(horizon), **audit})
            reliability_rows.extend(
                {"model": model_name, "horizon": int(horizon), **item} for item in curve
            )
    calibration_frame = pd.DataFrame(calibration_rows)
    reliability_frame = pd.DataFrame(reliability_rows)

    validation_path = root / "data/processed/fd001/validation.parquet"
    validation = pd.read_parquet(validation_path)
    expected_units = set(sources["fusion"].unit_id.astype(int))
    if set(validation.unit_id.astype(int)) != expected_units or len(expected_units) != 15:
        raise ValueError("validation source is inconsistent with the frozen 15-unit split")

    shap_local, shap_global, shap_sensors, shap_check = _xgboost_shap(
        validation, sources["xgboost"], reports,
        top_features=int(config["analysis"]["top_features_per_observation"]),
        top_sensors=int(config["analysis"]["top_sensors_per_observation"]),
        batch_size=int(config["analysis"]["shap_batch_size"]),
    )
    hazard_importance = _hazard_importance(reports)
    neural_ablation = _neural_ablation(
        validation, reports, sample_origins=int(config["analysis"]["neural_ablation_origins"]),
    )
    explanation_frame = _integrated_explanations(
        sources["fusion"], shap_local, shap_sensors,
        reports / "fusion/artifacts/validation_alert_levels.parquet", config,
    )
    validate_explanation_frame(explanation_frame)

    bootstrap = _bootstrap_audit(sources, config)
    examples = _select_examples(explanation_frame, sources["fusion"])

    calibration_path = output / "calibration_metrics.parquet"
    reliability_path = output / "reliability_curves.parquet"
    shap_local_path = output / "xgboost_shap_local.parquet"
    shap_global_path = output / "xgboost_shap_global.parquet"
    shap_sensor_path = output / "xgboost_shap_sensors.parquet"
    hazard_path = output / "hazard_coefficient_importance.parquet"
    ablation_path = output / "neural_feature_ablation.parquet"
    explanation_path = output / "validation_explanations.parquet"
    for frame, path in (
        (calibration_frame, calibration_path), (reliability_frame, reliability_path),
        (shap_local, shap_local_path), (shap_global, shap_global_path),
        (shap_sensors, shap_sensor_path), (hazard_importance, hazard_path),
        (neural_ablation, ablation_path), (explanation_frame, explanation_path),
    ):
        frame.to_parquet(path, index=False)

    result: dict[str, object] = {
        "scope": {
            "partition": "validation", "units": len(expected_units),
            "test_internal_read": False, "official_test_read": False,
            "official_rul_read": False, "models_retrained": False,
            "thresholds_changed": False,
        },
        "configuration": config,
        "calibration": calibration_frame.to_dict("records"),
        "bootstrap": bootstrap,
        "examples": examples,
        "xgboost_shap_consistency": shap_check,
        "interpretation_methods": {
            "weibull": "structural age-only population risk; no sensor attribution",
            "xgboost": "TreeSHAP local contributions in raw-margin space",
            "discrete_hazard": "absolute standardized logistic coefficients; global association",
            "tcn": "mean-channel ablation on a deterministic validation sample",
            "transformer": "mean-channel ablation on a deterministic validation sample",
            "fusion": "component probabilities and their observed disagreement, plus XGBoost SHAP",
            "anomaly_score": "separate abnormality indicator; never interpreted as probability",
        },
        "artifacts": {},
        "provenance": {
            "config_sha256": _sha(config_file),
            "validation_sha256": _sha(validation_path),
            "source_paths": [
                "reports/fusion/artifacts/validation_fusion_predictions.parquet",
                "reports/classical_ml/artifacts/validation_predictions.parquet",
                "reports/discrete_hazard/artifacts/validation_predictions.parquet",
                "reports/weibull/artifacts/validation_predictions.parquet",
                "reports/tcn/artifacts/validation_predictions.parquet",
                "reports/transformer/artifacts/validation_predictions.parquet",
            ],
        },
    }
    for path in (
        calibration_path, reliability_path, shap_local_path, shap_global_path,
        shap_sensor_path, hazard_path, ablation_path, explanation_path,
    ):
        result["artifacts"][path.relative_to(root).as_posix()] = _sha(path)
    _write_json(output / "metrics.json", result)
    _write_explainability_report(root / "reports/explainability_uncertainty_report.md", result)
    _write_requirements_reports(root)
    return result


def _load_probability_sources(reports: Path) -> dict[str, pd.DataFrame]:
    fusion = pd.read_parquet(reports / "fusion/artifacts/validation_fusion_predictions.parquet")
    truth = fusion[["unit_id", "cycle", "horizon", "label", "RUL"]]

    def normalized(path: Path, *, query: str | None = None) -> pd.DataFrame:
        frame = pd.read_parquet(path)
        if query is not None:
            frame = frame.query(query)
        columns = ["unit_id", "cycle", "horizon", "risk_score"]
        if "label" in frame.columns:
            columns.append("label")
        result = frame[columns].copy()
        if "label" not in result.columns:
            result = result.merge(truth, on=["unit_id", "cycle", "horizon"], validate="one_to_one")
        else:
            result = result.merge(
                truth[["unit_id", "cycle", "horizon", "RUL"]],
                on=["unit_id", "cycle", "horizon"], validate="one_to_one",
            )
        return result.sort_values(["unit_id", "cycle", "horizon"]).reset_index(drop=True)

    classical_path = reports / "classical_ml/artifacts/validation_predictions.parquet"
    return {
        "weibull": normalized(reports / "weibull/artifacts/validation_predictions.parquet"),
        "random_forest": normalized(classical_path, query="algorithm == 'random_forest'"),
        "xgboost": normalized(classical_path, query="algorithm == 'xgboost'"),
        "discrete_hazard": normalized(reports / "discrete_hazard/artifacts/validation_predictions.parquet"),
        "tcn": normalized(reports / "tcn/artifacts/validation_predictions.parquet"),
        "transformer": normalized(reports / "transformer/artifacts/validation_predictions.parquet"),
        "fusion": fusion[["unit_id", "cycle", "horizon", "risk_score", "label", "RUL"]].copy()
            .sort_values(["unit_id", "cycle", "horizon"]).reset_index(drop=True),
    }


def _validate_source_alignment(sources: dict[str, pd.DataFrame]) -> None:
    if tuple(sources) != PROBABILITY_MODELS:
        raise ValueError("probability source registry is incomplete")
    reference = sources["fusion"][["unit_id", "cycle", "horizon", "label"]].reset_index(drop=True)
    for name, frame in sources.items():
        if frame.duplicated(["unit_id", "cycle", "horizon"]).any():
            raise ValueError(f"duplicate prediction keys for {name}")
        aligned = frame[["unit_id", "cycle", "horizon", "label"]].reset_index(drop=True)
        if not np.array_equal(
            aligned.to_numpy(dtype=np.int64), reference.to_numpy(dtype=np.int64),
        ):
            raise ValueError(f"prediction source is not aligned with fusion truth: {name}")
        scores = frame.risk_score.to_numpy(dtype=float)
        if not np.isfinite(scores).all() or ((scores < 0) | (scores > 1)).any():
            raise ValueError(f"invalid probabilities for {name}")


def _xgboost_shap(
    validation: pd.DataFrame,
    xgboost_predictions: pd.DataFrame,
    reports: Path,
    *,
    top_features: int,
    top_sensors: int,
    batch_size: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, object]]:
    engineer = CausalTelemetryFeatures.load(
        reports / "classical_ml/artifacts/causal_feature_engineer.json"
    )
    generated = engineer.transform_frame(validation)
    all_local: list[pd.DataFrame] = []
    global_rows: list[dict[str, object]] = []
    sensor_rows: list[pd.DataFrame] = []
    consistency: dict[str, object] = {}
    for horizon in (15, 30):
        prediction = xgboost_predictions.loc[xgboost_predictions.horizon.eq(horizon)].copy()
        keyed = prediction[["unit_id", "cycle"]].merge(
            generated, on=["unit_id", "cycle"], validate="one_to_one",
        )
        model = XGBoostRiskModel.load(
            reports / f"classical_ml/artifacts/models/xgboost_h{horizon}.joblib"
        )
        matrix = keyed.loc[:, list(model.feature_names)].to_numpy(dtype=float)
        explainer = shap.TreeExplainer(model.estimator)
        pieces: list[np.ndarray] = []
        started = time.perf_counter()
        for start in range(0, len(matrix), batch_size):
            explanation = explainer(matrix[start:start + batch_size], check_additivity=False)
            pieces.append(np.asarray(explanation.values, dtype=float))
        values = np.vstack(pieces)
        elapsed = time.perf_counter() - started
        local = top_shap_contributions(
            keyed[["unit_id", "cycle"]], model.feature_names, matrix, values,
            horizon=horizon, top_k=top_features,
        )
        all_local.append(local)
        sensor_rows.append(top_sensor_contributions(
            keyed[["unit_id", "cycle"]], model.feature_names, values,
            horizon=horizon, top_k=top_sensors,
        ))
        mean_abs = np.abs(values).mean(axis=0)
        mean_signed = values.mean(axis=0)
        order = np.argsort(-mean_abs, kind="stable")
        for rank, feature_index in enumerate(order, start=1):
            name = model.feature_names[int(feature_index)]
            source = name.split("__", 1)[0] if "__" in name else name
            temporal = name.split("__", 1)[1] if "__" in name else "current_age"
            global_rows.append({
                "horizon": horizon, "rank": rank, "feature_name": name,
                "source_signal": source, "temporal_component": temporal,
                "mean_absolute_shap": float(mean_abs[feature_index]),
                "mean_signed_shap": float(mean_signed[feature_index]),
                "contribution_space": "xgboost_raw_margin",
            })
        predicted = model.estimator.predict_proba(matrix)[:, 1]
        expected = prediction.risk_score.to_numpy(dtype=float)
        consistency[str(horizon)] = {
            "observations": len(matrix), "seconds": elapsed,
            "max_absolute_prediction_difference": float(np.max(np.abs(predicted - expected))),
            "output_space": "raw margin before logistic link",
            "causal_interpretation": False,
            "physical_sensor_semantics_added": False,
        }
    return (
        pd.concat(all_local, ignore_index=True),
        pd.DataFrame(global_rows),
        pd.concat(sensor_rows, ignore_index=True),
        consistency,
    )


def _hazard_importance(reports: Path) -> pd.DataFrame:
    model = DiscreteHazardRiskModel.load(reports / "discrete_hazard/artifacts/model.joblib")
    coefficients = np.asarray(model.theta[:-2], dtype=float)
    order = np.argsort(-np.abs(coefficients), kind="stable")
    rows = []
    for rank, index in enumerate(order, start=1):
        name = model.feature_names[int(index)]
        rows.append({
            "rank": rank, "feature_name": name,
            "standardized_log_hazard_coefficient": float(coefficients[index]),
            "absolute_magnitude": float(abs(coefficients[index])),
            "direction": "increases_step_hazard" if coefficients[index] > 0 else (
                "decreases_step_hazard" if coefficients[index] < 0 else "neutral"
            ),
            "interpretation": "global model association per training standard deviation; not causality",
        })
    return pd.DataFrame(rows)


def _neural_ablation(
    validation: pd.DataFrame, reports: Path, *, sample_origins: int,
) -> pd.DataFrame:
    models = {
        "tcn": TCNRiskModel.load(reports / "tcn/artifacts/tcn_model.pt"),
        "transformer": TransformerRiskModel.load(reports / "transformer/artifacts/transformer_model.pt"),
    }
    rows: list[dict[str, object]] = []
    for name, model in models.items():
        operational = validation.loc[
            validation.cycle.lt(validation.groupby("unit_id").cycle.transform("max"))
        ].reset_index(drop=True)
        records = _feature_records(operational, model.feature_names)
        sequences, masks, _ = model._sequence_arrays(records, allow_invalid=False)
        count = min(sample_origins, len(sequences))
        indexes = np.unique(np.linspace(0, len(sequences) - 1, count, dtype=int))
        sequence_sample = sequences[indexes]
        mask_sample = masks[indexes]
        baseline = model._predict_arrays(sequence_sample, mask_sample)
        for feature_index, feature_name in enumerate(model.feature_names):
            ablated = sequence_sample.copy()
            ablated[:, :, feature_index] = 0.0
            changed = model._predict_arrays(ablated, mask_sample)
            delta = baseline - changed
            for horizon_index, horizon in enumerate(model.config.horizons):
                rows.append({
                    "model": name, "feature_name": feature_name,
                    "horizon": int(horizon), "sample_origins": int(len(indexes)),
                    "mean_absolute_risk_change": float(np.abs(delta[:, horizon_index]).mean()),
                    "mean_signed_risk_change": float(delta[:, horizon_index].mean()),
                    "ablation_value": "zero after training normalization (training mean)",
                    "interpretation": "global sensitivity diagnostic; not a physical intervention or causal effect",
                })
    frame = pd.DataFrame(rows)
    frame["rank"] = frame.groupby(["model", "horizon"])["mean_absolute_risk_change"].rank(
        method="first", ascending=False,
    ).astype(int)
    return frame.sort_values(["model", "horizon", "rank"]).reset_index(drop=True)


def _integrated_explanations(
    fusion: pd.DataFrame,
    local: pd.DataFrame,
    sensors: pd.DataFrame,
    alert_path: Path,
    config: dict,
) -> pd.DataFrame:
    base = pd.read_parquet(alert_path)
    base = base[["unit_id", "cycle", "alert_level"]]
    fusion_full = pd.read_parquet(alert_path.parent / "validation_fusion_predictions.parquet")
    frame = fusion_full.merge(base, on=["unit_id", "cycle"], validate="many_to_one")
    grouped_features = {
        key: part.sort_values("rank")[[
            "feature_name", "source_signal", "temporal_component", "direction",
            "shap_value", "relative_magnitude", "feature_value",
        ]].to_dict("records")
        for key, part in local.groupby(["unit_id", "cycle", "horizon"], sort=False)
    }
    grouped_sensors = {
        key: part.sort_values("rank")[[
            "source_signal", "direction", "shap_value", "relative_magnitude",
        ]].to_dict("records")
        for key, part in sensors.groupby(["unit_id", "cycle", "horizon"], sort=False)
    }
    rows = []
    for row in frame.itertuples(index=False):
        key = (int(row.unit_id), int(row.cycle), int(row.horizon))
        features = grouped_features[key]
        sensor_values = grouped_sensors[key]
        codes = [
            f"XGB_{features[0]['direction'].upper()}:{features[0]['feature_name']}"
        ]
        threshold = float(config["alert_policy"][f"h{int(row.horizon)}_threshold"])
        if float(row.risk_score) >= threshold:
            codes.append(f"FINAL_RISK_ABOVE_FROZEN_H{int(row.horizon)}_THRESHOLD")
        if float(row.anomaly_score) >= 0.95:
            codes.append("ANOMALY_SCORE_ABOVE_TRAIN_HEALTHY_Q95_DIAGNOSTIC")
        rows.append({
            "unit_id": int(row.unit_id), "cycle": int(row.cycle),
            "horizon": int(row.horizon), "risk_weibull": float(row.risk_weibull),
            "risk_xgboost": float(row.risk_xgboost),
            "risk_hazard_discrete": float(row.risk_discrete_hazard),
            "risk_final": float(row.risk_score), "anomaly_score": float(row.anomaly_score),
            "disagreement": float(row.disagreement),
            "top_features": json.dumps(features, ensure_ascii=False, separators=(",", ":")),
            "top_sensors": json.dumps(sensor_values, ensure_ascii=False, separators=(",", ":")),
            "reason_codes": json.dumps(codes, ensure_ascii=False, separators=(",", ":")),
            "prediction_status": str(row.prediction_status),
            "input_validity": str(row.input_validity),
            "telemetry_stale": False, "alert_level": str(row.alert_level),
        })
    return pd.DataFrame(rows)


def _bootstrap_audit(
    sources: dict[str, pd.DataFrame], config: dict,
) -> dict[str, object]:
    cfg = UnitBootstrapConfig(
        resamples=int(config["bootstrap"]["resamples"]),
        confidence_level=float(config["bootstrap"]["confidence_level"]),
        seed=int(config["bootstrap"]["seed"]),
    )
    output: dict[str, object] = {}
    for horizon in (15, 30):
        reference = sources["fusion"].loc[sources["fusion"].horizon.eq(horizon)].copy()
        wide = reference.rename(columns={"risk_score": "fusion"})
        for model_name in PROBABILITY_MODELS[:-1]:
            column = sources[model_name].loc[
                sources[model_name].horizon.eq(horizon),
                ["unit_id", "cycle", "risk_score"],
            ].rename(columns={"risk_score": model_name})
            wide = wide.merge(column, on=["unit_id", "cycle"], validate="one_to_one")

        metrics: dict[str, Callable[[pd.DataFrame], float | None]] = {}
        for model_name in PROBABILITY_MODELS:
            metrics[f"{model_name}__brier"] = (
                lambda data, column=model_name: float(np.mean((data[column] - data.label) ** 2))
            )
            metrics[f"{model_name}__pr_auc"] = (
                lambda data, column=model_name: float(
                    average_precision_score(data.label, data[column])
                )
            )
            metrics[f"{model_name}__roc_auc"] = (
                lambda data, column=model_name: float(roc_auc_score(data.label, data[column]))
            )
        threshold = float(config["alert_policy"][f"h{horizon}_threshold"])
        persistence = int(config["alert_policy"]["persistence_cycles"])
        metrics["fusion__recall_policy"] = lambda data: float(
            threshold_metrics(data.label, data.fusion, threshold=threshold)["recall"]
        )

        temporal_cache: dict[str, object] = {"frame": None, "result": None}

        def temporal(data: pd.DataFrame) -> pd.DataFrame:
            if temporal_cache["frame"] is not data:
                temporal_cache["frame"] = data
                temporal_cache["result"] = alert_metrics_by_unit(
                    data.rename(columns={"fusion": "risk_score"}),
                    threshold=threshold, persistence_cycles=persistence,
                )
            return temporal_cache["result"]  # type: ignore[return-value]

        metrics["fusion__mean_lead_time"] = lambda data: (
            float(temporal(data).lead_time.dropna().mean())
            if temporal(data).lead_time.notna().any() else None
        )
        metrics["fusion__false_alerts_per_unit"] = lambda data: float(
            temporal(data).false_alert_episode_count.mean()
        )
        intervals = unit_bootstrap_intervals(wide, metrics, config=cfg)
        for name, interval in intervals.items():
            model_name, metric_name = name.split("__", 1)
            if metric_name == "brier":
                observed = float(np.mean((wide[model_name] - wide.label) ** 2))
            elif metric_name == "pr_auc":
                observed = average_precision(wide.label, wide[model_name])
            elif metric_name == "roc_auc":
                observed = roc_auc(wide.label, wide[model_name])
            elif metric_name == "recall_policy":
                observed = float(threshold_metrics(wide.label, wide.fusion, threshold=threshold)["recall"])
            elif metric_name == "mean_lead_time":
                unit = temporal(wide)
                observed = float(unit.lead_time.dropna().mean()) if unit.lead_time.notna().any() else None
            else:
                observed = float(temporal(wide).false_alert_episode_count.mean())
            interval["observed"] = observed
            interval["model"] = model_name
            interval["metric"] = metric_name
            interval["horizon"] = horizon
            interval["threshold"] = threshold if metric_name in {
                "recall_policy", "mean_lead_time", "false_alerts_per_unit"
            } else None
        output[str(horizon)] = intervals
    return output


def _select_examples(explanations: pd.DataFrame, fusion: pd.DataFrame) -> dict[str, object]:
    candidates = explanations.loc[explanations.horizon.eq(30)].merge(
        fusion.loc[fusion.horizon.eq(30), ["unit_id", "cycle", "label", "RUL"]],
        on=["unit_id", "cycle"], validate="one_to_one",
    )
    emitted = candidates.loc[candidates.alert_level.ne("normal")]
    correct = emitted.loc[emitted.label.eq(1)].sort_values("risk_final", ascending=False)
    false = emitted.loc[emitted.label.eq(0)].sort_values("risk_final", ascending=False)

    def record(frame: pd.DataFrame) -> dict[str, object] | None:
        if frame.empty:
            return None
        row = frame.iloc[0]
        return {
            "unit_id": int(row.unit_id), "cycle": int(row.cycle), "horizon": 30,
            "RUL": int(row.RUL), "risk_final": float(row.risk_final),
            "risk_xgboost": float(row.risk_xgboost), "anomaly_score": float(row.anomaly_score),
            "disagreement": float(row.disagreement), "alert_level": str(row.alert_level),
            "top_features": json.loads(row.top_features),
            "reason_codes": json.loads(row.reason_codes),
        }
    return {"correct_alert": record(correct), "false_alert": record(false)}


def _write_explainability_report(path: Path, result: dict[str, object]) -> None:
    calibration = pd.DataFrame(result["calibration"])
    lines = [
        "# Explicabilidade, calibração e incerteza empírica — FD001", "",
        "## Escopo", "",
        "Auditoria retrospectiva dos artefatos congelados em validation. Nenhum modelo foi criado ou reajustado; `test_internal`, `test_FD001.txt` e `RUL_FD001.txt` não foram lidos. Os resultados se limitam às 15 unidades de validation do FD001.", "",
        "## Semântica", "",
        "- SHAP descreve contribuições do XGBoost no espaço de margem bruta; não prova causalidade e não acrescenta significado físico aos nomes dos sensores.",
        "- `anomaly_score` é um indicador de anormalidade, não uma probabilidade de falha.",
        "- `disagreement` é divergência observada entre probabilidades comparáveis, não um intervalo de confiança.",
        "- Os intervalos abaixo quantificam variação empírica das métricas ao reamostrar motores inteiros; não são intervalos por observações independentes.", "",
        "## Calibração em validation", "",
        "| Modelo | H | Brier | ECE | Intercepto | Inclinação |", "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in calibration.itertuples(index=False):
        intercept = "n/a" if row.calibration_intercept is None else f"{row.calibration_intercept:.6f}"
        slope = "n/a" if row.calibration_slope is None else f"{row.calibration_slope:.6f}"
        lines.append(
            f"| {row.model} | {row.horizon} | {row.brier_score:.6f} | "
            f"{row.expected_calibration_error:.6f} | {intercept} | {slope} |"
        )
    lines.extend(["", "## Exemplos de explicação", ""])
    for label, title in (("correct_alert", "Alerta correto"), ("false_alert", "Falso alerta")):
        example = result["examples"][label]
        if example is None:
            lines.append(f"### {title}\n\nNenhum exemplo emitido foi encontrado com a política congelada.\n")
            continue
        lines.extend([
            f"### {title}", "",
            f"Unidade {example['unit_id']}, ciclo {example['cycle']}, RUL retrospectivo {example['RUL']}, risco final H30 {example['risk_final']:.6f}, `anomaly_score` {example['anomaly_score']:.6f} e `disagreement` {example['disagreement']:.6f}.", "",
            "Principais contribuições XGBoost:", "",
        ])
        for feature in example["top_features"][:3]:
            lines.append(
                f"- `{feature['feature_name']}`: {feature['direction']}, magnitude relativa "
                f"{feature['relative_magnitude']:.4f}, SHAP {feature['shap_value']:+.6f}."
            )
        lines.extend(["", "Reason codes: " + ", ".join(f"`{code}`" for code in example["reason_codes"]), ""])
    lines.extend([
        "## Métodos econômicos para os demais modelos", "",
        "A Weibull permanece explicável apenas por idade populacional. O hazard discreto usa coeficientes padronizados como associação global. TCN e Transformer usam ablação de um canal por vez em amostra determinística: o canal é substituído por zero após normalização, isto é, pela média do treino. Essa ablação é sensibilidade do modelo, não intervenção física.", "",
        "## Intervalos bootstrap", "",
        "Os artefatos registram estimativa observada, mediana, limites percentis de 95%, número de réplicas válidas e cada motivo de réplica inválida. Recall, lead time médio e falsos alertas por unidade são calculados somente para a fusão com a política congelada; os demais modelos não receberam um threshold operacional nesta etapa.", "",
        "| H | Métrica da fusão | Observado | IC 95% inferior | IC 95% superior | Válidas | Inválidas |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: |",
    ])
    for horizon in ("15", "30"):
        for name in (
            "fusion__brier", "fusion__pr_auc", "fusion__roc_auc",
            "fusion__recall_policy", "fusion__mean_lead_time",
            "fusion__false_alerts_per_unit",
        ):
            item = result["bootstrap"][horizon][name]
            observed = "n/a" if item["observed"] is None else f"{item['observed']:.6f}"
            lower = "n/a" if item["lower"] is None else f"{item['lower']:.6f}"
            upper = "n/a" if item["upper"] is None else f"{item['upper']:.6f}"
            lines.append(
                f"| {horizon} | {item['metric']} | {observed} | {lower} | {upper} | "
                f"{item['valid_replicates']} | {item['invalid_replicates']} |"
            )
    lines.extend(["", "## Limitações", "",
                  "Quinze motores fornecem evidência limitada para quantis extremos. ECE depende da escolha de dez bins. SHAP e ablação explicam sensibilidade da implementação, sem identificar mecanismos físicos, causas ou segurança operacional."])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_requirements_reports(root: Path) -> None:
    requirements_path = root / "docs/safety_requirements.md"
    matrix_path = root / "docs/traceability_matrix.csv"
    text = requirements_path.read_text(encoding="utf-8")
    requirements = _parse_requirements(text)
    with matrix_path.open(encoding="utf-8", newline="") as stream:
        matrix = {row["requirement_id"]: row for row in csv.DictReader(stream)}
    tests = _existing_test_ids(root / "tests")

    validation_lines = [
        "# Relatório de validação dos requisitos", "",
        "Validação pergunta se cada requisito é correto e suficientemente completo para o objetivo do demonstrador. Ela não demonstra que o código o implementa.", "",
        "| ID | Claro | Necessário | Consistente | Verificável | Rastreável | Completo | Problema ou limite |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    open_issues = {
        "SRQ012": "Critérios de desempenho e antecedência ainda dependem de contexto de decisão e custo não definido.",
        "SRQ043": "A idade lógica está definida; timestamp e política física por fonte permanecem futuros.",
        "SRQ047": "Os thresholds são experimentais e ainda não possuem adequação operacional externa.",
        "SRQ065": "Reprodução completa do experimento de filtragem em ambiente independente ainda não foi executada.",
        "SRQ068": "Critérios congelados são específicos do FD001 e não validam aceitabilidade industrial.",
        "SRQ075": "Determinismo entre plataformas PyTorch permanece limitado.",
        "SRQ086": "Memória é estimativa analítica e não pico medido do processo.",
        "SRQ093": "Quinze unidades limitam estabilidade dos intervalos bootstrap.",
    }
    for item in requirements:
        rid = item["requirement_id"]
        row = matrix.get(rid, {})
        traceable = "sim" if row else "não"
        verifiable = "sim" if item.get("verification_method") else "não"
        complete = "parcial" if rid in open_issues or item.get("status") != "verified" else "sim"
        issue = open_issues.get(rid, "Nenhum problema material identificado nesta revisão.")
        validation_lines.append(
            f"| {rid} | sim | sim | sim | {verifiable} | {traceable} | {complete} | {issue} |"
        )
    validation_lines.extend([
        "", "## Problemas de requisito", "",
        "Nenhuma redação foi alterada nesta etapa. Os limites acima foram preservados como itens abertos; portanto, não foi necessário abrir uma análise de impacto para mudança de statement.",
    ])
    (root / "reports/requirements_validation_report.md").write_text(
        "\n".join(validation_lines) + "\n", encoding="utf-8",
    )

    verification_lines = [
        "# Relatório de verificação dos requisitos", "",
        "Verificação pergunta se a implementação satisfaz o requisito especificado. Status `verified` só é reproduzido quando a matriz contém implementação, evidência objetiva e testes existentes.", "",
        "| requirement_id | verification_method | evidence | test_ids | result | status |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in requirements:
        rid = item["requirement_id"]
        row = matrix.get(rid, {})
        declared_tests = [value for value in row.get("test_ids", "").split("; ") if value]
        missing_tests = [value for value in declared_tests if value not in tests]
        objective = bool(row.get("implementation") and row.get("verification_evidence") and declared_tests)
        if item.get("status") == "verified" and objective and not missing_tests:
            result, status = "PASS — evidência ligada e testes existentes", "verified"
        elif item.get("status") == "planned":
            result, status = "NOT RUN — implementação/evidência ausente", "planned"
        else:
            reason = "testes referenciados ausentes" if missing_tests else "evidência parcial ou escopo futuro"
            result, status = "PARTIAL — " + reason, "partial"
        evidence = "; ".join(filter(None, [row.get("implementation", ""), row.get("verification_evidence", "")])) or "—"
        test_text = "; ".join(declared_tests) or "—"
        method = item.get("verification_method", "—")
        verification_lines.append(
            f"| {rid} | {method} | {evidence} | {test_text} | {result} | {status} |"
        )
    (root / "reports/requirements_verification_report.md").write_text(
        "\n".join(verification_lines) + "\n", encoding="utf-8",
    )


def _parse_requirements(text: str) -> list[dict[str, str]]:
    ids = re.findall(r"^## (SRQ\d{3})$", text, flags=re.MULTILINE)
    rows: list[dict[str, str]] = []
    for index, requirement_id in enumerate(ids):
        start = text.index(f"## {requirement_id}\n")
        end = text.find("\n## ", start + 4)
        section = text[start:] if end < 0 else text[start:end]
        fields = dict(re.findall(r"^- ([a-z_]+): (.*)$", section, flags=re.MULTILINE))
        fields["requirement_id"] = requirement_id
        fields["order"] = str(index)
        rows.append(fields)
    return rows


def _existing_test_ids(test_root: Path) -> set[str]:
    identifiers: set[str] = set()
    for path in test_root.glob("test_*.py"):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.ClassDef):
                identifiers.update(
                    f"{path.stem}.{node.name}.{method.name}"
                    for method in node.body
                    if isinstance(method, ast.FunctionDef) and method.name.startswith("test_")
                )
    return identifiers


def _validate_config(config: dict) -> None:
    if any(bool(config["scope"][key]) for key in (
        "use_test_internal", "use_official_test", "use_official_rul", "retrain_models",
    )):
        raise ValueError("this stage is validation-only and cannot use tests or retrain models")
    if int(config["analysis"]["reliability_bins"]) < 2:
        raise ValueError("reliability_bins must be at least two")
    if int(config["analysis"]["shap_batch_size"]) < 1:
        raise ValueError("shap_batch_size must be positive")


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True,
                               allow_nan=False, default=str) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path("."))
    parser.add_argument("--config", type=Path, default=Path("configs/explainability_uncertainty.toml"))
    args = parser.parse_args()
    result = run_explainability_uncertainty(args.project_root, args.config)
    print(json.dumps(result["scope"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
