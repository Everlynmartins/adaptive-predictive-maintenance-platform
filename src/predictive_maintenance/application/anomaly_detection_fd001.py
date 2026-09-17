"""Fit and evaluate a train-only healthy-region Isolation Forest for FD001."""

from __future__ import annotations

import argparse
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import platform
import os
import tempfile
import tomllib

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "predictive_maintenance_matplotlib"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from predictive_maintenance.application.classical_ml_fd001 import (
    _feature_records, grouped_unit_folds, load_development_partitions,
)
from predictive_maintenance.features.causal import CausalFeatureConfig, CausalTelemetryFeatures
from predictive_maintenance.models.anomaly.isolation_forest import (
    IsolationForestAnomalyDetector, IsolationForestConfig,
)


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _with_rul(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["RUL"] = result.groupby("unit_id", sort=False).cycle.transform("max") - result.cycle
    # Preserve original row indexes so transformed causal features align by key.
    return result.loc[result.RUL.gt(0)].copy()


def _healthy_mask(frame: pd.DataFrame, minimum_rul_exclusive: int) -> np.ndarray:
    if type(minimum_rul_exclusive) is not int or minimum_rul_exclusive < 1:
        raise ValueError("healthy minimum RUL must be a positive integer")
    mask = frame.RUL.gt(minimum_rul_exclusive).to_numpy(dtype=bool)
    if mask.sum() < 2 or frame.loc[mask, "unit_id"].nunique() < 2:
        raise ValueError("healthy region does not contain sufficient observations and units")
    return mask


def _fit_fold_detector(frame: pd.DataFrame, feature_config: CausalFeatureConfig,
                       model_config: IsolationForestConfig, healthy_limit: int):
    operational = _with_rul(frame)
    healthy = _healthy_mask(operational, healthy_limit)
    # The only use of RUL here is train-only selection of the healthy fitting population.
    telemetry = frame.reset_index(drop=True)
    fit_mask = telemetry.index.isin(operational.loc[healthy].index)
    engineer = CausalTelemetryFeatures(feature_config).fit_frame(telemetry, fit_mask=fit_mask)
    engineered = engineer.transform_frame(telemetry)
    operational_features = engineered.loc[telemetry.index.isin(operational.index)].copy()
    operational_features["RUL"] = operational.RUL.to_numpy()
    records = _feature_records(operational_features, engineer.feature_names)
    detector = IsolationForestAnomalyDetector(engineer.feature_names, model_config).fit(
        [record for record, selected in zip(records, healthy, strict=True) if selected]
    )
    return engineer, detector, operational_features, records, healthy


def _score_frame(records, detector: IsolationForestAnomalyDetector, metadata: pd.DataFrame) -> pd.DataFrame:
    predictions = detector.detect(records)
    rows = []
    for record, prediction, source in zip(records, predictions, metadata.itertuples(index=False), strict=True):
        rows.append({"unit_id": int(record.unit_id), "cycle": record.cycle, "RUL": int(source.RUL),
                     "anomaly_score": prediction.anomaly_score, "model_name": prediction.model_name,
                     "model_version": prediction.model_version,
                     "prediction_status": prediction.prediction_status,
                     "input_validity": prediction.input_validity})
    result = pd.DataFrame(rows)
    if result.anomaly_score.isna().any() or not np.isfinite(result.anomaly_score).all():
        raise RuntimeError("available anomaly scoring must be finite")
    return result


def _validate_oof(frame: pd.DataFrame, train: pd.DataFrame) -> None:
    expected = len(train) - train.unit_id.nunique()
    if len(frame) != expected or frame.duplicated(["unit_id", "cycle"]).any():
        raise RuntimeError("anomaly OOF scores do not cover each operational train key once")
    if frame.unit_id.nunique() != train.unit_id.nunique():
        raise RuntimeError("anomaly OOF does not cover every training unit")


def _analysis(scores: pd.DataFrame, healthy_limit: int, near_event_limit: int,
              diagnostic_quantile: float, representatives: int) -> dict[str, object]:
    if not 0 < diagnostic_quantile < 1:
        raise ValueError("diagnostic healthy quantile must be in (0, 1)")
    score = scores.anomaly_score
    healthy = scores.RUL.gt(healthy_limit)
    near = scores.RUL.le(near_event_limit)
    # Score is an empirical healthy percentile. This is an analysis reference, never a policy threshold.
    diagnostic_cutoff = float(diagnostic_quantile)
    summary = {
        "healthy_region": _distribution(scores.loc[healthy]),
        "near_event_region": _distribution(scores.loc[near]),
        "all_operational": _distribution(scores),
        "analysis_reference": {"healthy_score_quantile": diagnostic_quantile,
                               "anomaly_score_cutoff": diagnostic_cutoff,
                               "meaning": "diagnostic reference only; not an operational alert threshold"},
        "false_positive_reference": {
            "count": int((healthy & score.ge(diagnostic_cutoff)).sum()),
            "fraction_of_healthy_rows": float((healthy & score.ge(diagnostic_cutoff)).sum() / healthy.sum()),
        },
    }
    unit_rows, early, false_positive = [], [], []
    for unit, values in scores.groupby("unit_id", sort=True):
        values = values.sort_values("cycle")
        flagged = values.loc[values.anomaly_score.ge(diagnostic_cutoff)]
        unit_rows.append({"unit_id": int(unit), "n_cycles": int(len(values)),
                          "mean_anomaly_score": float(values.anomaly_score.mean()),
                          "max_anomaly_score": float(values.anomaly_score.max()),
                          "first_diagnostic_cycle": int(flagged.cycle.iloc[0]) if len(flagged) else None,
                          "lead_cycles_at_first_diagnostic": int(flagged.RUL.iloc[0]) if len(flagged) else None})
        # An early analytical indication must occur outside the near-event region.
        candidates = flagged.loc[flagged.RUL.gt(near_event_limit)]
        if len(candidates):
            first = candidates.iloc[0]
            early.append({"unit_id": int(unit), "cycle": int(first.cycle), "RUL": int(first.RUL),
                          "anomaly_score": float(first.anomaly_score)})
    fp = scores.loc[healthy & score.ge(diagnostic_cutoff)].sort_values("anomaly_score", ascending=False)
    for row in fp.head(representatives).itertuples(index=False):
        false_positive.append({"unit_id": int(row.unit_id), "cycle": int(row.cycle),
                               "RUL": int(row.RUL), "anomaly_score": float(row.anomaly_score)})
    return summary | {"by_unit": unit_rows,
                      "early_indications": sorted(early, key=lambda r: (-r["RUL"], r["unit_id"]))[:representatives],
                      "healthy_region_high_scores": false_positive}


def _distribution(frame: pd.DataFrame) -> dict[str, object]:
    values = frame.anomaly_score.to_numpy(dtype=float)
    return {"rows": int(len(frame)), "units": int(frame.unit_id.nunique()),
            "mean": float(values.mean()), "median": float(np.median(values)),
            "q05": float(np.quantile(values, .05)), "q95": float(np.quantile(values, .95)),
            "min": float(values.min()), "max": float(values.max())}


def _plots(scores: pd.DataFrame, root: Path, healthy_limit: int, near_event_limit: int,
           representatives: int) -> None:
    figures = root / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    healthy, near = scores.loc[scores.RUL.gt(healthy_limit)], scores.loc[scores.RUL.le(near_event_limit)]
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(healthy.anomaly_score, bins=30, alpha=.7, label=f"healthy RUL>{healthy_limit}")
    ax.hist(near.anomaly_score, bins=30, alpha=.7, label=f"near event RUL≤{near_event_limit}")
    ax.set(xlabel="Anomaly score (healthy empirical percentile)", ylabel="Rows")
    ax.legend(); fig.tight_layout(); fig.savefig(figures / "score_distribution.png", dpi=150); plt.close(fig)
    binned = scores.assign(rul_bin=(scores.RUL // 10) * 10).groupby("rul_bin", as_index=False).agg(
        mean_score=("anomaly_score", "mean"), q10=("anomaly_score", lambda v: v.quantile(.1)),
        q90=("anomaly_score", lambda v: v.quantile(.9)), rows=("anomaly_score", "size"))
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(binned.rul_bin, binned.mean_score, marker="o", label="mean")
    ax.fill_between(binned.rul_bin, binned.q10, binned.q90, alpha=.2, label="P10–P90")
    ax.invert_xaxis(); ax.set(xlabel="RUL retrospective (cycles; analysis only)", ylabel="Anomaly score")
    ax.legend(); fig.tight_layout(); fig.savefig(figures / "score_by_rul.png", dpi=150); plt.close(fig)
    selected = scores.groupby("unit_id").anomaly_score.mean().sort_values().index.to_list()
    chosen = selected[:max(1, representatives // 2)] + selected[-max(1, representatives - representatives // 2):]
    fig, ax = plt.subplots(figsize=(9, 5))
    for unit in chosen:
        part = scores.loc[scores.unit_id.eq(unit)].sort_values("cycle")
        ax.plot(part.cycle, part.anomaly_score, label=f"unit {unit}")
    ax.set(xlabel="Cycle", ylabel="Anomaly score"); ax.legend(ncol=2, fontsize=8)
    fig.tight_layout(); fig.savefig(figures / "representative_trajectories.png", dpi=150); plt.close(fig)


def run_anomaly_detection(processed: Path = Path("data/processed/fd001"),
                          config_path: Path = Path("configs/anomaly_detection.toml"),
                          report_root: Path = Path("reports")) -> dict[str, object]:
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    model_config = IsolationForestConfig(**config["model"])
    healthy_limit = int(config["healthy_region"]["minimum_rul_exclusive"])
    near_limit = int(config["analysis"]["near_event_rul_inclusive"])
    feature_config = CausalFeatureConfig(windows=tuple(config["features"]["windows"]))
    train, validation, manifest = load_development_partitions(processed)
    root, artifacts = report_root / "anomaly_detection", report_root / "anomaly_detection" / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    folds = grouped_unit_folds(train.unit_id.tolist(), folds=int(config["cross_validation"]["folds"]),
                               seed=int(config["cross_validation"]["seed"]))
    all_units, oof, fold_manifest = set(train.unit_id), [], []
    for index, holdout in enumerate(folds):
        fitting = sorted(all_units - set(holdout))
        engineer, detector, _, _, _ = _fit_fold_detector(
            train.loc[train.unit_id.isin(fitting)].reset_index(drop=True), feature_config, model_config, healthy_limit)
        holdout_frame = train.loc[train.unit_id.isin(holdout)].reset_index(drop=True)
        holdout_op = _with_rul(holdout_frame)
        engineered = engineer.transform_frame(holdout_frame).loc[holdout_op.index]
        records = _feature_records(engineered, engineer.feature_names)
        output = _score_frame(records, detector, holdout_op)
        output["fold"], output["partition"] = index, "train_oof"
        oof.append(output)
        engineer.save(artifacts / f"fold_{index}_feature_engineer.json")
        detector.save(artifacts / f"fold_{index}_detector.joblib")
        fold_manifest.append({"fold": index, "fitting_units": fitting, "holdout_units": holdout,
                              "overlap": [], "detector_training_summary": detector.training_summary})
    oof_frame = pd.concat(oof, ignore_index=True)
    _validate_oof(oof_frame, train)
    engineer, detector, _, _, _ = _fit_fold_detector(train, feature_config, model_config, healthy_limit)
    validation_op = _with_rul(validation)
    engineered_validation = engineer.transform_frame(validation).loc[validation_op.index]
    validation_frame = _score_frame(_feature_records(engineered_validation, engineer.feature_names), detector, validation_op)
    validation_frame["partition"] = "validation"
    oof_frame.to_parquet(artifacts / "train_oof_anomaly_scores.parquet", index=False)
    validation_frame.to_parquet(artifacts / "validation_anomaly_scores.parquet", index=False)
    engineer.save(artifacts / "causal_feature_engineer.json")
    detector.save(artifacts / "isolation_forest.joblib")
    _write_json(artifacts / "fold_manifest.json", {"strategy": "deterministic grouped unit folds",
        "fold_count": len(folds), "seed": int(config["cross_validation"]["seed"]), "folds": fold_manifest,
        "test_internal_read": False, "official_test_read": False})
    analyses = {"train_oof": _analysis(oof_frame, healthy_limit, near_limit,
                                         float(config["analysis"]["diagnostic_healthy_quantile"]),
                                         int(config["analysis"]["representative_units"])),
                "validation": _analysis(validation_frame, healthy_limit, near_limit,
                                          float(config["analysis"]["diagnostic_healthy_quantile"]),
                                          int(config["analysis"]["representative_units"]))}
    _write_json(root / "metrics.json", analyses)
    pd.DataFrame(analyses["validation"]["by_unit"]).to_parquet(artifacts / "validation_by_unit.parquet", index=False)
    _plots(validation_frame, root, healthy_limit, near_limit, int(config["analysis"]["representative_units"]))
    inputs = [processed / "train.parquet", processed / "validation.parquet", processed / "split_manifest.json", config_path]
    card = {"model_name": detector.model_name, "model_version": model_config.model_version,
            "training_data_manifest": manifest, "configuration": config,
            "parameters": detector.training_summary, "features": list(detector.feature_names),
            "input_contract": "324 train-fitted causal features at t; no RUL, targets, final time or future data",
            "output_contract": "anomaly_score = empirical CDF of -IsolationForest.score_samples on healthy train rows; [0,1], higher is more anomalous; not risk probability",
            "healthy_region": {"selection": f"RUL > {healthy_limit}", "used_as": "train-only detector fitting selection", "experimental": True},
            "assumptions": ["ASM019", "ASM020", "ASM021"],
            "limitations": ["No anomaly ground truth", "Diagnostic quantile is not an alert threshold", "Validation reused for development analysis", "Not independent from risk models"],
            "shared_dependencies": ["FD001 train data", "causal sensors/features", "feature selection/imputation", "Python/scikit-learn/joblib runtime", "unit folds and validation"],
            "dependencies": {"python": platform.python_version(), **{x: version(x) for x in ["numpy", "pandas", "scikit-learn", "joblib"]}},
            "input_hashes": {str(path): _sha(path) for path in inputs},
            "artifact_hash": {"path": str(artifacts / "isolation_forest.joblib"), "value": _sha(artifacts / "isolation_forest.joblib")},
            "metrics": analyses, "test_internal_read": False, "official_test_read": False}
    _write_json(root / "model_card.json", card)
    _write_report(report_root / "anomaly_detection_report.md", analyses, healthy_limit, near_limit)
    return analyses


def _write_report(path: Path, analyses: dict[str, object], healthy_limit: int, near_limit: int) -> None:
    validation = analyses["validation"]
    lines = ["# Detecção de anomalias com Isolation Forest — FD001", "",
             "## Escopo e escala", "",
             f"O detector foi ajustado exclusivamente no treino, em linhas com RUL>{healthy_limit}. "
             "RUL seleciona retrospectivamente a população saudável somente durante o ajuste; ele não é feature e validation não definiu esse limite.",
             "`raw_anomaly=-score_samples`; `anomaly_score=F_healthy(raw_anomaly)`, a CDF empírica dos raw scores saudáveis. "
             "Logo o score pertence a [0,1] e valores maiores indicam maior isolamento relativo à referência saudável. "
             "Não é probabilidade de falha, anomalia calibrada, risk_score ou health_score.", "",
             "## Comportamento em validation", "",
             "| Região retrospectiva | Linhas | Unidades | Média | Mediana | P95 |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for label, section in ((f"healthy RUL>{healthy_limit}", validation["healthy_region"]),
                           (f"near event RUL≤{near_limit}", validation["near_event_region"]),
                           ("all operational", validation["all_operational"])):
        lines.append(f"| {label} | {section['rows']} | {section['units']} | {section['mean']:.6f} | {section['median']:.6f} | {section['q95']:.6f} |")
    ref = validation["analysis_reference"]
    lines += ["", "## Antecedência e falsos positivos analíticos", "",
              f"Para tornar a mudança observável, a análise usa apenas a referência de percentil saudável {ref['healthy_score_quantile']:.2f} (score≥{ref['anomaly_score_cutoff']:.2f}). Ela não é threshold de alerta nem política operacional.",
              "", "Primeiras marcações fora de RUL≤30 (indicações aparentes; não há ground truth independente de anomalia):", ""]
    for row in validation["early_indications"]:
        lines.append(f"- unidade {row['unit_id']}, ciclo {row['cycle']}, RUL retrospectivo {row['RUL']}, score {row['anomaly_score']:.6f}.")
    lines += ["", "As primeiras marcações em ciclo 1 devem ser interpretadas com cautela: no FD001 elas podem refletir níveis iniciais entre unidades, não degradação antecipada. "
              "A sobreposição com a região saudável é evidência de que o score não deve acionar manutenção sem regra/validação adicional.",
              "", f"Linhas saudáveis acima dessa referência: {validation['false_positive_reference']['count']} "
              f"({validation['false_positive_reference']['fraction_of_healthy_rows']:.2%} das linhas saudáveis). Exemplos:", ""]
    for row in validation["healthy_region_high_scores"]:
        lines.append(f"- unidade {row['unit_id']}, ciclo {row['cycle']}, RUL retrospectivo {row['RUL']}, score {row['anomaly_score']:.6f}.")
    lines += ["", "## Dependência e monitoramento", "",
              "Isolation Forest acrescenta diversidade analítica, não um monitor independente. Ele compartilha sensores, dados de treino, "
              "preprocessing causal, partições, runtime e código de avaliação com os modelos de risco. Uma falha nesses componentes pode afetar monitor e preditor em conjunto.",
              "O monitor pode expor valores fora da referência saudável ou deriva gradual nas features. Provavelmente não detecta falhas "
              "que preservam a distribuição das features, rotulagem incorreta, atraso de telemetria sem timestamps, nem defeitos comuns no preprocessing/runtime.",
              "A latência de computação local é um score por observação após as janelas causais; a latência de detecção depende da frequência da telemetria e da regra futura de interpretação, inexistente nesta etapa.",
              "", "![Distribuições](anomaly_detection/figures/score_distribution.png)", "",
              "![Evolução por RUL](anomaly_detection/figures/score_by_rul.png)", "",
              "![Trajetórias](anomaly_detection/figures/representative_trajectories.png)", "",
              "## Artefatos e limites", "",
              "OOF: `reports/anomaly_detection/artifacts/train_oof_anomaly_scores.parquet`. Validation: `reports/anomaly_detection/artifacts/validation_anomaly_scores.parquet`. "
              "O card, manifests, modelos, métricas por unidade e figuras ficam em `reports/anomaly_detection`.",
              "Não foram usados test_internal, teste oficial NASA ou RUL oficial. Não há threshold operacional, fusão automática ou conversão para risco."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/anomaly_detection.toml"))
    args = parser.parse_args()
    print(json.dumps(run_anomaly_detection(config_path=args.config), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
