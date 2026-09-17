"""Train and evaluate a small causal Transformer Encoder on FD001."""

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

import torch

from predictive_maintenance.application.tcn_fd001 import (
    FORBIDDEN_INPUTS,
    _early_stopping_units,
    _evaluate_predictions,
    _feature_records,
    _input_feature_names,
    _load_development,
    _metric_subset,
    _operational_frame,
    _prediction_frame,
    _target_records,
    _write_table,
)
from predictive_maintenance.models.temporal.transformer import (
    TransformerConfig,
    TransformerRiskModel,
)


def run_transformer(
    processed: Path = Path("data/processed/fd001"),
    raw: Path = Path("data/raw"),
    config_path: Path = Path("configs/transformer.toml"),
    report_root: Path = Path("reports"),
) -> dict[str, object]:
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    _validate_config(config)
    train, validation, manifest, source_mode = _load_development(processed, raw)
    feature_names = _input_feature_names(report_root, config)
    if FORBIDDEN_INPUTS & set(feature_names):
        raise ValueError("Transformer input schema contains forbidden information")

    horizons = tuple(int(value) for value in config["model"]["horizons"])
    train_operational = _operational_frame(train)
    validation_operational = _operational_frame(validation)
    train_records = _feature_records(train_operational, feature_names)
    train_targets = _target_records(train_operational, horizons)
    validation_records = _feature_records(validation_operational, feature_names)

    fit_units, stop_units = _early_stopping_units(
        manifest["units"]["train"],
        fraction=float(config["training"]["early_stopping_fraction"]),
        seed=int(config["training"]["seed"]),
    )
    fit_mask = train_operational.unit_id.isin(fit_units).to_numpy()
    stop_mask = train_operational.unit_id.isin(stop_units).to_numpy()
    fit_records = [record for record, keep in zip(train_records, fit_mask, strict=True) if keep]
    fit_targets = [target for target, keep in zip(train_targets, fit_mask, strict=True) if keep]
    stop_records = [record for record, keep in zip(train_records, stop_mask, strict=True) if keep]
    stop_targets = [target for target, keep in zip(train_targets, stop_mask, strict=True) if keep]

    base_config = _model_config(config)
    selection_model = TransformerRiskModel(base_config, feature_names)
    start = time.perf_counter()
    selection_model.fit_with_validation(fit_records, fit_targets, stop_records, stop_targets)
    selection_seconds = time.perf_counter() - start
    selected_epoch = int(selection_model.training_summary["selected_epoch"])

    final_config = replace(base_config, max_epochs=selected_epoch)
    final_model = TransformerRiskModel(final_config, feature_names)
    start = time.perf_counter()
    final_model.fit(train_records, train_targets)
    final_seconds = time.perf_counter() - start

    output = report_root / "transformer"
    artifacts = output / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    model_path = artifacts / "transformer_model.pt"
    final_model.save(model_path)

    start = time.perf_counter()
    probabilities = final_model.predict_probabilities(validation_records)
    inference_seconds = time.perf_counter() - start
    predictions = _prediction_frame(validation_operational, horizons, probabilities, final_model)
    metrics, by_unit = _evaluate_predictions(predictions, config)
    prediction_artifact = _write_table(predictions, artifacts / "validation_predictions.parquet")
    unit_artifact = _write_table(by_unit, artifacts / "validation_metrics_by_unit.parquet")
    comparison = _comparison(report_root, metrics)
    tcn_result = json.loads((report_root / "tcn/metrics.json").read_text(encoding="utf-8"))
    memory = {
        "parameter_bytes_float32": final_model.parameter_memory_bytes(),
        "parameter_mebibytes_float32": final_model.parameter_memory_bytes() / 2**20,
        "estimated_inference_working_bytes_batch_1": final_model.approximate_inference_working_memory_bytes(1),
        "estimated_inference_working_mebibytes_batch_1": final_model.approximate_inference_working_memory_bytes(1) / 2**20,
        "checkpoint_bytes": model_path.stat().st_size,
        "method": "analytical float32 parameter and attention/token tensor estimate; excludes Python and allocator overhead",
    }
    provenance = _provenance(
        config_path, processed, report_root, manifest, source_mode, feature_names,
        fit_units, stop_units, selection_seconds, final_seconds, inference_seconds,
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
            "final_training_seconds": final_seconds,
            "validation_inference_seconds": inference_seconds,
            "validation_inference_ms_per_origin": 1000.0 * inference_seconds / len(validation_records),
            "memory": memory,
            "cost_relative_to_tcn": {
                "parameter_count_ratio": final_model.parameter_count() / tcn_result["model"]["parameter_count"],
                "inference_latency_ratio": (1000.0 * inference_seconds / len(validation_records)) / tcn_result["model"]["validation_inference_ms_per_origin"],
                "selection_training_time_ratio": selection_seconds / tcn_result["model"]["selection_training_seconds"],
                "final_training_time_ratio": final_seconds / tcn_result["model"]["final_training_seconds"],
                "checkpoint_size_ratio": model_path.stat().st_size / (report_root / "tcn/artifacts/tcn_model.pt").stat().st_size,
            },
            "epoch_selection": {
                "fit_units": fit_units,
                "early_stopping_units": stop_units,
                "validation_units_used": False,
                "clean_model_reinitialized_for_final_fit": True,
            },
        },
        "metrics": metrics,
        "comparison": comparison,
        "oof": {
            "generated": False,
            "included_in_current_fusion": False,
            "reason": str(config["oof"]["reason"]),
        },
        "provenance": provenance,
    }
    _write_json(output / "metrics.json", result)
    card = _model_card(
        final_model, manifest, result, model_path, prediction_artifact, unit_artifact,
    )
    _write_json(output / "model_card.json", card)
    _write_report(report_root / "transformer_report.md", result)
    return result


def _model_config(config: dict) -> TransformerConfig:
    model, training = config["model"], config["training"]
    return TransformerConfig(
        model_name="transformer_fd001", model_version=str(model["version"]),
        horizons=tuple(int(value) for value in model["horizons"]),
        sequence_length=int(model["sequence_length"]), d_model=int(model["d_model"]),
        num_heads=int(model["num_heads"]), num_layers=int(model["num_layers"]),
        feedforward_dim=int(model["feedforward_dim"]), dropout=float(model["dropout"]),
        activation=str(model["activation"]), batch_size=int(training["batch_size"]),
        learning_rate=float(training["learning_rate"]), weight_decay=float(training["weight_decay"]),
        max_epochs=int(training["max_epochs"]), patience=int(training["patience"]),
        min_delta=float(training["min_delta"]), random_seed=int(training["seed"]),
        torch_threads=int(training["torch_threads"]),
    )


def _comparison(report_root: Path, transformer_metrics: dict) -> dict[str, object]:
    prior = json.loads((report_root / "tcn/metrics.json").read_text(encoding="utf-8"))
    output: dict[str, object] = {}
    for horizon in (15, 30):
        key = str(horizon)
        output[key] = {
            "transformer": _metric_subset(transformer_metrics[key], "exploratory_classification"),
            "tcn": prior["comparison"][key]["tcn"],
            "xgboost": prior["comparison"][key]["xgboost"],
            "discrete_hazard": prior["comparison"][key]["discrete_hazard"],
        }
        transformer = output[key]["transformer"]
        output[key]["relative_to_tcn"] = {
            "brier_reduction_fraction": (prior["comparison"][key]["tcn"]["brier_score"] - transformer["brier_score"]) / prior["comparison"][key]["tcn"]["brier_score"],
            "pr_auc_change": transformer["pr_auc_average_precision"] - prior["comparison"][key]["tcn"]["pr_auc_average_precision"],
        }
        for reference in ("xgboost", "discrete_hazard"):
            baseline = prior["comparison"][key][reference]
            output[key][f"relative_to_{reference}"] = {
                "brier_reduction_fraction": (baseline["brier_score"] - transformer["brier_score"]) / baseline["brier_score"],
                "pr_auc_change": transformer["pr_auc_average_precision"] - baseline["pr_auc_average_precision"],
            }
    return output


def _provenance(config_path: Path, processed: Path, report_root: Path, manifest: dict,
                source_mode: str, feature_names: tuple[str, ...], fit_units: list[int],
                stop_units: list[int], selection_seconds: float, final_seconds: float,
                inference_seconds: float) -> dict[str, object]:
    paths = [config_path, processed / "split_manifest.json",
             report_root / "classical_ml/artifacts/feature_manifest.json"]
    if source_mode == "processed_parquet":
        paths.extend([processed / "train.parquet", processed / "validation.parquet"])
    return {
        "package_version": "0.13.0", "source_mode": source_mode,
        "training_partition": "train", "evaluation_partition": "validation",
        "early_stopping_partition": "grouped subset of train only",
        "partition_units": {"train": len(manifest["units"]["train"]),
                            "validation": len(manifest["units"]["validation"]),
                            "early_stopping_fit": fit_units,
                            "early_stopping_holdout": stop_units},
        "test_internal_read": False, "official_test_read": False, "official_rul_read": False,
        "feature_names": list(feature_names),
        "dependencies": {"python": platform.python_version(),
                         **{name: _package_version(name) for name in (
                             "numpy", "pandas", "pyarrow", "scikit-learn", "torch")}},
        "timing_seconds": {"model_selection_training": selection_seconds,
                           "final_training": final_seconds,
                           "validation_inference": inference_seconds},
        "input_sha256": {path.as_posix(): _sha(path) for path in paths},
        "manifest_source_sha256": manifest["source"]["sha256"],
    }


def _model_card(model: TransformerRiskModel, manifest: dict, result: dict,
                model_path: Path, prediction_artifact: dict, unit_artifact: dict) -> dict[str, object]:
    return {
        "model_name": model.config.model_name, "model_version": model.config.model_version,
        "model_family": "small causal Transformer Encoder",
        "architecture": {"sequence_length": model.config.sequence_length,
                         "d_model": model.config.d_model, "num_heads": model.config.num_heads,
                         "num_layers": model.config.num_layers,
                         "feedforward_dim": model.config.feedforward_dim,
                         "dropout": model.config.dropout,
                         "positional_representation": "fixed sinusoidal within lookback window",
                         "causal_attention_mask": True,
                         "joint_monotone_horizon_head": True,
                         "parameter_count": model.parameter_count()},
        "training_configuration": asdict(model.config),
        "training_summary": model.training_summary, "training_history": model.training_history,
        "dataset": {"name": "NASA C-MAPSS FD001", "training_partition": "train",
                    "validation_partition": "validation",
                    "train_units": len(manifest["units"]["train"]),
                    "validation_units": len(manifest["units"]["validation"]),
                    "test_internal_used": False, "official_test_used": False,
                    "official_rul_used": False},
        "input_contract": {"features": list(model.feature_names),
                           "sequence_rule": "left-padded history from one unit ending at t",
                           "forbidden": sorted(FORBIDDEN_INPUTS)},
        "output_contract": "P(T_i <= t+H | F_i,t, T_i>t), H in {15,30}",
        "metrics": result["metrics"], "comparison": result["comparison"],
        "memory": result["model"]["memory"],
        "cost_relative_to_tcn": result["model"]["cost_relative_to_tcn"],
        "shared_dependencies": ["FD001 telemetry", "terminal event and H15/H30 targets",
                                "unit partitions", "feature selection", "Python/PyTorch runtime"],
        "limitations": ["FD001 validation evidence only", "threshold 0.5 is exploratory",
                        "architectural diversity does not establish independence",
                        "analytical memory estimate excludes runtime allocator overhead",
                        "Transformer remains outside the current fusion without grouped OOF"],
        "artifacts": {"model": {"path": model_path.as_posix(), "sha256": _sha(model_path)},
                      "validation_predictions": prediction_artifact,
                      "validation_metrics_by_unit": unit_artifact},
        "provenance": result["provenance"],
    }


def _write_report(path: Path, result: dict) -> None:
    lines = [
        "# Transformer Encoder causal no FD001", "",
        "## Escopo", "",
        "Transformer pequeno, sem modelo de linguagem, treinado somente com prefixos da mesma unidade até t. Usa projeção linear, posição senoidal, máscara causal, máscara de padding e cabeça monotônica H15/H30.", "",
        "## Treinamento e custo", "",
        f"Época selecionada: {result['model']['selected_epoch']}. Dispositivo: {result['model']['training_device']}. Parâmetros: {result['model']['parameter_count']}.",
        f"Seleção: {result['model']['selection_training_seconds']:.3f} s; ajuste final: {result['model']['final_training_seconds']:.3f} s; inferência: {result['model']['validation_inference_seconds']:.3f} s ({result['model']['validation_inference_ms_per_origin']:.4f} ms/origem).",
        f"Memória de parâmetros float32: {result['model']['memory']['parameter_mebibytes_float32']:.4f} MiB; working set analítico batch=1: {result['model']['memory']['estimated_inference_working_mebibytes_batch_1']:.4f} MiB.", "",
        f"Contra a TCN: {result['model']['cost_relative_to_tcn']['parameter_count_ratio']:.2f}x parâmetros, {result['model']['cost_relative_to_tcn']['inference_latency_ratio']:.2f}x latência medida e {result['model']['cost_relative_to_tcn']['checkpoint_size_ratio']:.2f}x checkpoint.", "",
        "## Comparação em validation", "",
        "| H | Modelo | Brier | Log loss | ROC AUC | PR AUC | Recall |", "| ---: | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for horizon in (15, 30):
        for name in ("transformer", "tcn", "xgboost", "discrete_hazard"):
            item = result["comparison"][str(horizon)][name]
            recall = "n/a" if item["recall"] is None else f"{item['recall']:.6f}"
            lines.append(f"| {horizon} | {name} | {item['brier_score']:.6f} | {item['log_loss']:.6f} | {item['roc_auc']:.6f} | {item['pr_auc_average_precision']:.6f} | {recall} |")
    lines.extend(["", "## Métricas temporais", "",
                  "| H | Lead time mediano | Falsos alertas/unidade | Persistência média |", "| ---: | ---: | ---: | ---: |"])
    for horizon in (15, 30):
        alert = result["metrics"][str(horizon)]["alert_summary"]
        lines.append(f"| {horizon} | {alert['median_lead_time']:.2f} | {alert['mean_false_alert_episodes_per_unit']:.4f} | {alert['mean_alert_persistence']:.4f} |")
    lines.extend(["", "## Ganho relativo", ""])
    for horizon in (15, 30):
        gain = result["comparison"][str(horizon)]
        lines.append(
            f"H{horizon}: redução de Brier de {100*gain['relative_to_xgboost']['brier_reduction_fraction']:.2f}% contra XGBoost e {100*gain['relative_to_tcn']['brier_reduction_fraction']:.2f}% contra TCN; mudança de PR AUC de {gain['relative_to_xgboost']['pr_auc_change']:+.6f} e {gain['relative_to_tcn']['pr_auc_change']:+.6f}, respectivamente."
        )
    lines.extend(["", "## Coerência e limites", "",
                  f"Violações H15>H30: {result['metrics']['cross_horizon_coherence']['violations_short_greater_than_long']} em {result['metrics']['cross_horizon_coherence']['origins']} origens.",
                  "", "A arquitetura fornece diversidade analítica, não independência. Resultados limitados ao FD001; test_internal e teste oficial NASA não foram usados."])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _validate_config(config: dict) -> None:
    if tuple(config["model"]["horizons"]) != (15, 30):
        raise ValueError("Transformer stage requires horizons [15, 30]")
    fraction = float(config["training"]["early_stopping_fraction"])
    if not 0.0 < fraction < 0.5:
        raise ValueError("early stopping fraction must be in (0, 0.5)")
    if bool(config["oof"]["generate"]):
        raise ValueError("Transformer remains outside fusion in this stage")


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return torch.__version__ if name == "torch" else "unknown"


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True,
                               allow_nan=False, default=str) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/transformer.toml"))
    parser.add_argument("--processed", type=Path, default=Path("data/processed/fd001"))
    parser.add_argument("--raw", type=Path, default=Path("data/raw"))
    args = parser.parse_args()
    print(json.dumps(run_transformer(args.processed, args.raw, args.config),
                     ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
