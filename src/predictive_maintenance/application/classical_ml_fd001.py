"""Train causal Random Forest and XGBoost risk baselines for FD001."""

from __future__ import annotations

import argparse
from hashlib import sha256
from importlib.metadata import version
import json
import os
from pathlib import Path
import tempfile
import tomllib

os.environ.setdefault(
    "MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "predictive_maintenance_matplotlib")
)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance

from predictive_maintenance.core.records import FeatureRecord, TargetRecord
from predictive_maintenance.evaluation.probability import (
    evaluate_binary_probabilities,
    reliability_curve,
    threshold_metrics,
)
from predictive_maintenance.features.causal import CausalFeatureConfig, CausalTelemetryFeatures
from predictive_maintenance.models.ml.classical import (
    RandomForestRiskModel,
    TreeModelConfig,
    XGBoostRiskModel,
)


def grouped_unit_folds(unit_ids: list[int], *, folds: int, seed: int) -> list[list[int]]:
    """Return deterministic, disjoint holdout-unit lists covering all units once."""
    unique = np.asarray(sorted(set(int(value) for value in unit_ids)), dtype=int)
    if folds < 2 or folds > len(unique):
        raise ValueError("fold count must be between two and the number of units")
    shuffled = np.random.default_rng(seed).permutation(unique)
    result = [sorted(part.astype(int).tolist()) for part in np.array_split(shuffled, folds)]
    flattened = [unit for part in result for unit in part]
    if len(flattened) != len(set(flattened)) or set(flattened) != set(unique.tolist()):
        raise RuntimeError("grouped folds are not a disjoint cover")
    return result


def load_development_partitions(processed: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Read train and validation only; test_internal and official files are forbidden."""
    manifest_path = processed / "split_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("dataset") != "FD001" or manifest.get("source", {}).get("file") != "train_FD001.txt":
        raise ValueError("classical ML pipeline requires the FD001 internal split")
    names = ("train", "validation", "test_internal")
    declared = {name: set(int(value) for value in manifest["units"][name]) for name in names}
    if any(declared[a] & declared[b] for a, b in (
        ("train", "validation"), ("train", "test_internal"), ("validation", "test_internal"),
    )):
        raise ValueError("unit overlap in split manifest")
    frames = []
    for name in ("train", "validation"):
        frame = pd.read_parquet(processed / f"{name}.parquet")
        _validate_partition(frame)
        if set(frame.unit_id.astype(int)) != declared[name] or len(frame) != manifest["rows"][name]:
            raise ValueError(f"{name} does not match split manifest")
        frames.append(frame)
    return frames[0], frames[1], manifest


def run_classical_ml(
    processed: Path = Path("data/processed/fd001"),
    config_path: Path = Path("configs/classical_ml.toml"),
    report_root: Path = Path("reports"),
) -> dict[str, object]:
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    _validate_config(config)
    train, validation, split_manifest = load_development_partitions(processed)
    horizons = [int(value) for value in config["prediction"]["horizons"]]
    feature_config = CausalFeatureConfig(
        windows=tuple(config["features"]["windows"]),
        relative_epsilon=float(config["features"]["relative_epsilon"]),
        variance_epsilon=float(config["features"]["variance_epsilon"]),
        include_cycle=bool(config["features"]["include_cycle"]),
    )
    folds = grouped_unit_folds(
        train.unit_id.astype(int).tolist(), folds=int(config["cross_validation"]["folds"]),
        seed=int(config["cross_validation"]["seed"]),
    )
    output = report_root / "classical_ml"
    artifacts = output / "artifacts"
    models_dir = artifacts / "models"
    figures = output / "figures"
    for path in (artifacts, models_dir, figures):
        path.mkdir(parents=True, exist_ok=True)

    oof_frames: list[pd.DataFrame] = []
    permutation_rows: list[dict[str, object]] = []
    fold_manifest: list[dict[str, object]] = []
    all_train_units = set(train.unit_id.astype(int))
    for fold_index, holdout_units in enumerate(folds):
        holdout_set = set(holdout_units)
        fitting_units = all_train_units - holdout_set
        fold_train = train.loc[train.unit_id.isin(fitting_units)].reset_index(drop=True)
        fold_holdout = train.loc[train.unit_id.isin(holdout_set)].reset_index(drop=True)
        train_operational, _ = _operational_target(fold_train, horizons[0])
        engineer = CausalTelemetryFeatures(feature_config).fit_frame(
            fold_train, fit_mask=train_operational,
        )
        train_features = engineer.transform_frame(fold_train)
        holdout_features = engineer.transform_frame(fold_holdout)
        fold_manifest.append({
            "fold": fold_index, "fitting_units": sorted(fitting_units),
            "holdout_units": holdout_units, "overlap": [],
            "feature_count": len(engineer.feature_names),
            "dropped_constant_columns": list(engineer.dropped_constant_columns),
        })
        for horizon in horizons:
            train_mask, train_labels = _operational_target(fold_train, horizon)
            holdout_mask, holdout_labels = _operational_target(fold_holdout, horizon)
            fit_records = _feature_records(train_features.loc[train_mask], engineer.feature_names)
            target_records = _target_records(
                fold_train.loc[train_mask, ["unit_id", "cycle"]], train_labels, horizon,
            )
            holdout_records = _feature_records(
                holdout_features.loc[holdout_mask], engineer.feature_names,
            )
            for algorithm in ("random_forest", "xgboost"):
                model = _make_model(algorithm, horizon, engineer.feature_names, config,
                                    seed_offset=fold_index)
                model.fit(fit_records, target_records)
                predictions = model.predict_risk(holdout_records, horizon=horizon)
                predicted = _prediction_frame(predictions)
                predicted["label"] = holdout_labels.astype("int8")
                predicted["fold"] = fold_index
                predicted["partition"] = "train_oof"
                predicted["algorithm"] = algorithm
                oof_frames.append(predicted)
                if algorithm == "xgboost":
                    matrix = holdout_features.loc[holdout_mask, engineer.feature_names].to_numpy(dtype=float)
                    importance = permutation_importance(
                        model.estimator, matrix, holdout_labels,
                        scoring="neg_brier_score",
                        n_repeats=int(config["importance"]["permutation_repeats"]),
                        random_state=int(config["importance"]["seed"]) + fold_index + horizon,
                        n_jobs=1,
                    )
                    for name, mean, std in zip(
                        engineer.feature_names, importance.importances_mean,
                        importance.importances_std, strict=True,
                    ):
                        permutation_rows.append({
                            "horizon": horizon, "fold": fold_index, "feature": name,
                            "importance_mean": float(mean), "importance_std": float(std),
                        })

    oof = pd.concat(oof_frames, ignore_index=True)
    _validate_oof_coverage(oof, train, horizons)
    oof_path = artifacts / "train_oof_predictions.parquet"
    oof.to_parquet(oof_path, index=False)
    _write_json(artifacts / "fold_manifest.json", {
        "strategy": "deterministic shuffled unit folds",
        "fold_count": len(folds), "seed": int(config["cross_validation"]["seed"]),
        "folds": fold_manifest, "test_internal_read": False, "official_test_read": False,
    })

    permutation_frame = pd.DataFrame(permutation_rows)
    permutation_summary = (permutation_frame.groupby(["horizon", "feature"], as_index=False)
                           .agg(importance_mean=("importance_mean", "mean"),
                                between_fold_std=("importance_mean", "std"),
                                folds=("fold", "nunique")))
    permutation_summary.to_parquet(artifacts / "xgboost_permutation_importance_oof.parquet", index=False)

    full_operational, _ = _operational_target(train, horizons[0])
    final_engineer = CausalTelemetryFeatures(feature_config).fit_frame(
        train, fit_mask=full_operational,
    )
    engineered_train = final_engineer.transform_frame(train)
    engineered_validation = final_engineer.transform_frame(validation)
    feature_artifact = artifacts / "causal_feature_engineer.json"
    final_engineer.save(feature_artifact)
    _write_json(artifacts / "feature_manifest.json", final_engineer.manifest())

    validation_frames: list[pd.DataFrame] = []
    gain_rows: list[dict[str, object]] = []
    impurity_rows: list[dict[str, object]] = []
    model_artifacts: dict[str, dict[str, object]] = {"random_forest": {}, "xgboost": {}}
    for horizon in horizons:
        train_mask, train_labels = _operational_target(train, horizon)
        validation_mask, validation_labels = _operational_target(validation, horizon)
        fit_records = _feature_records(engineered_train.loc[train_mask], final_engineer.feature_names)
        targets = _target_records(train.loc[train_mask, ["unit_id", "cycle"]], train_labels, horizon)
        validation_records = _feature_records(
            engineered_validation.loc[validation_mask], final_engineer.feature_names,
        )
        for algorithm in ("random_forest", "xgboost"):
            model = _make_model(algorithm, horizon, final_engineer.feature_names, config)
            model.fit(fit_records, targets)
            predictions = model.predict_risk(validation_records, horizon=horizon)
            predicted = _prediction_frame(predictions)
            predicted["label"] = validation_labels.astype("int8")
            predicted["partition"] = "validation"
            predicted["algorithm"] = algorithm
            validation_frames.append(predicted)
            model_path = models_dir / f"{algorithm}_h{horizon}.joblib"
            model.save(model_path)
            loaded = type(model).load(model_path)
            if loaded.predict_risk(validation_records[:10], horizon=horizon) != predictions[:10]:
                raise RuntimeError(f"save/load changed {algorithm} H={horizon} predictions")
            model_artifacts[algorithm][str(horizon)] = {
                "path": model_path.as_posix(), "sha256": model.artifact_hash(model_path),
                "training_summary": model.training_summary,
            }
            values = np.asarray(model.estimator.feature_importances_, dtype=float)
            if algorithm == "random_forest":
                for name, value in zip(final_engineer.feature_names, values, strict=True):
                    impurity_rows.append({"horizon": horizon, "feature": name,
                                          "importance": float(value)})
            else:
                raw_gain = model.estimator.get_booster().get_score(importance_type="gain")
                for index, name in enumerate(final_engineer.feature_names):
                    gain_rows.append({"horizon": horizon, "feature": name,
                                      "gain": float(raw_gain.get(f"f{index}", 0.0))})

    validation_predictions = pd.concat(validation_frames, ignore_index=True)
    validation_path = artifacts / "validation_predictions.parquet"
    validation_predictions.to_parquet(validation_path, index=False)
    pd.DataFrame(gain_rows).to_parquet(artifacts / "xgboost_gain_importance.parquet", index=False)
    pd.DataFrame(impurity_rows).to_parquet(artifacts / "random_forest_impurity_importance.parquet", index=False)

    metrics, per_unit = _evaluate_outputs(
        oof, validation_predictions, config,
    )
    per_unit_path = artifacts / "metrics_by_unit.parquet"
    per_unit.to_parquet(per_unit_path, index=False)
    weibull_comparison = _weibull_validation_comparison(
        report_root, validation, horizons, float(config["evaluation"]["exploratory_threshold"]),
        int(config["evaluation"]["reliability_bins"]),
        float(config["evaluation"]["log_loss_epsilon"]),
    )
    metrics["weibull_validation_comparison"] = weibull_comparison

    coherence = _horizon_coherence(validation_predictions, horizons)
    metrics["cross_horizon_coherence"] = coherence
    provenance = {
        "package_version": version("adaptive-predictive-maintenance"),
        "dependencies": {name: version(name) for name in
                         ("numpy", "pandas", "scikit-learn", "xgboost", "joblib")},
        "configuration": config,
        "input_sha256": {
            path.as_posix(): _hash(path) for path in (
                processed / "train.parquet", processed / "validation.parquet",
                processed / "split_manifest.json", config_path,
            )
        },
        "training_partition": "train", "evaluation_partition": "validation",
        "test_internal_read": False, "official_test_read": False,
        "official_rul_read": False,
    }
    metrics_payload = {"provenance": provenance, "results": metrics}
    _write_json(output / "metrics.json", metrics_payload)

    _write_model_cards(
        output, config, split_manifest, final_engineer, model_artifacts, metrics,
        feature_artifact, oof_path, validation_path, per_unit_path, provenance,
    )
    _plot_reliability_comparison(validation_predictions, validation, weibull_comparison,
                                 horizons, figures, config)
    _plot_importances(permutation_summary, pd.DataFrame(gain_rows), horizons, figures)
    _write_report(report_root / "classical_ml_report.md", metrics, final_engineer,
                  model_artifacts, permutation_summary, pd.DataFrame(gain_rows),
                  oof_path, validation_path, per_unit_path, coherence, config)
    return {
        "feature_count": len(final_engineer.feature_names),
        "dropped_constant_columns": list(final_engineer.dropped_constant_columns),
        "oof_rows": len(oof), "validation_prediction_rows": len(validation_predictions),
        "metrics": metrics, "artifacts": model_artifacts,
    }


def _make_model(
    algorithm: str, horizon: int, feature_names: tuple[str, ...], config: dict,
    *, seed_offset: int = 0,
):
    model_class = RandomForestRiskModel if algorithm == "random_forest" else XGBoostRiskModel
    model_name = f"{algorithm}_fd001_h{horizon}"
    return model_class(TreeModelConfig(
        model_name=model_name, model_version=str(config["models"]["version"]),
        horizon=horizon, random_seed=int(config["models"]["random_seed"]) + seed_offset,
        parameters=dict(config[algorithm]),
    ), feature_names)


def _operational_target(frame: pd.DataFrame, horizon: int) -> tuple[np.ndarray, np.ndarray]:
    final_cycle = frame.groupby("unit_id", sort=False).cycle.transform("max")
    rul = final_cycle - frame.cycle
    mask = rul.gt(0).to_numpy(dtype=bool)
    return mask, rul.loc[mask].le(horizon).to_numpy(dtype=np.int8)


def _feature_records(frame: pd.DataFrame, feature_names: tuple[str, ...]) -> list[FeatureRecord]:
    matrix = frame.loc[:, feature_names].to_numpy(dtype=float)
    units = frame.unit_id.to_numpy()
    cycles = frame.cycle.to_numpy()
    return [FeatureRecord(str(int(unit)), int(cycle), dict(zip(feature_names, row, strict=True)))
            for unit, cycle, row in zip(units, cycles, matrix, strict=True)]


def _target_records(keys: pd.DataFrame, labels: np.ndarray, horizon: int) -> list[TargetRecord]:
    return [TargetRecord(str(int(row.unit_id)), int(row.cycle), {
        "horizon": horizon, "failure_within_horizon": int(label),
    }) for row, label in zip(keys.itertuples(index=False), labels, strict=True)]


def _prediction_frame(predictions) -> pd.DataFrame:
    return pd.DataFrame([{
        "unit_id": int(item.unit_id), "cycle": item.cycle, "horizon": item.horizon,
        "risk_score": item.risk_score, "survival_score": item.survival_score,
        "health_score": item.health_score, "model_name": item.model_name,
        "model_version": item.model_version, "prediction_status": item.prediction_status,
        "input_validity": item.input_validity,
    } for item in predictions])


def _evaluate_outputs(
    oof: pd.DataFrame, validation: pd.DataFrame, config: dict,
) -> tuple[dict[str, object], pd.DataFrame]:
    threshold = float(config["evaluation"]["exploratory_threshold"])
    bins = int(config["evaluation"]["reliability_bins"])
    epsilon = float(config["evaluation"]["log_loss_epsilon"])
    metrics: dict[str, object] = {}
    unit_rows = []
    for partition, source in (("train_oof", oof), ("validation", validation)):
        metrics[partition] = {}
        for algorithm in ("random_forest", "xgboost"):
            metrics[partition][algorithm] = {}
            for horizon in sorted(source.horizon.unique()):
                subset = source.loc[(source.algorithm == algorithm) & (source.horizon == horizon)]
                probability = evaluate_binary_probabilities(
                    subset.label, subset.risk_score, reliability_bins=bins,
                    log_loss_epsilon=epsilon,
                )
                classification = threshold_metrics(
                    subset.label, subset.risk_score, threshold=threshold,
                )
                metrics[partition][algorithm][str(int(horizon))] = {
                    **probability, "exploratory_classification": classification,
                    "unit_count": int(subset.unit_id.nunique()),
                }
                for unit_id, unit in subset.groupby("unit_id", sort=True):
                    unit_probability = evaluate_binary_probabilities(
                        unit.label, unit.risk_score, reliability_bins=bins,
                        log_loss_epsilon=epsilon,
                    )
                    unit_classification = threshold_metrics(
                        unit.label, unit.risk_score, threshold=threshold,
                    )
                    unit_rows.append({
                        "partition": partition, "algorithm": algorithm,
                        "horizon": int(horizon), "unit_id": int(unit_id),
                        **{key: value for key, value in unit_probability.items()
                           if key != "reliability_curve"},
                        **{f"classification_{key}": value for key, value in unit_classification.items()},
                    })
    return metrics, pd.DataFrame(unit_rows)


def _weibull_validation_comparison(
    report_root: Path, validation: pd.DataFrame, horizons: list[int], threshold: float,
    bins: int, epsilon: float,
) -> dict[str, object]:
    path = report_root / "weibull" / "artifacts" / "validation_predictions.parquet"
    predictions = pd.read_parquet(path)
    result = {}
    for horizon in horizons:
        mask, labels = _operational_target(validation, horizon)
        keys = validation.loc[mask, ["unit_id", "cycle"]].copy()
        keys["label"] = labels
        subset = predictions.loc[predictions.horizon == horizon]
        merged = keys.merge(subset[["unit_id", "cycle", "risk_score"]],
                            on=["unit_id", "cycle"], how="inner", validate="one_to_one")
        if len(merged) != len(keys):
            raise ValueError("Weibull validation artifact does not cover current validation keys")
        result[str(horizon)] = {
            **evaluate_binary_probabilities(merged.label, merged.risk_score,
                                            reliability_bins=bins, log_loss_epsilon=epsilon),
            "exploratory_classification": threshold_metrics(
                merged.label, merged.risk_score, threshold=threshold,
            ),
        }
    return result


def _horizon_coherence(predictions: pd.DataFrame, horizons: list[int]) -> dict[str, object]:
    if len(horizons) != 2 or horizons != sorted(horizons):
        return {"evaluated": False, "reason": "requires two ordered horizons"}
    short, long = horizons
    rows = {}
    for algorithm in ("random_forest", "xgboost"):
        pivot = predictions.loc[predictions.algorithm == algorithm].pivot(
            index=["unit_id", "cycle"], columns="horizon", values="risk_score",
        )
        difference = pivot[short] - pivot[long]
        rows[algorithm] = {
            "short_horizon": short, "long_horizon": long,
            "violations_short_greater_than_long": int((difference > 1e-12).sum()),
            "fraction": float((difference > 1e-12).mean()),
            "maximum_violation": float(max(0.0, difference.max())),
        }
    return {"evaluated": True, "by_algorithm": rows}


def _write_model_cards(
    output: Path, config: dict, split_manifest: dict, engineer: CausalTelemetryFeatures,
    model_artifacts: dict, metrics: dict, feature_artifact: Path, oof_path: Path,
    validation_path: Path, per_unit_path: Path, provenance: dict,
) -> None:
    for algorithm in ("random_forest", "xgboost"):
        card = {
            "model_name": f"{algorithm}_fd001",
            "model_version": config["models"]["version"],
            "dataset": {
                "name": "NASA C-MAPSS FD001", "training_partition": "train",
                "validation_partition": "validation", "split_seed": split_manifest["split"]["seed"],
                "train_units": len(split_manifest["units"]["train"]),
                "validation_units": len(split_manifest["units"]["validation"]),
                "test_internal_used": False, "official_test_used": False,
            },
            "configuration": {
                "algorithm": config[algorithm], "cross_validation": config["cross_validation"],
                "weighting": "inverse unit row count multiplied by inverse class frequency",
                "exploratory_threshold": config["evaluation"]["exploratory_threshold"],
            },
            "features": engineer.manifest(),
            "horizons": config["prediction"]["horizons"],
            "input_contract": "FeatureRecord with the exact finite feature schema; features use history through t only",
            "output_contract": "RiskPrediction probability P(T_i <= t+H | F_i,t, T_i>t)",
            "dependencies": provenance["dependencies"],
            "shared_dependencies": [
                "same FD001 train/validation split", "same target construction",
                "same causal feature code and final preprocessor", "same Python/NumPy/pandas runtime",
                "same evaluation implementation",
            ],
            "limitations": [
                "benchmark-only evidence and no claim of transfer to physical assets",
                "dependent rows within units; grouped OOF mitigates but does not remove temporal dependence",
                "probabilities are uncalibrated estimator outputs",
                "threshold 0.5 is exploratory and is not an alert policy",
                "separate horizon models can violate cross-horizon probability ordering",
                "common data/preprocessing errors can affect both tree families",
                "permutation importance is predictive diagnostic, not a causal effect",
            ],
            "metrics": {
                "train_oof": metrics["train_oof"][algorithm],
                "validation": metrics["validation"][algorithm],
            },
            "artifacts": {
                "models": model_artifacts[algorithm],
                "feature_engineer": {"path": feature_artifact.as_posix(),
                                     "sha256": _hash(feature_artifact)},
                "train_oof_predictions": oof_path.as_posix(),
                "validation_predictions": validation_path.as_posix(),
                "metrics_by_unit": per_unit_path.as_posix(),
            },
            "provenance": provenance,
        }
        _write_json(output / f"{algorithm}_model_card.json", card)


def _plot_reliability_comparison(
    predictions: pd.DataFrame, validation: pd.DataFrame, weibull: dict,
    horizons: list[int], figures: Path, config: dict,
) -> None:
    fig, axes = plt.subplots(1, len(horizons), figsize=(6 * len(horizons), 5), squeeze=False)
    bins = int(config["evaluation"]["reliability_bins"])
    for axis, horizon in zip(axes[0], horizons, strict=True):
        axis.plot([0, 1], [0, 1], "--", color="0.5", label="ideal")
        for algorithm, label in (("random_forest", "Random Forest"), ("xgboost", "XGBoost")):
            subset = predictions.loc[(predictions.algorithm == algorithm) & (predictions.horizon == horizon)]
            curve = reliability_curve(subset.label, subset.risk_score, bins)
            axis.plot([row["mean_predicted"] for row in curve],
                      [row["observed_frequency"] for row in curve], marker="o", label=label)
        curve = weibull[str(horizon)]["reliability_curve"]
        axis.plot([row["mean_predicted"] for row in curve],
                  [row["observed_frequency"] for row in curve], marker="o", label="Weibull")
        axis.set(title=f"Validation H={horizon}", xlabel="Risco médio previsto",
                 ylabel="Frequência observada", xlim=(0, 1), ylim=(0, 1))
        axis.legend()
    _save(fig, figures / "reliability_comparison.png")


def _plot_importances(
    permutation_frame: pd.DataFrame, gain_frame: pd.DataFrame,
    horizons: list[int], figures: Path,
) -> None:
    for horizon in horizons:
        fig, axes = plt.subplots(1, 2, figsize=(14, 7))
        permutation = permutation_frame.loc[permutation_frame.horizon == horizon].nlargest(
            15, "importance_mean"
        ).sort_values("importance_mean")
        gain = gain_frame.loc[gain_frame.horizon == horizon].nlargest(15, "gain").sort_values("gain")
        axes[0].barh(permutation.feature, permutation.importance_mean)
        axes[0].set_title("XGBoost — permutation OOF (Δ Brier)")
        axes[1].barh(gain.feature, gain.gain)
        axes[1].set_title("XGBoost — gain no treino completo")
        _save(fig, figures / f"xgboost_importance_h{horizon}.png")


def _write_report(
    path: Path, metrics: dict, engineer: CausalTelemetryFeatures, model_artifacts: dict,
    permutation_frame: pd.DataFrame, gain_frame: pd.DataFrame, oof_path: Path,
    validation_path: Path, per_unit_path: Path, coherence: dict, config: dict,
) -> None:
    threshold = config["evaluation"]["exploratory_threshold"]
    lines = [
        "# Random Forest e XGBoost com atributos causais — FD001", "",
        "## Escopo e isolamento", "",
        "Modelos separados para H=15 e H=30, ajustados exclusivamente nos 70 motores de treino.",
        "Validation contém 15 motores e é usada apenas para avaliação. Test_internal, teste oficial",
        "NASA e RUL oficial não foram lidos. Nenhuma política operacional ou calibração foi ajustada.", "",
        "## Atributos", "",
        f"Foram gerados {len(engineer.feature_names)} atributos. Janelas causais: {list(engineer.config.windows)}.",
        f"Colunas constantes removidas por ajuste no treino: {', '.join(engineer.dropped_constant_columns)}.",
        "Cada janela é alinhada à direita e termina em t. Delta, diferença relativa, estatísticas móveis,",
        "inclinação e variação absoluta acumulada reiniciam por unit_id. age_cycle é idade causal explícita.",
        "RUL, vida normalizada, T_i, máximos de trajetória e rótulos nunca entram no schema.", "",
        "## Validação cruzada agrupada", "",
        "Cinco folds determinísticos por unit_id reajustam seleção, imputação e modelo. Cada motor aparece",
        "uma vez como holdout OOF e nunca simultaneamente no ajuste do mesmo fold. O peso de cada linha",
        "combina balanceamento por unidade e por classe.", "",
        "## Comparação em validation", "",
        f"Precision, recall e F1 usam threshold fixo exploratório {threshold}; não é threshold de alerta.", "",
        "| H | Modelo | Brier | Log loss | ROC AUC | PR AUC | Precision | Recall | F1 |", 
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    display = [("weibull", metrics["weibull_validation_comparison"]),
               ("random_forest", metrics["validation"]["random_forest"]),
               ("xgboost", metrics["validation"]["xgboost"])]
    for horizon in config["prediction"]["horizons"]:
        for algorithm, source in display:
            row = source[str(horizon)]
            classification = row["exploratory_classification"]
            lines.append(
                f"| {horizon} | {algorithm} | {row['brier_score']:.6f} | {row['log_loss']:.6f} | "
                f"{row['roc_auc']:.6f} | {row['pr_auc_average_precision']:.6f} | "
                f"{classification['precision']:.6f} | {classification['recall']:.6f} | {classification['f1']:.6f} |"
            )
    lines += ["", "Métricas por linha têm dependência intraunidade; o artefato por unidade deve ser consultado.",
              "Os horizontes têm prevalências diferentes e não devem ser ranqueados entre si por Brier/log loss.", "",
              "## Features mais relevantes", ""]
    for horizon in config["prediction"]["horizons"]:
        permutation = permutation_frame.loc[permutation_frame.horizon == horizon].nlargest(10, "importance_mean")
        gain = gain_frame.loc[gain_frame.horizon == horizon].nlargest(10, "gain")
        lines += [f"### H={horizon}", "",
                  "Permutation OOF: " + ", ".join(f"{r.feature} ({r.importance_mean:.6g})" for r in permutation.itertuples()), "",
                  "Gain XGBoost: " + ", ".join(f"{r.feature} ({r.gain:.6g})" for r in gain.itertuples()), ""]
    lines += ["A importância por permutação usa holdouts OOF e Δ Brier; gain usa o ajuste final do treino.",
              "Features correlacionadas dividem importância e nenhuma medida implica causalidade física.", "",
              "## Coerência entre horizontes", "", json.dumps(coherence, ensure_ascii=False), "",
              "Modelos separados não impõem p(H=15) ≤ p(H=30); violações são registradas, não corrigidas",
              "por pós-processamento nesta etapa.", "", "## Leakage auditado", "",
              "O schema proíbe campos retrospectivos. Testes por prefixo demonstram que alterar ou anexar",
              "ciclos futuros não muda atributos já emitidos. Folds não compartilham unidades e cada fold",
              "reajusta seleção/imputação. A permutation importance não usa validation.", "",
              "Limite: mediana global de imputação é estado aprendido no treino do fold, não informação online",
              "do ativo. age_cycle pode funcionar como atalho populacional por idade e é mantido explícito.", "",
              "## Dependências compartilhadas", "",
              "Random Forest e XGBoost compartilham dados, split, alvos, gerador de features, imputação, runtime",
              "e avaliação. Uma falha comum nesses componentes pode afetar ambos; diversidade de algoritmo",
              "não constitui redundância independente. Concordância não prova correção.", "",
              "## Artefatos", "",
              f"- OOF de treino: `{oof_path.as_posix()}`.",
              f"- Previsões de validation: `{validation_path.as_posix()}`.",
              f"- Métricas por unidade: `{per_unit_path.as_posix()}`.",
              "- Model cards: `reports/classical_ml/random_forest_model_card.json` e `xgboost_model_card.json`.",
              "- Modelos finais: `reports/classical_ml/artifacts/models`.",
              "- Importâncias: Parquets em `reports/classical_ml/artifacts`.", "",
              "![Calibração](classical_ml/figures/reliability_comparison.png)", "",
              "![Importância H15](classical_ml/figures/xgboost_importance_h15.png)", "",
              "![Importância H30](classical_ml/figures/xgboost_importance_h30.png)", "",
              "## Limitações", "",
              "Probabilidades não receberam calibração adicional; threshold 0,5 é apenas diagnóstico.",
              "Validation já integra o ciclo de desenvolvimento e não é evidência final. Resultados FD001",
              "não demonstram desempenho industrial, independência entre modelos ou benefício de manutenção.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def _validate_oof_coverage(oof: pd.DataFrame, train: pd.DataFrame, horizons: list[int]) -> None:
    expected = sum(_operational_target(train, horizon)[0].sum() for horizon in horizons) * 2
    if len(oof) != expected or oof.duplicated(["algorithm", "horizon", "unit_id", "cycle"]).any():
        raise RuntimeError("OOF predictions do not provide exactly one score per eligible key/model")
    if set(oof.prediction_status) != {"available"} or set(oof.input_validity) != {"valid"}:
        raise RuntimeError("OOF predictions contain unavailable or invalid rows")


def _validate_partition(frame: pd.DataFrame) -> None:
    expected = {"unit_id", "cycle", *(f"setting_{index}" for index in range(1, 4)),
                *(f"sensor_{index}" for index in range(1, 22))}
    if frame.empty or set(frame.columns) != expected:
        raise ValueError("FD001 partition must contain the exact 26-column schema")
    values = frame.to_numpy(dtype=float)
    if not np.isfinite(values).all() or frame.duplicated(["unit_id", "cycle"]).any():
        raise ValueError("FD001 partition contains invalid values or duplicate keys")
    for _, unit in frame.groupby("unit_id", sort=False):
        if unit.cycle.tolist() != list(range(1, len(unit) + 1)):
            raise ValueError("FD001 partition trajectories must be consecutive 1..N")


def _validate_config(config: dict) -> None:
    required = {"models", "features", "cross_validation", "prediction",
                "random_forest", "xgboost", "evaluation", "importance"}
    if set(config) != required:
        raise ValueError("classical ML configuration sections are incomplete")
    horizons = config["prediction"].get("horizons")
    if horizons != [15, 30]:
        raise ValueError("this FD001 stage requires horizons 15 and 30")
    threshold = config["evaluation"].get("exploratory_threshold")
    if not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
        raise ValueError("exploratory threshold must be within [0, 1]")


def _save(fig: plt.Figure, path: Path) -> None:
    fig.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                               indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--processed-dir", type=Path, default=Path("data/processed/fd001"))
    parser.add_argument("--config", type=Path, default=Path("configs/classical_ml.toml"))
    parser.add_argument("--reports-dir", type=Path, default=Path("reports"))
    args = parser.parse_args()
    print(json.dumps(run_classical_ml(args.processed_dir, args.config, args.reports_dir),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
