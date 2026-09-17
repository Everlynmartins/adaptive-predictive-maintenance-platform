"""Local landmark hazard experiment; only train and validation are consumed."""
import argparse
from dataclasses import asdict
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import platform
import tomllib

import numpy as np
import pandas as pd

from predictive_maintenance.application.classical_ml_fd001 import (
    load_development_partitions, grouped_unit_folds, _feature_records,
    _prediction_frame, _operational_target,
)
from predictive_maintenance.core.records import TargetRecord
from predictive_maintenance.features.causal import CausalFeatureConfig, CausalTelemetryFeatures
from predictive_maintenance.models.temporal.discrete_hazard import DiscreteHazardRiskModel, HazardConfig
from predictive_maintenance.evaluation.probability import evaluate_binary_probabilities, reliability_curve


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+"\n", encoding="utf-8")


def sha(path):
    return sha256(path.read_bytes()).hexdigest()


def fit_model(frame, config, feature_config):
    mask, _ = _operational_target(frame, 1)
    engineer = CausalTelemetryFeatures(feature_config).fit_frame(frame, fit_mask=mask)
    features = _feature_records(engineer.transform_frame(frame).loc[mask], engineer.feature_names)
    endpoints = frame.groupby("unit_id").cycle.max()
    targets = [TargetRecord(unit_id=f.unit_id, cycle=f.cycle,
               values={"observed_end": int(endpoints.loc[int(f.unit_id)]), "event_observed": 1}) for f in features]
    model = DiscreteHazardRiskModel(engineer.feature_names, config).fit(features, targets)
    return engineer, model


def predict_frame(frame, engineer, model, horizons):
    mask, _ = _operational_target(frame, 1)
    features = _feature_records(engineer.transform_frame(frame).loc[mask], engineer.feature_names)
    outputs = []
    for horizon in horizons:
        predicted = _prediction_frame(model.predict_risk(features, horizon=horizon))
        _, labels = _operational_target(frame, horizon)
        predicted["label"] = labels.astype(int)
        predicted["algorithm"] = "discrete_hazard"
        outputs.append(predicted)
    return pd.concat(outputs, ignore_index=True)


def metrics(frame):
    # Small age strata may have a single class; ranking metrics are undefined.
    if frame.label.nunique() == 2:
        return evaluate_binary_probabilities(frame.label, frame.risk_score)
    p, y = frame.risk_score.to_numpy(), frame.label.to_numpy()
    q = np.clip(p, 1e-15, 1-1e-15)
    return {"n_observations": len(frame), "n_positive": int(y.sum()),
            "prevalence": float(y.mean()), "mean_predicted_risk": float(p.mean()),
            "calibration_in_the_large": float(p.mean()-y.mean()),
            "brier_score": float(np.mean((p-y)**2)),
            "log_loss": float(-np.mean(y*np.log(q)+(1-y)*np.log1p(-q))),
            "roc_auc": None, "pr_auc_average_precision": None,
            "reliability_curve": reliability_curve(y,p,10)}


def compare_existing(root, validation, horizons):
    sources = [(root/"weibull/artifacts/validation_predictions.parquet", "weibull"),
               (root/"classical_ml/artifacts/validation_predictions.parquet", None)]
    frames = []
    for path, algorithm in sources:
        previous = pd.read_parquet(path)
        if algorithm:
            previous["algorithm"] = algorithm
        previous["unit_id"] = previous.unit_id.astype(int)
        for name, group in previous.groupby("algorithm"):
            for h in horizons:
                mask, y = _operational_target(validation, h)
                keys = validation.loc[mask, ["unit_id","cycle"]].copy()
                keys["label"] = y.astype(int)
                p = group.loc[group.horizon == h]
                if len(p) != len(keys):
                    raise ValueError("prior prediction coverage mismatch")
                merged = keys.merge(p[["unit_id","cycle","risk_score"]], on=["unit_id","cycle"], validate="one_to_one")
                if len(merged) != len(keys):
                    raise ValueError("prior prediction keys mismatch")
                merged["algorithm"], merged["horizon"] = name, h
                frames.append(merged)
    return pd.concat(frames, ignore_index=True)


def run_discrete_hazard(processed=Path("data/processed/fd001"),
                        config_path=Path("configs/discrete_hazard.toml"), report_root=Path("reports"),
                        compare=True):
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    model_config = HazardConfig(**config["model"])
    horizons = config["evaluation"]["horizons"]
    if not horizons or horizons != sorted(set(horizons)) or any(type(h) is not int or not 1 <= h <= model_config.max_horizon for h in horizons):
        raise ValueError("invalid evaluation horizons")
    width = config["evaluation"]["age_bin_width"]
    if type(width) is not int or width < 1:
        raise ValueError("positive age bin width required")
    feature_config = CausalFeatureConfig(windows=tuple(config["features"]["windows"]))
    train, validation, split = load_development_partitions(processed)
    root = report_root/"discrete_hazard"
    artifacts, figures = root/"artifacts", root/"figures"
    artifacts.mkdir(parents=True, exist_ok=True)
    figures.mkdir(parents=True, exist_ok=True)
    folds = grouped_unit_folds(train.unit_id.tolist(), **config["cross_validation"])
    oof, fold_records = [], []
    all_units = set(train.unit_id)
    for j, holdout in enumerate(folds):
        fitting = sorted(all_units-set(holdout))
        print(f"Fold {j+1}/{len(folds)}: fitting {len(fitting)} units", flush=True)
        engineer, model = fit_model(train.loc[train.unit_id.isin(fitting)].reset_index(drop=True), model_config, feature_config)
        predictions = predict_frame(train.loc[train.unit_id.isin(holdout)].reset_index(drop=True), engineer, model, horizons)
        predictions["fold"] = j
        oof.append(predictions)
        engineer.save(artifacts/f"fold_{j}_features.json")
        model.save(artifacts/f"fold_{j}_model.joblib")
        fold_records.append({"fold":j,"fitting_units":fitting,"holdout_units":holdout,
                             "training_summary":model.training_summary})
    oof = pd.concat(oof,ignore_index=True)
    mask, _ = _operational_target(train,1)
    if oof.duplicated(["unit_id","cycle","horizon"]).any() or len(oof) != int(mask.sum())*len(horizons):
        raise RuntimeError("OOF coverage failure")
    print("Final fit on full training partition",flush=True)
    engineer, model = fit_model(train,model_config,feature_config)
    predicted = predict_frame(validation,engineer,model,horizons)
    oof["partition"], predicted["partition"] = "train_oof", "validation"
    oof.to_parquet(artifacts/"train_oof_predictions.parquet",index=False)
    predicted.to_parquet(artifacts/"validation_predictions.parquet",index=False)
    engineer.save(artifacts/"causal_feature_engineer.json")
    model.save(artifacts/"model.joblib")
    write_json(artifacts/"fold_manifest.json",fold_records)
    results, unit_rows, age_rows = {}, [], []
    for partition, frame in (("train_oof",oof),("validation",predicted)):
        results[partition] = {}
        for h,g in frame.groupby("horizon"):
            results[partition][str(h)] = metrics(g)
            for unit,u in g.groupby("unit_id"):
                unit_rows.append({"partition":partition,"horizon":int(h),"unit_id":int(unit),
                                  **{k:v for k,v in metrics(u).items() if k != "reliability_curve"}})
            for age,a in g.groupby((g.cycle//width)*width):
                age_rows.append({"partition":partition,"horizon":int(h),"age_start":int(age),
                    "age_end_exclusive":int(age+width),"units":int(a.unit_id.nunique()),
                    **{k:v for k,v in metrics(a).items() if k != "reliability_curve"}})
    pd.DataFrame(unit_rows).to_parquet(artifacts/"metrics_by_unit.parquet",index=False)
    pd.DataFrame(age_rows).to_parquet(artifacts/"calibration_by_age.parquet",index=False)
    combined = predicted.copy()
    if compare:
        combined = pd.concat([compare_existing(report_root,validation,horizons),predicted],ignore_index=True)
    comparison = []
    for (name,h),g in combined.groupby(["algorithm","horizon"]):
        comparison.append({"model":name,"horizon":int(h),**metrics(g)})
    coherence = {}
    for partition,frame in (("train_oof",oof),("validation",predicted)):
        p = frame.pivot(index=["unit_id","cycle"],columns="horizon",values="risk_score")
        coherence[partition] = {"origins":len(p),"violations":int((np.diff(p.to_numpy(),axis=1)<-1e-12).any(axis=1).sum())}
    results["comparison"], results["coherence"] = comparison,coherence
    write_json(root/"metrics.json",results)
    inputs = [processed/"train.parquet",processed/"validation.parquet",processed/"split_manifest.json",config_path]
    card = {"model_name":model.model_name,"model_version":model.config.model_version,
        "training_data_manifest":split,"configuration":config,"training_summary":model.training_summary,
        "features":list(model.feature_names),"input_contract":"Reviewed causal features frozen at t, age_cycle=t; relative k generated internally",
        "output_contract":"P(T<=t+H | F_t,T>t)=1-product(1-h_k); RiskPrediction; H in 1..max_horizon",
        "parameters":{"coefficients":model.theta.tolist(),"order":[*model.feature_names,"relative_step_scaled","intercept"]},
        "assumptions":["ASM001","ASM011","ASM012","ASM013","ASM016","ASM017","ASM018"],
        "limitations":["Additive logistic logit; no feature-step interactions", "Dependent overlapping landmarks; no iid confidence intervals",
                       "No post-hoc calibration or operational threshold", "No industrial validation; censoring tested only synthetically"],
        "dependencies":{"python":platform.python_version(),**{n:version(n) for n in ["numpy","scipy","scikit-learn","pandas","joblib"]}},
        "common_dependencies":["data","causal preprocessing","folds","runtime","evaluation; not independent redundancy"],
        "input_hashes":{str(p):sha(p) for p in inputs},"artifact_hash":sha(artifacts/"model.joblib"),
        "artifact_hashes":{p.name:sha(p) for p in artifacts.iterdir() if p.is_file()},
        "source_hashes":{str(p):sha(p) for p in Path("src/predictive_maintenance").rglob("*.py")},
        "metrics":results,"test_internal_read":False,"official_test_read":False}
    write_json(root/"model_card.json",card)
    make_report(report_root,results,age_rows,model,engineer)
    print(json.dumps({"validation":results["validation"],"coherence":coherence},indent=2),flush=True)
    return results


def make_report(root,results,age_rows,model,engineer):
    import matplotlib.pyplot as plt
    fig,axes = plt.subplots(1,len(results["validation"]),figsize=(12,5),squeeze=False)
    for ax,h in zip(axes[0],results["validation"]):
        ax.plot([0,1],[0,1],"k--")
        for row in results["comparison"]:
            if row["horizon"] == int(h):
                curve=row["reliability_curve"]
                ax.plot([b["mean_predicted"] for b in curve],[b["observed_frequency"] for b in curve],"o-",label=row["model"])
        ax.set(xlabel="Predicted risk",ylabel="Observed frequency",title=f"Validation H={h}",xlim=(0,1),ylim=(0,1))
        ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(root/"discrete_hazard/figures/reliability_curve.png",dpi=150); plt.close(fig)
    fig,axes=plt.subplots(1,len(results["validation"]),figsize=(12,4),squeeze=False)
    for ax,h in zip(axes[0],results["validation"]):
        rows=[r for r in age_rows if r["partition"]=="validation" and r["horizon"]==int(h)]
        for key,label in [("mean_predicted_risk","Predicted"),("prevalence","Observed")]:
            ax.plot([r["age_start"] for r in rows],[r[key] for r in rows],"o-",label=label)
        ax.set(xlabel="Age bin start (cycles)",ylabel="Risk / frequency",title=f"H={h}"); ax.legend()
    fig.tight_layout(); fig.savefig(root/"discrete_hazard/figures/calibration_by_age.png",dpi=150); plt.close(fig)
    lines=["# Hazard discreto logístico — FD001", "", "## Construção landmark", "",
       f"Cada origem operacional t recebe passos k=1..{model.config.max_horizon}, com covariáveis congeladas em t, idade t e k/Hmax. "
       "A máscara inclui k≤observed_end−t. O alvo vale 1 somente em k=T−t com evento observado. "
       "Não há linhas após evento; após censura os passos não entram na perda. Nenhuma censura foi fabricada no FD001.", "",
       "logit(h)=b0+bᵀz(x_t,t)+bk(k/Hmax). Padronização, seleção de constantes e imputação são aprendidas "
       "somente no treino de cada fold. A perda Bernoulli soma passos observados com penalização L2, "
       "sem balancear classes. A implementação fatorada é equivalente a expandir as linhas, evitando duplicar toda a matriz.", "",
       f"{len(engineer.feature_names)} features causais; resumo do ajuste: `{json.dumps(model.training_summary)}`.", "",
       "Landmarks sobrepostos são dependentes e formam uma verossimilhança composta. Motores longos contribuem mais passos; "
       "não se calculam erros-padrão iid. A avaliação por unidade acompanha a avaliação por linha. "
       "Folds e seed são configuráveis e registrados no card, sem unidades compartilhadas dentro do fold.","",
       "## Comparação em validation", "", "| H | Modelo | Brier | Log loss | ROC AUC | PR AUC/AP | Previsto | Observado |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in sorted(results["comparison"],key=lambda r:(r["horizon"],r["model"])):
        lines.append(f"| {r['horizon']} | {r['model']} | "+" | ".join(f"{r[k]:.6f}" for k in ["brier_score","log_loss","roc_auc","pr_auc_average_precision","mean_predicted_risk","prevalence"])+" |")
    lines += ["", "## Calibração e coerência", "",
        "As curvas usam dez bins de probabilidade. Calibração por idade usa faixas fixas configuráveis, "
        "sem vida normalizada ou seleção de features por validation. Contagens por faixa e unidade estão em Parquet. "
        "Faixas de uma classe têm ranking indefinido (null). Oscilações em bins pequenos não sustentam conclusões industriais.", "",
        f"Coerência observada: `{json.dumps(results['coherence'])}`. O mesmo modelo gera ambos os horizontes, "
        "logo S(H)=produto(1-h) não aumenta e risco não diminui com H. Isso não garante calibração nem monotonicidade em idade.","",
        "![Reliability](discrete_hazard/figures/reliability_curve.png)","",
        "![Idade](discrete_hazard/figures/calibration_by_age.png)","",
        "## Limitações e assurance", "",
        "ASM016–018 permanecem abertas: adequação do logit aditivo, suficiência das features e contribuição dos landmarks. "
        "ASM011 (censura condicionalmente não informativa) não foi confirmada por fixtures. "
        "Weibull continua baseline cuja aderência foi rejeitada. RF/XGB e hazard compartilham dados, features, folds, "
        "runtime e avaliação: não são redundância independente. Não há calibração posterior, threshold ou política de manutenção.","",
        "Treino e validation apenas; test_internal e teste oficial não utilizados. Comparações reutilizam previsões históricas "
        "alinhadas por chave e horizonte, sem reajustar os modelos anteriores. A avaliação repetida em validation não é avaliação final.","",
        "## Artefatos e reprodução", "",
        "`reports/discrete_hazard/artifacts/train_oof_predictions.parquet`, `validation_predictions.parquet`, "
        "`metrics_by_unit.parquet`, `calibration_by_age.parquet`, `fold_manifest.json`, modelos e preprocessors por fold "
        "e finais. Card em `reports/discrete_hazard/model_card.json`; métricas em `metrics.json`.","",
        "Executar: `.venv/Scripts/python.exe -m predictive_maintenance.application.discrete_hazard_fd001`. "
        "Artefatos joblib somente de fonte local confiável. Os horizontes 15/30 são experimentais."]
    (root/"discrete_hazard_report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config",type=Path,default=Path("configs/discrete_hazard.toml"))
    args=parser.parse_args()
    run_discrete_hazard(config_path=args.config)


if __name__ == "__main__":
    main()
