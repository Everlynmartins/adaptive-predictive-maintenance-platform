"""Train and evaluate a small causal TCN on NASA C-MAPSS FD001."""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import json
import platform
from pathlib import Path
import time
import tomllib

import numpy as np
import pandas as pd
import torch

from predictive_maintenance.core.records import FeatureRecord, TargetRecord
from predictive_maintenance.data.cmapss import CMAPSSFD001Loader
from predictive_maintenance.evaluation.probability import (
    evaluate_binary_probabilities,
    threshold_metrics,
)
from predictive_maintenance.models.fusion.probabilistic import alert_metrics_by_unit
from predictive_maintenance.models.temporal.tcn import TCNConfig, TCNRiskModel


FORBIDDEN_INPUTS = {
    "RUL", "normalized_life", "final_cycle", "max_cycle",
    "failure_within_horizon", "failure_within_critical_horizon",
}


def run_tcn(
    processed: Path = Path("data/processed/fd001"),
    raw: Path = Path("data/raw"),
    config_path: Path = Path("configs/tcn.toml"),
    report_root: Path = Path("reports"),
) -> dict[str, object]:
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    _validate_config(config)
    train, validation, manifest, source_mode = _load_development(processed, raw)
    feature_names = _input_feature_names(report_root, config)
    if FORBIDDEN_INPUTS & set(feature_names):
        raise ValueError("TCN input schema contains forbidden retrospective information")

    horizons = tuple(int(value) for value in config["model"]["horizons"])
    train_operational = _operational_frame(train)
    validation_operational = _operational_frame(validation)
    train_records = _feature_records(train_operational, feature_names)
    train_targets = _target_records(train_operational, horizons)
    validation_records = _feature_records(validation_operational, feature_names)
    validation_targets = _target_records(validation_operational, horizons)

    fitting_units, stop_units = _early_stopping_units(
        manifest["units"]["train"], fraction=float(config["training"]["early_stopping_fraction"]),
        seed=int(config["training"]["seed"]),
    )
    fitting_mask = train_operational.unit_id.isin(fitting_units).to_numpy()
    stopping_mask = train_operational.unit_id.isin(stop_units).to_numpy()
    fit_records = [record for record, keep in zip(train_records, fitting_mask, strict=True) if keep]
    stop_records = [record for record, keep in zip(train_records, stopping_mask, strict=True) if keep]
    fit_targets = [target for target, keep in zip(train_targets, fitting_mask, strict=True) if keep]
    stop_targets = [target for target, keep in zip(train_targets, stopping_mask, strict=True) if keep]

    base_config = _model_config(config)
    selection_model = TCNRiskModel(base_config, feature_names)
    selection_start = time.perf_counter()
    selection_model.fit_with_validation(fit_records, fit_targets, stop_records, stop_targets)
    selection_seconds = time.perf_counter() - selection_start
    selected_epoch = int(selection_model.training_summary["selected_epoch"])

    final_config = replace(base_config, max_epochs=selected_epoch)
    final_model = TCNRiskModel(final_config, feature_names)
    final_start = time.perf_counter()
    final_model.fit(train_records, train_targets)
    final_training_seconds = time.perf_counter() - final_start

    output = report_root / "tcn"
    artifacts = output / "artifacts"
    output.mkdir(parents=True, exist_ok=True)
    artifacts.mkdir(parents=True, exist_ok=True)
    model_path = artifacts / "tcn_model.pt"
    final_model.save(model_path)

    inference_start = time.perf_counter()
    probabilities = final_model.predict_probabilities(validation_records)
    inference_seconds = time.perf_counter() - inference_start
    predictions = _prediction_frame(validation_operational, horizons, probabilities, final_model)
    metrics, by_unit = _evaluate_predictions(predictions, config)
    prediction_paths = _write_table(predictions, artifacts / "validation_predictions.parquet")
    unit_paths = _write_table(by_unit, artifacts / "validation_metrics_by_unit.parquet")

    baseline_comparison = _baseline_comparison(report_root, metrics)
    provenance = _provenance(
        config_path, processed, raw, report_root, manifest, source_mode, feature_names,
        fitting_units, stop_units,
        selection_seconds, final_training_seconds, inference_seconds,
    )
    oof_state = {
        "generated": bool(config["oof"]["generate"]),
        "included_in_current_fusion": False,
        "reason": str(config["oof"]["reason"]),
    }
    if oof_state["generated"]:
        raise NotImplementedError(
            "This stage keeps the TCN outside the current fusion. Set oof.generate=false; "
            "grouped TCN OOF can be implemented when fusion integration is requested."
        )

    result = {
        "model": {
            "selected_epoch": selected_epoch,
            "parameter_count": final_model.parameter_count(),
            "sequence_length": final_config.sequence_length,
            "feature_count": len(feature_names),
            "feature_names": list(feature_names),
            "training_device": final_model.training_summary.get("device", "cpu"),
            "selection_training_seconds": selection_seconds,
            "final_training_seconds": final_training_seconds,
            "validation_inference_seconds": inference_seconds,
            "validation_inference_ms_per_origin": 1000.0 * inference_seconds / len(validation_records),
            "epoch_selection": {
                "fit_units": fitting_units,
                "early_stopping_units": stop_units,
                "validation_units_used": False,
                "clean_model_reinitialized_for_final_fit": True,
            },
        },
        "metrics": metrics,
        "comparison": baseline_comparison,
        "oof": oof_state,
        "provenance": provenance,
    }
    _write_json(output / "metrics.json", result)
    card = _model_card(final_model, config, manifest, result, model_path, prediction_paths, unit_paths)
    _write_json(output / "model_card.json", card)
    _write_report(report_root / "tcn_report.md", result, config, oof_state)
    return result


def _load_development(processed: Path, raw: Path):
    manifest = json.loads((processed / "split_manifest.json").read_text(encoding="utf-8"))
    declared = {name: set(int(value) for value in manifest["units"][name])
                for name in ("train", "validation", "test_internal")}
    if declared["train"] & declared["validation"] or declared["train"] & declared["test_internal"] or declared["validation"] & declared["test_internal"]:
        raise ValueError("split manifest contains overlapping units")
    try:
        train = pd.read_parquet(processed / "train.parquet")
        validation = pd.read_parquet(processed / "validation.parquet")
        source_mode = "processed_parquet"
    except ImportError:
        complete = CMAPSSFD001Loader().load_frame(raw / "train_FD001.txt")
        train = complete.loc[complete.unit_id.isin(declared["train"])].reset_index(drop=True)
        validation = complete.loc[complete.unit_id.isin(declared["validation"])].reset_index(drop=True)
        source_mode = "raw_train_fallback_due_to_missing_local_parquet_engine"
    for name, frame in (("train", train), ("validation", validation)):
        if set(frame.unit_id.astype(int)) != declared[name]:
            raise ValueError(f"{name} units disagree with split manifest")
        if len(frame) != int(manifest["rows"][name]):
            raise ValueError(f"{name} row count disagrees with split manifest")
        ordered = frame.sort_values(["unit_id", "cycle"]).reset_index(drop=True)
        if not ordered[["unit_id", "cycle"]].equals(frame[["unit_id", "cycle"]].reset_index(drop=True)):
            raise ValueError(f"{name} must be ordered by unit_id and cycle")
    return train, validation, manifest, source_mode


def _input_feature_names(report_root: Path, config: dict) -> tuple[str, ...]:
    manifest_path = report_root / "classical_ml/artifacts/feature_manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    names = list(payload["raw_columns"])
    if bool(config["model"]["include_age_cycle"]):
        names.append("age_cycle")
    if not names or len(names) != len(set(names)):
        raise ValueError("TCN feature schema is empty or duplicated")
    return tuple(names)


def _feature_records(frame: pd.DataFrame, names: tuple[str, ...]) -> list[FeatureRecord]:
    records: list[FeatureRecord] = []
    for row in frame.itertuples(index=False):
        values = {}
        for name in names:
            values[name] = float(row.cycle) if name == "age_cycle" else float(getattr(row, name))
        records.append(FeatureRecord(str(int(row.unit_id)), int(row.cycle), values))
    return records


def _operational_frame(frame: pd.DataFrame) -> pd.DataFrame:
    final = frame.groupby("unit_id", sort=False).cycle.transform("max")
    output = frame.copy()
    output["RUL"] = (final - frame.cycle).astype(int)
    return output.loc[output.RUL.gt(0)].reset_index(drop=True)


def _target_records(frame: pd.DataFrame, horizons: tuple[int, int]) -> list[TargetRecord]:
    if "RUL" not in frame.columns or (frame.RUL <= 0).any():
        raise ValueError("target construction requires operational rows with positive RUL")
    output: list[TargetRecord] = []
    for unit, cycle, remaining in zip(frame.unit_id, frame.cycle, frame.RUL, strict=True):
        values = {f"failure_within_h{horizon}": int(0 < remaining <= horizon)
                  for horizon in horizons}
        output.append(TargetRecord(str(int(unit)), int(cycle), values))
    return output


def _early_stopping_units(unit_ids, *, fraction: float, seed: int) -> tuple[list[int], list[int]]:
    unique = np.asarray(sorted(set(int(value) for value in unit_ids)), dtype=int)
    count = max(1, int(round(len(unique) * fraction)))
    if count >= len(unique):
        raise ValueError("early stopping split leaves no fitting units")
    shuffled = np.random.default_rng(seed).permutation(unique)
    stop = sorted(shuffled[:count].astype(int).tolist())
    fit = sorted(shuffled[count:].astype(int).tolist())
    if set(fit) & set(stop) or set(fit) | set(stop) != set(unique.tolist()):
        raise RuntimeError("early stopping unit split is invalid")
    return fit, stop


def _model_config(config: dict) -> TCNConfig:
    return TCNConfig(
        model_name="tcn_fd001",
        model_version=str(config["model"]["version"]),
        horizons=tuple(int(value) for value in config["model"]["horizons"]),
        sequence_length=int(config["model"]["sequence_length"]),
        channels=tuple(int(value) for value in config["model"]["channels"]),
        kernel_size=int(config["model"]["kernel_size"]),
        dropout=float(config["model"]["dropout"]),
        batch_size=int(config["training"]["batch_size"]),
        learning_rate=float(config["training"]["learning_rate"]),
        weight_decay=float(config["training"]["weight_decay"]),
        max_epochs=int(config["training"]["max_epochs"]),
        patience=int(config["training"]["patience"]),
        min_delta=float(config["training"]["min_delta"]),
        random_seed=int(config["training"]["seed"]),
        torch_threads=int(config["training"]["torch_threads"]),
    )


def _prediction_frame(frame: pd.DataFrame, horizons: tuple[int, int], probabilities: np.ndarray,
                      model: TCNRiskModel) -> pd.DataFrame:
    if "RUL" not in frame.columns or (frame.RUL <= 0).any():
        raise ValueError("prediction evaluation requires operational rows")
    if probabilities.shape != (len(frame), len(horizons)):
        raise ValueError("probability matrix is not aligned to validation rows")
    rows = []
    for index, row in enumerate(frame.itertuples(index=False)):
        for column, horizon in enumerate(horizons):
            risk = float(probabilities[index, column])
            rows.append({
                "unit_id": int(row.unit_id), "cycle": int(row.cycle), "RUL": int(row.RUL),
                "horizon": int(horizon), "label": int(row.RUL <= horizon),
                "risk_score": risk, "survival_score": 1.0 - risk,
                "health_score": 100.0 * (1.0 - risk), "model_name": model.config.model_name,
                "model_version": model.config.model_version, "prediction_status": "available",
                "input_validity": "valid",
            })
    output = pd.DataFrame(rows)
    if output.empty or output.duplicated(["unit_id", "cycle", "horizon"]).any():
        raise RuntimeError("TCN validation prediction keys are invalid")
    return output


def _evaluate_predictions(predictions: pd.DataFrame, config: dict):
    bins = int(config["evaluation"]["reliability_bins"])
    epsilon = float(config["evaluation"]["log_loss_epsilon"])
    threshold = float(config["evaluation"]["exploratory_threshold"])
    persistence = int(config["evaluation"]["persistence_cycles"])
    metrics: dict[str, object] = {}
    unit_frames = []
    for horizon in sorted(predictions.horizon.unique()):
        part = predictions.loc[predictions.horizon.eq(horizon)].copy()
        probability = evaluate_binary_probabilities(
            part.label, part.risk_score, reliability_bins=bins, log_loss_epsilon=epsilon,
        )
        classification = threshold_metrics(part.label, part.risk_score, threshold=threshold)
        alerts = alert_metrics_by_unit(part, threshold=threshold, persistence_cycles=persistence)
        alerts["horizon"] = int(horizon)
        alerts["threshold"] = threshold
        unit_frames.append(alerts)
        metrics[str(int(horizon))] = {
            **probability,
            "exploratory_classification": classification,
            "alert_summary": {
                "threshold": threshold,
                "persistence_cycles": persistence,
                "units": int(alerts.unit_id.nunique()),
                "units_with_alert": int(alerts.first_alert_cycle.notna().sum()),
                "median_lead_time": _finite_or_none(alerts.lead_time.median()),
                "mean_false_alert_episodes_per_unit": float(alerts.false_alert_episode_count.mean()),
                "mean_alert_persistence": float(alerts.alert_persistence.mean()),
                "mean_fraction_life_under_alert": float(alerts.fraction_life_under_alert.mean()),
            },
        }
    pivot = predictions.pivot(index=["unit_id", "cycle"], columns="horizon", values="risk_score")
    short, long = sorted(int(value) for value in predictions.horizon.unique())
    difference = pivot[short] - pivot[long]
    metrics["cross_horizon_coherence"] = {
        "origins": len(pivot), "violations_short_greater_than_long": int((difference > 1.0e-12).sum()),
        "maximum_violation": float(max(0.0, difference.max())),
    }
    return metrics, pd.concat(unit_frames, ignore_index=True)


def _baseline_comparison(report_root: Path, tcn_metrics: dict) -> dict[str, object]:
    classical = json.loads((report_root / "classical_ml/metrics.json").read_text(encoding="utf-8"))
    hazard = json.loads((report_root / "discrete_hazard/metrics.json").read_text(encoding="utf-8"))
    fusion = json.loads((report_root / "fusion/metrics.json").read_text(encoding="utf-8"))
    output: dict[str, object] = {}
    for horizon in (15, 30):
        h = str(horizon)
        output[h] = {
            "tcn": _metric_subset(tcn_metrics[h], "exploratory_classification"),
            "xgboost": _metric_subset(classical["results"]["validation"]["xgboost"][h], "exploratory_classification"),
            "discrete_hazard": _metric_subset(_hazard_validation(hazard, h), "exploratory_classification"),
            "fusion_stacking": _metric_subset(fusion["validation"]["stacking"][h], "classification"),
        }
    return output


def _hazard_validation(payload: dict, horizon: str) -> dict:
    for path in (
        ("results", "validation", horizon),
        ("validation", horizon),
        ("metrics", "validation", horizon),
    ):
        value = payload
        try:
            for key in path:
                value = value[key]
            return value
        except (KeyError, TypeError):
            continue
    raise KeyError(f"could not locate discrete hazard validation metrics for H={horizon}")


def _metric_subset(item: dict, classification_key: str) -> dict[str, object]:
    classification = item.get(classification_key, {})
    return {
        "brier_score": float(item["brier_score"]),
        "log_loss": float(item["log_loss"]),
        "roc_auc": float(item["roc_auc"]),
        "pr_auc_average_precision": float(item["pr_auc_average_precision"]),
        "recall": (None if "recall" not in classification else float(classification["recall"])),
        "threshold": (None if "threshold" not in classification else float(classification["threshold"])),
    }


def _model_card(model: TCNRiskModel, config: dict, manifest: dict, result: dict,
                model_path: Path, prediction_paths: dict, unit_paths: dict) -> dict[str, object]:
    return {
        "model_name": model.config.model_name,
        "model_version": model.config.model_version,
        "model_family": "Temporal Convolutional Network",
        "architecture": {
            "sequence_length": model.config.sequence_length,
            "channels": list(model.config.channels),
            "kernel_size": model.config.kernel_size,
            "dropout": model.config.dropout,
            "causal_convolutions": True,
            "horizon_head": "joint monotone H15/H30 head",
            "parameter_count": model.parameter_count(),
        },
        "seed": model.config.random_seed,
        "dependencies": result["provenance"]["dependencies"],
        "training_configuration": asdict(model.config),
        "training_summary": model.training_summary,
        "training_history": model.training_history,
        "dataset": {
            "name": "NASA C-MAPSS FD001", "training_partition": "train",
            "validation_partition": "validation", "split_seed": manifest["split"]["seed"],
            "train_units": len(manifest["units"]["train"]),
            "validation_units": len(manifest["units"]["validation"]),
            "source_mode": result["provenance"]["source_mode"],
            "test_internal_used": False, "official_test_used": False,
            "official_rul_used": False,
        },
        "input_contract": {
            "features": list(model.feature_names),
            "sequence_rule": "left padded causal history ending at t; no future observation",
            "padding": "zero after train-fitted standardization with an explicit binary mask",
            "forbidden": sorted(FORBIDDEN_INPUTS),
        },
        "output_contract": "RiskPrediction for P(T_i <= t+H | F_i,t, T_i>t), H in {15,30}",
        "horizons": list(model.config.horizons),
        "metrics": result["metrics"],
        "comparison": result["comparison"],
        "shared_dependencies": [
            "same FD001 telemetry", "same benchmark terminal event and targets",
            "same Python process and part of the data preparation stack",
            "same train and validation unit partitions as the classical and hazard models",
        ],
        "limitations": [
            "benchmark-only evidence; no claim of aircraft safety, certification, or industrial transfer",
            "TCN is outside the current fusion because grouped OOF neural training was deferred",
            "architectural diversity does not demonstrate statistical, functional, physical, or development independence",
            "threshold 0.5 is exploratory and is not an operational maintenance limit",
            "short sequences depend on left padding and masking behavior",
            "training determinism is requested, but residual platform and device nondeterminism must still be treated as a failure mode",
        ],
        "artifacts": {
            "model": {"path": model_path.as_posix(), "sha256": _sha(model_path)},
            "validation_predictions": prediction_paths,
            "validation_metrics_by_unit": unit_paths,
        },
        "provenance": result["provenance"],
    }


def _provenance(config_path: Path, processed: Path, raw: Path, report_root: Path,
                 manifest: dict, source_mode: str, feature_names: tuple[str, ...],
                 fitting_units: list[int], stop_units: list[int], selection_seconds: float,
                 final_seconds: float, inference_seconds: float) -> dict[str, object]:
    input_hashes = {
        config_path.as_posix(): _sha(config_path),
        (processed / "split_manifest.json").as_posix(): _sha(processed / "split_manifest.json"),
    }
    if source_mode == "processed_parquet":
        for name in ("train.parquet", "validation.parquet"):
            path = processed / name
            input_hashes[path.as_posix()] = _sha(path)
    else:
        path = raw / "train_FD001.txt"
        input_hashes[path.as_posix()] = _sha(path)
    feature_manifest = report_root / "classical_ml/artifacts/feature_manifest.json"
    input_hashes[feature_manifest.as_posix()] = _sha(feature_manifest)
    return {
        "package_version": "0.12.0",
        "source_mode": source_mode,
        "training_partition": "train",
        "early_stopping_partition": "grouped subset of train only",
        "evaluation_partition": "validation",
        "partition_units": {
            "train": len(manifest["units"]["train"]),
            "validation": len(manifest["units"]["validation"]),
            "early_stopping_fit": fitting_units,
            "early_stopping_holdout": stop_units,
        },
        "test_internal_read": False,
        "official_test_read": False,
        "official_rul_read": False,
        "feature_names": list(feature_names),
        "dependencies": {
            "python": platform.python_version(),
            **{name: _package_version(name) for name in (
                "numpy", "pandas", "pyarrow", "scikit-learn", "torch",
            )},
        },
        "timing_seconds": {
            "model_selection_training": selection_seconds,
            "final_training": final_seconds,
            "validation_inference": inference_seconds,
        },
        "input_sha256": input_hashes,
        "manifest_source_sha256": manifest["source"]["sha256"],
    }


def _write_report(path: Path, result: dict, config: dict, oof: dict) -> None:
    metrics = result["metrics"]
    comparison = result["comparison"]
    lines = [
        "# Temporal Convolutional Network causal no FD001", "",
        "## Escopo", "",
        "A TCN usa somente histórico da mesma unidade até o ciclo atual. As sequências têm comprimento fixo, com padding à esquerda e máscara explícita. O final da trajetória, RUL, normalized_life e rótulos não entram nas features.", "",
        "A arquitetura é pequena e local. H15 e H30 são produzidos em uma única cabeça monotônica, portanto o risco H30 não pode ficar abaixo do H15 para a mesma origem.", "",
        "## Seleção e treinamento", "",
        f"A seleção de época usou somente um subconjunto de unidades do treino. A época escolhida foi {result['model']['selected_epoch']}. O modelo final foi reajustado nos 70 motores de treino por esse número fixo de épocas. Validation não foi usada para early stopping.", "",
        f"Parâmetros treináveis: {result['model']['parameter_count']}. Tempo de seleção: {result['model']['selection_training_seconds']:.3f} s. Tempo de ajuste final: {result['model']['final_training_seconds']:.3f} s. Inferência de validation: {result['model']['validation_inference_seconds']:.3f} s, ou {result['model']['validation_inference_ms_per_origin']:.4f} ms por origem neste ambiente.", "",
        "## Comparação em validation", "",
        "As métricas probabilísticas são diretamente comparáveis. Recall depende do threshold registrado por cada etapa e deve ser lido com essa ressalva.", "",
        "| H | Modelo | Brier | Log loss | ROC AUC | PR AUC | Recall | Threshold |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for horizon in (15, 30):
        for name in ("tcn", "xgboost", "discrete_hazard", "fusion_stacking"):
            row = comparison[str(horizon)][name]
            recall = "n/a" if row["recall"] is None else f"{row['recall']:.6f}"
            threshold = "n/a" if row["threshold"] is None else f"{row['threshold']:.6f}"
            lines.append(
                f"| {horizon} | {name} | {row['brier_score']:.6f} | {row['log_loss']:.6f} | "
                f"{row['roc_auc']:.6f} | {row['pr_auc_average_precision']:.6f} | {recall} | {threshold} |"
            )
    lines += ["", "## Métricas temporais da TCN", "",
              f"Threshold exploratório da TCN: {float(config['evaluation']['exploratory_threshold']):.3f}. Persistência: {int(config['evaluation']['persistence_cycles'])} ciclos. Estes valores não são limites de manutenção reais.", "",
              "| H | Unidades com alerta | Lead time mediano | Falsos alertas por unidade | Persistência média | Fração média da vida sob alerta |",
              "| ---: | ---: | ---: | ---: | ---: | ---: |"]
    for horizon in (15, 30):
        item = metrics[str(horizon)]["alert_summary"]
        lead = "n/a" if item["median_lead_time"] is None else f"{item['median_lead_time']:.2f}"
        lines.append(
            f"| {horizon} | {item['units_with_alert']} | {lead} | "
            f"{item['mean_false_alert_episodes_per_unit']:.4f} | {item['mean_alert_persistence']:.4f} | "
            f"{item['mean_fraction_life_under_alert']:.4f} |"
        )
    lines += ["", "## Coerência entre horizontes", "",
              f"Violações H15 maior que H30: {metrics['cross_horizon_coherence']['violations_short_greater_than_long']} em {metrics['cross_horizon_coherence']['origins']} origens. A propriedade é imposta pela cabeça probabilística conjunta.", "",
              "## Participação na fusão", "",
              f"OOF TCN gerado: {oof['generated']}. A TCN não foi adicionada à fusão atual. Motivo: {oof['reason']}", "",
              "## Modos de falha específicos", "",
              "A FMEA do demonstrador foi estendida com sequência curta, padding incorreto, máscara incorreta, checkpoint incorreto, não determinismo residual, saída inválida e latência excessiva.", "",
              "## Dependências comuns", "",
              "A TCN compartilha telemetria, definição de alvo, partições de unidades, runtime Python e parte da preparação dos dados com os demais modelos. Sua arquitetura temporal diferente constitui diversidade analítica, sem evidência de independência funcional, física, de desenvolvimento ou estatística.", "",
              "## Justificativa experimental", ""]
    tcn15 = comparison["15"]["tcn"]
    xgb15 = comparison["15"]["xgboost"]
    tcn30 = comparison["30"]["tcn"]
    xgb30 = comparison["30"]["xgboost"]
    better_any = (tcn15["pr_auc_average_precision"] > xgb15["pr_auc_average_precision"] or
                  tcn30["pr_auc_average_precision"] > xgb30["pr_auc_average_precision"] or
                  tcn15["brier_score"] < xgb15["brier_score"] or
                  tcn30["brier_score"] < xgb30["brier_score"])
    if better_any:
        lines.append("A TCN apresenta ganho em pelo menos uma métrica ou horizonte, portanto merece ser mantida como comparador temporal para a etapa seguinte. A decisão de produção permanece aberta porque custo, calibração e desempenho conjunto precisam ser considerados.")
    else:
        lines.append("A TCN não supera o XGBoost nas métricas principais deste experimento. Ela pode ser mantida somente como comparador temporal para testar se o Transformer acrescenta informação suficiente para justificar modelos sequenciais mais caros.")
    lines += ["", "Resultados limitados ao NASA C MAPSS FD001. Nenhuma evidência desta etapa constitui demonstração de segurança operacional, certificação ou generalização industrial."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_table(frame: pd.DataFrame, parquet_path: Path) -> dict[str, str]:
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        frame.to_parquet(parquet_path, index=False)
        return {"path": parquet_path.as_posix(), "format": "parquet", "sha256": _sha(parquet_path)}
    except ImportError:
        csv_path = parquet_path.with_suffix(".csv")
        frame.to_csv(csv_path, index=False)
        return {"path": csv_path.as_posix(), "format": "csv_fallback", "sha256": _sha(csv_path)}


def _validate_config(config: dict) -> None:
    if tuple(config["model"]["horizons"]) != (15, 30):
        raise ValueError("this TCN stage requires horizons [15, 30]")
    fraction = float(config["training"]["early_stopping_fraction"])
    if not 0.0 < fraction < 0.5:
        raise ValueError("early stopping fraction must be in (0, 0.5)")
    if bool(config["oof"]["generate"]):
        raise ValueError("current TCN stage must keep oof.generate=false unless fusion integration is explicitly added")


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        if name == "torch":
            return torch.__version__
        return "unknown"


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True,
                               allow_nan=False, default=str) + "\n", encoding="utf-8")


def _finite_or_none(value) -> float | None:
    return float(value) if value is not None and np.isfinite(value) else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/tcn.toml"))
    parser.add_argument("--processed", type=Path, default=Path("data/processed/fd001"))
    parser.add_argument("--raw", type=Path, default=Path("data/raw"))
    args = parser.parse_args()
    print(json.dumps(run_tcn(args.processed, args.raw, args.config), ensure_ascii=False,
                     indent=2, default=str))


if __name__ == "__main__":
    main()
