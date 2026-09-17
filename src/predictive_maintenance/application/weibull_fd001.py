"""Fit and evaluate the age-only two-parameter Weibull FD001 baseline."""

from __future__ import annotations

import argparse
from dataclasses import asdict
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

from predictive_maintenance.analysis.weibull import (
    goodness_of_fit,
    parameter_bootstrap,
    probability_plot_data,
    sensitivity_analysis,
)
from predictive_maintenance.core.records import FeatureRecord
from predictive_maintenance.evaluation.probability import (
    evaluate_binary_probabilities,
    evaluate_by_unit,
)
from predictive_maintenance.models.reliability.weibull import (
    Weibull2Parameter,
    WeibullFitConfig,
)


def load_age_partitions(processed: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Read unit/cycle only from train and validation; never open either test."""
    manifest_path = processed / "split_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("dataset") != "FD001" or manifest.get("source", {}).get("file") != "train_FD001.txt":
        raise ValueError("Weibull baseline requires FD001 internal split manifest")
    names = ("train", "validation", "test_internal")
    declared = {name: set(manifest["units"][name]) for name in names}
    if any(declared[left] & declared[right] for left, right in
           (("train", "validation"), ("train", "test_internal"),
            ("validation", "test_internal"))):
        raise ValueError("unit overlap in split manifest")
    frames = []
    for name in ("train", "validation"):
        frame = pd.read_parquet(processed / f"{name}.parquet", columns=["unit_id", "cycle"])
        _validate_complete_keys(frame)
        if set(frame.unit_id) != declared[name] or len(frame) != manifest["rows"][name]:
            raise ValueError(f"{name} age data does not match split manifest")
        frames.append(frame)
    return frames[0], frames[1], manifest


def run_weibull_baseline(
    processed: Path = Path("data/processed/fd001"),
    config_path: Path = Path("configs/weibull.toml"),
    report_root: Path = Path("reports"),
) -> dict[str, object]:
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    _validate_configuration(config)
    train, validation, split_manifest = load_age_partitions(processed)
    train_path, validation_path = processed / "train.parquet", processed / "validation.parquet"
    split_path = processed / "split_manifest.json"
    input_hashes = {path.as_posix(): _hash(path) for path in
                    (train_path, validation_path, split_path, config_path)}

    lifetimes = train.groupby("unit_id", sort=True).cycle.max()
    training_manifest = {
        "dataset": "NASA C-MAPSS FD001",
        "source_partition": "train",
        "unit_count": int(len(lifetimes)),
        "event_count": int(len(lifetimes)),
        "censored_count": 0,
        "time_definition": "final observed cycle T_i of complete run-to-event units",
        "unit_ids": [int(value) for value in lifetimes.index],
        "split_seed": split_manifest["split"]["seed"],
        "source_file": split_manifest["source"]["file"],
        "source_sha256": split_manifest["source"]["sha256"],
        "input_sha256": input_hashes,
        "test_internal_read": False,
        "official_test_read": False,
    }
    model = Weibull2Parameter(WeibullFitConfig(
        config["model"]["name"], config["model"]["version"],
    )).fit_lifetimes(
        lifetimes.to_numpy(dtype=float),
        np.ones(len(lifetimes), dtype=bool),
        unit_ids=[str(value) for value in lifetimes.index],
        training_data_manifest=training_manifest,
    )

    intervals = parameter_bootstrap(
        lifetimes,
        samples=config["fit"]["bootstrap_samples"],
        seed=config["fit"]["bootstrap_seed"],
        confidence_level=config["fit"]["confidence_level"],
    )
    fit_assessment = goodness_of_fit(
        lifetimes, model,
        samples=config["goodness_of_fit"]["parametric_bootstrap_samples"],
        seed=config["goodness_of_fit"]["bootstrap_seed"],
        significance_level=config["goodness_of_fit"]["significance_level"],
    )
    horizons = list(config["prediction"]["horizons"])
    sensitivity = sensitivity_analysis(
        model, intervals, ages=config["sensitivity"]["ages"], horizons=horizons,
    )

    final_cycle = validation.groupby("unit_id").cycle.transform("max")
    evaluation = validation.assign(RUL=(final_cycle - validation.cycle).astype("int64"))
    evaluation = evaluation.loc[evaluation.RUL > 0].copy()
    prediction_frames, unit_frames = [], []
    metrics: dict[str, object] = {}
    feature_records = [FeatureRecord(str(row.unit_id), int(row.cycle), {})
                       for row in evaluation.itertuples(index=False)]
    for horizon in horizons:
        predictions = model.predict_risk(feature_records, horizon=horizon)
        prediction_frame = pd.DataFrame([{
            "unit_id": int(prediction.unit_id),
            "cycle": prediction.cycle,
            "horizon": prediction.horizon,
            "risk_score": prediction.risk_score,
            "survival_score": prediction.survival_score,
            "health_score": prediction.health_score,
            "model_name": prediction.model_name,
            "model_version": prediction.model_version,
            "prediction_status": prediction.prediction_status,
            "input_validity": prediction.input_validity,
        } for prediction in predictions])
        labels = evaluation.RUL.le(horizon).astype("int8").to_numpy()
        scored = prediction_frame.assign(label=labels)
        overall = evaluate_binary_probabilities(
            labels, prediction_frame.risk_score,
            reliability_bins=config["evaluation"]["reliability_bins"],
            log_loss_epsilon=config["evaluation"]["log_loss_epsilon"],
        )
        per_unit = evaluate_by_unit(
            scored,
            reliability_bins=config["evaluation"]["reliability_bins"],
            log_loss_epsilon=config["evaluation"]["log_loss_epsilon"],
        )
        per_unit.insert(1, "horizon", horizon)
        macro_columns = ["brier_score", "roc_auc", "pr_auc_average_precision",
                         "log_loss", "mean_predicted_risk", "prevalence"]
        metrics[str(horizon)] = {
            "overall_by_observation": overall,
            "macro_mean_by_unit": {name: float(per_unit[name].mean()) for name in macro_columns},
            "unit_count": int(per_unit.unit_id.nunique()),
            "population": "validation rows with RUL > 0 (T_i > t)",
        }
        prediction_frames.append(prediction_frame)
        unit_frames.append(per_unit)

    output = report_root / "weibull"
    figures = output / "figures"
    artifacts = output / "artifacts"
    figures.mkdir(parents=True, exist_ok=True)
    artifacts.mkdir(parents=True, exist_ok=True)
    model_path = artifacts / "weibull_2p_model.json"
    model.save(model_path)
    loaded = Weibull2Parameter.load(model_path)
    reference = [FeatureRecord("roundtrip", 100, {})]
    for horizon in horizons:
        if loaded.predict_risk(reference, horizon=horizon) != model.predict_risk(reference, horizon=horizon):
            raise RuntimeError("saved and loaded Weibull predictions differ")
    artifact_hash = model.artifact_hash(model_path)

    predictions_frame = pd.concat(prediction_frames, ignore_index=True)
    unit_metrics = pd.concat(unit_frames, ignore_index=True)
    predictions_path = artifacts / "validation_predictions.parquet"
    unit_metrics_path = artifacts / "validation_metrics_by_unit.parquet"
    predictions_frame.to_parquet(predictions_path, index=False)
    unit_metrics.to_parquet(unit_metrics_path, index=False)

    probability = probability_plot_data(lifetimes, model)
    analysis_payload = {
        "parameters": {"beta": model.beta, "eta": model.eta, "location": 0.0,
                       "confidence_intervals": intervals},
        "training_lifetimes": {
            "unit_count": int(len(lifetimes)), "events": int(len(lifetimes)),
            "censored": 0, "minimum": int(lifetimes.min()),
            "median": float(lifetimes.median()), "maximum": int(lifetimes.max()),
        },
        "goodness_of_fit": fit_assessment,
        "probability_plot_r_squared_descriptive": float(probability["r_squared_descriptive"]),
        "sensitivity": sensitivity,
    }
    provenance = {
        "package_version": version("adaptive-predictive-maintenance"),
        "configuration": config,
        "input_sha256": input_hashes,
        "training_partition": "train",
        "evaluation_partition": "validation",
        "test_internal_read": False,
        "official_test_read": False,
        "sensors_read": False,
    }
    model_card = {
        "model_name": model.config.model_name,
        "model_version": model.config.model_version,
        "training_data_manifest": training_manifest,
        "parameters": analysis_payload["parameters"],
        "configuration": config,
        "input_contract": {
            "unit_id": "non-empty string identity",
            "cycle": "positive integer benchmark age; unit must still be operational",
            "values": "must be empty; sensors and other features are rejected",
            "horizon": "positive integer cycles supplied explicitly to predict_risk",
        },
        "output_contract": {
            "required": ["unit_id", "cycle", "horizon", "risk_score", "model_name",
                         "model_version", "prediction_status", "input_validity"],
            "risk_semantics": "P(T_i <= t + H | age t, T_i > t) under fitted population Weibull",
            "survival_score": "1 - risk_score",
            "health_score": "100 * survival_score; horizon-dependent display only",
        },
        "assumptions": ["ASM001", "ASM002", "ASM003", "ASM007", "ASM008",
                        "ASM009", "ASM010", "ASM011"],
        "limitations": [
            "Population age-only baseline; it does not use telemetry sensors or unit covariates.",
            "Two-parameter parametric form with zero location is an approximation and not a physical degradation model.",
            "Validation rows within each unit are dependent; per-row metrics are accompanied by per-unit results.",
            "FD001 cycles are benchmark age indices, not physical time; no extrapolation to real assets is established.",
            "No operational threshold, test_internal result, official NASA test result, or censoring experiment.",
        ],
        "metrics": {"training_goodness_of_fit": fit_assessment,
                    "validation": metrics},
        "artifact_hash": {"algorithm": "sha256", "path": model_path.as_posix(),
                          "value": artifact_hash},
        "provenance": provenance,
    }
    _write_json(output / "analysis.json", analysis_payload)
    _write_json(output / "metrics.json", {"validation": metrics, "provenance": provenance})
    _write_json(output / "model_card.json", model_card)
    figure_paths = _create_figures(figures, lifetimes.to_numpy(), model, probability,
                                   metrics, sensitivity)
    _write_report(report_root / "weibull_report.md", model_card, analysis_payload,
                  metrics, figure_paths, predictions_path, unit_metrics_path)

    for path, expected in input_hashes.items():
        if _hash(Path(path)) != expected:
            raise RuntimeError(f"input changed during Weibull execution: {path}")
    return {
        "beta": model.beta, "eta": model.eta,
        "confidence_intervals": intervals,
        "goodness_of_fit": fit_assessment,
        "validation": metrics,
        "model_artifact": model_path.as_posix(),
        "model_artifact_sha256": artifact_hash,
        "report": (report_root / "weibull_report.md").as_posix(),
    }


def _validate_complete_keys(frame: pd.DataFrame) -> None:
    if frame.empty or list(frame.columns) != ["unit_id", "cycle"]:
        raise ValueError("age data must contain unit_id and cycle only")
    if frame.isna().any().any() or frame.duplicated().any():
        raise ValueError("age keys must be non-missing and unique")
    for name in ("unit_id", "cycle"):
        values = pd.to_numeric(frame[name], errors="coerce")
        if values.isna().any() or values.mod(1).ne(0).any() or values.le(0).any():
            raise ValueError("age keys must be positive integers")
    for _, unit in frame.groupby("unit_id", sort=False):
        if unit.cycle.tolist() != list(range(1, len(unit) + 1)):
            raise ValueError("complete trajectories must contain ordered cycles 1..N")


def _validate_configuration(config: dict) -> None:
    required = {"model", "fit", "goodness_of_fit", "prediction", "evaluation", "sensitivity"}
    if set(config) != required:
        raise ValueError(f"Weibull configuration sections must be {sorted(required)}")
    horizons = config["prediction"]["horizons"]
    if (not isinstance(horizons, list) or not horizons
            or any(type(value) is not int or value <= 0 for value in horizons)
            or len(set(horizons)) != len(horizons)):
        raise ValueError("prediction horizons must be unique positive integers")
    ages = config["sensitivity"]["ages"]
    if not isinstance(ages, list) or not ages or any(type(value) is not int or value < 0 for value in ages):
        raise ValueError("sensitivity ages must be non-negative integers")
    for section, key in (("fit", "bootstrap_samples"),
                         ("goodness_of_fit", "parametric_bootstrap_samples")):
        if type(config[section][key]) is not int or config[section][key] <= 0:
            raise ValueError(f"{section}.{key} must be a positive integer")


def _create_figures(
    figures: Path,
    lifetimes: np.ndarray,
    model: Weibull2Parameter,
    probability: dict[str, np.ndarray],
    metrics: dict[str, object],
    sensitivity: list[dict[str, float | int]],
) -> list[Path]:
    paths = []
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.scatter(probability["log_lifetime"], probability["weibull_quantile"], s=22,
               label="Median ranks")
    ax.plot(probability["log_lifetime"], probability["fitted_quantile"], color="C1",
            label="Weibull 2P MLE")
    ax.set(xlabel="ln(T)", ylabel="ln[-ln(1-F)]", title="Weibull probability plot — treino")
    ax.grid(alpha=.25); ax.legend(); paths.append(_save(fig, figures / "probability_plot.png"))

    ordered = np.sort(lifetimes)
    empirical = (len(ordered) - np.arange(1, len(ordered) + 1)) / len(ordered)
    grid = np.linspace(0, ordered.max() * 1.1, 400)
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.step(np.r_[0, ordered], np.r_[1, empirical], where="post", label="Empírica (eventos)")
    ax.plot(grid, model.survival(grid), label="Weibull ajustada")
    ax.set(xlabel="Idade (ciclos FD001)", ylabel="Sobrevivência", ylim=(-.02, 1.02),
           title="Sobrevivência empírica e ajustada — treino")
    ax.grid(alpha=.25); ax.legend(); paths.append(_save(fig, figures / "survival_fit.png"))

    fig, ax = plt.subplots(figsize=(7, 5))
    ax.plot(grid, model.hazard(grid), color="C3")
    ax.set(xlabel="Idade (ciclos FD001)", ylabel="Hazard por ciclo",
           title="Hazard Weibull 2P ajustado")
    ax.grid(alpha=.25); paths.append(_save(fig, figures / "hazard.png"))

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.plot([0, 1], [0, 1], "--", color="0.5", label="Calibração perfeita")
    for horizon, result in metrics.items():
        curve = result["overall_by_observation"]["reliability_curve"]
        ax.plot([row["mean_predicted"] for row in curve],
                [row["observed_frequency"] for row in curve], marker="o", label=f"H={horizon}")
    ax.set(xlabel="Risco médio previsto", ylabel="Frequência observada", xlim=(-.02, 1.02),
           ylim=(-.02, 1.02), title="Reliability curve — validation operacional")
    ax.grid(alpha=.25); ax.legend(); paths.append(_save(fig, figures / "reliability_curve.png"))

    table = pd.DataFrame(sensitivity)
    fig, axes = plt.subplots(1, len(sorted(table.horizon.unique())), figsize=(12, 4.5), sharey=True)
    axes = np.atleast_1d(axes)
    for ax, horizon in zip(axes, sorted(table.horizon.unique()), strict=True):
        group = table.loc[table.horizon == horizon]
        ax.plot(group.age, group.risk_mle, marker="o", label="MLE")
        low = group["risk_parameter_rectangle_min"]
        high = group["risk_parameter_rectangle_max"]
        ax.fill_between(group.age, low, high, alpha=.2, label="retângulo dos ICs marginais")
        ax.set(title=f"H={horizon}", xlabel="Idade (ciclos)")
        ax.grid(alpha=.25)
    axes[0].set_ylabel("Risco condicional")
    axes[-1].legend(); paths.append(_save(fig, figures / "parameter_sensitivity.png"))
    return paths


def _write_report(
    path: Path, card: dict, analysis: dict, metrics: dict,
    figures: list[Path], predictions_path: Path, unit_metrics_path: Path,
) -> None:
    beta, eta = card["parameters"]["beta"], card["parameters"]["eta"]
    intervals = card["parameters"]["confidence_intervals"]
    gof = analysis["goodness_of_fit"]
    lines = [
        "# Baseline populacional Weibull 2P — FD001", "",
        "## Escopo", "",
        "Weibull de dois parâmetros com localização fixa em zero, ajustada por máxima",
        "verossimilhança a uma duração T_i por cada um dos 70 motores de treino.",
        "Todas as durações são eventos observados. Nenhum sensor, unidade de validation",
        "ou holdout participa do ajuste. É um baseline estatístico por idade; não é modelo",
        "físico automático de degradação. Nenhum threshold foi escolhido.", "",
        "## Parâmetros e incerteza", "",
        "| Parâmetro | MLE | IC bootstrap 95% |", "| --- | ---: | ---: |",
        f"| beta | {beta:.6f} | [{intervals['beta']['lower']:.6f}, {intervals['beta']['upper']:.6f}] |",
        f"| eta (ciclos) | {eta:.6f} | [{intervals['eta']['lower']:.6f}, {intervals['eta']['upper']:.6f}] |", "",
        f"IC percentil não paramétrico com {intervals['samples']} reamostragens dos 70 motores inteiros, seed {intervals['seed']}; ciclos não foram reamostrados como independentes.", "",
        "## Aderência no treino", "",
        f"Cramér–von Mises W²={gof['statistic']:.6f}; valor crítico bootstrap a 5%={gof['critical_value']:.6f}; p={gof['p_value']:.6f} (erro-padrão Monte Carlo aproximado {gof['monte_carlo_standard_error_at_p']:.6f}). Decisão: `{gof['decision']}`.",
        f"Foram usadas {gof['bootstrap_samples']} amostras paramétricas, seed {gof['seed']}; cada réplica foi simulada da Weibull ajustada, arredondada para o ciclo inteiro positivo mais próximo, reajustada por MLE e teve W² recalculado. Houve {gof['bootstrap_exceedances']} réplicas com estatística pelo menos tão grande; p usa correção (excedências+1)/(B+1), logo {1/(gof['bootstrap_samples']+1):.6f} é o menor valor resolvível. O crítico é o quantil empírico linear de 95%. Assim, ambos incluem estimação dos parâmetros e a resolução adotada. Distância KS descritiva={gof['ks_distance_descriptive']:.6f}; AIC={gof['aic']:.3f}; BIC={gof['bic']:.3f}; R² descritivo do probability plot={analysis['probability_plot_r_squared_descriptive']:.6f}.", "",
        "Desvios de sobrevivência empírica menos ajustada por região:", "",
        "| Região | Faixa T | Média do desvio | Máximo absoluto |", "| --- | ---: | ---: | ---: |",
    ]
    for row in gof["systematic_deviation"]:
        lines.append(f"| {row['region']} | {row['minimum_lifetime']:.0f}–{row['maximum_lifetime']:.0f} | {row['mean_empirical_minus_fitted_survival']:.6f} | {row['max_absolute_deviation']:.6f} |")
    lines += ["", "Sinal positivo indica sobrevivência empírica acima da Weibull naquela região; sinal negativo indica abaixo. O teste avalia aderência global, não prova que a forma paramétrica seja verdadeira nem ausência de desvio local.", "",
              "## Validation operacional", "",
              "Somente ciclos com T_i>t dos 15 motores de validation: 3.045 observações dependentes. Métricas globais por linha são acompanhadas por médias dos resultados calculados separadamente em cada motor.", "",
              "| H | Positivos | Previsto médio | Observado | Brier | ROC AUC | PR AUC (average precision) | Log loss | Brier macro por unidade |", "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for horizon in sorted(metrics, key=int):
        overall = metrics[horizon]["overall_by_observation"]
        macro = metrics[horizon]["macro_mean_by_unit"]
        lines.append(f"| {horizon} | {overall['n_positive']} | {overall['mean_predicted_risk']:.6f} | {overall['prevalence']:.6f} | {overall['brier_score']:.6f} | {overall['roc_auc']:.6f} | {overall['pr_auc_average_precision']:.6f} | {overall['log_loss']:.6f} | {macro['brier_score']:.6f} |")
    lines += ["", "A calibração média é a diferença previsto menos observado. Curvas por bins iguais estão em metrics.json e na figura. Em ambos os horizontes o risco médio ficou abaixo da frequência observada. Brier e log loss não devem ser comparados entre H=15 e H=30 como se a prevalência fosse igual; H=30 contém o dobro de positivos.", "",
              "ROC AUC e PR AUC calculadas separadamente dentro de cada unidade são 1,0 porque tanto o rótulo retrospectivo quanto qualquer risco Weibull com beta positivo são monotônicos no ciclo: os últimos H ciclos sempre recebem os maiores riscos. Isso é uma consequência estrutural do baseline age-only, não evidência de boa calibração ou separação entre motores. Os valores globais agrupados são menores porque motores falham em idades distintas. As linhas de uma mesma unidade continuam dependentes; o Parquet por unidade torna essa estrutura auditável.", "",
              "## Sensibilidade a beta e eta", "",
              "Cada parâmetro foi variado até seus limites de IC mantendo o outro na MLE; os quatro cantos do retângulo formado pelos ICs marginais também foram avaliados. Isso mede sensibilidade paramétrica ao ajuste, não intervalo de previsão nem região de confiança conjunta.", "",
              "| idade | H | risco MLE | beta baixo/alto | eta baixo/alto | min/max no retângulo |", "| ---: | ---: | ---: | ---: | ---: | ---: |"]
    for row in analysis["sensitivity"]:
        lines.append(f"| {row['age']} | {row['horizon']} | {row['risk_mle']:.6f} | {row['risk_beta_lower']:.6f} / {row['risk_beta_upper']:.6f} | {row['risk_eta_lower']:.6f} / {row['risk_eta_upper']:.6f} | {row['risk_parameter_rectangle_min']:.6f} / {row['risk_parameter_rectangle_max']:.6f} |")
    lines += ["", "## Funções e contrato", "",
              "`f(t)`, `F(t)`, `S(t)`, `h(t)` e `H_c(t)` são as funções Weibull 2P usuais. `risk(t,H)=1-S(t+H)/S(t)=1-exp(-[((t+H)/eta)^beta-(t/eta)^beta])`. O método matemático aceita H=0 e retorna zero; RiskPrediction exige H inteiro positivo conforme o contrato de aplicação.", "",
              "Cada previsão contém unit_id, cycle, horizon, risk_score, model_name, model_version, prediction_status e input_validity, além de survival_score e health_score derivados. Entrada aceita: FeatureRecord com unit_id, ciclo-idade positivo e values vazio. Qualquer sensor/feature é rejeitado.", "",
              "## Hipóteses e limitações", "",
              "Hipóteses ASM001–ASM003 e ASM007–ASM011 no registro. A rejeição ou não rejeição do teste não valida os horizontes nem extrapolação. A Weibull presume uma população comum e usa somente idade; heterogeneidade entre motores, dependência entre ciclos de avaliação e misspecification podem afetar calibração. Ciclo é índice do benchmark, não tempo físico. A execução não usa test_internal, teste oficial NASA ou RUL oficial e não simula censura.", "",
              "## Artefatos e reprodução", ""]
    for figure in figures:
        lines += [f"![{figure.stem}](weibull/figures/{figure.name})", ""]
    lines += [f"- Modelo: `{card['artifact_hash']['path']}`; SHA-256 `{card['artifact_hash']['value']}`.",
              f"- Previsões: `{predictions_path.as_posix()}`.",
              f"- Métricas por unidade: `{unit_metrics_path.as_posix()}`.",
              "- Model card: `reports/weibull/model_card.json`; métricas: `reports/weibull/metrics.json`; análise: `reports/weibull/analysis.json`.", "",
              "```powershell", ".\\.venv\\Scripts\\python.exe -m predictive_maintenance.application.weibull_fd001", "```", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def _save(fig: plt.Figure, path: Path) -> Path:
    fig.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return path


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True,
                               allow_nan=False) + "\n", encoding="utf-8")


def _hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--processed-dir", type=Path, default=Path("data/processed/fd001"))
    parser.add_argument("--config", type=Path, default=Path("configs/weibull.toml"))
    parser.add_argument("--reports-dir", type=Path, default=Path("reports"))
    args = parser.parse_args()
    print(json.dumps(run_weibull_baseline(args.processed_dir, args.config, args.reports_dir),
                     indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
