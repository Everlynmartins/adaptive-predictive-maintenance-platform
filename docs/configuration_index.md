# Índice de configuração da fase local

Este índice identifica a configuração reproduzível da versão **0.16.0** do
demonstrador local FD001. Ele não é uma baseline de certificação. O repositório
ainda não possui commit Git; por isso a identidade do código é dada pela versão
do pacote, pelos hashes abaixo e pelo resultado da auditoria final. Essa
limitação permanece registrada em `problem_reports.md`.

## Dados e partições

| Item | Localização | Identidade |
| --- | --- | --- |
| Manifesto FD001 | `data/processed/fd001/split_manifest.json` | SHA-256 `255eb98adbf71c3dc096c6e63331f28a7c24838915fe2a626d28775cca3aa0d1` |
| Fonte de desenvolvimento | `data/raw/train_FD001.txt` | SHA-256 `963b5e22825b34d8b21c69e1aeb4af3e647050eb672ee8834ba4b5d91d2de0f8`, registrado no manifesto |
| Divisão | manifesto acima | seed 42; 70 unidades treino, 15 validation e 15 test_internal; nenhuma sobreposição |
| Teste oficial | `data/raw/test_FD001.txt` e `RUL_FD001.txt` | presentes, `used=false`; não fazem parte da configuração científica executada |

`test_internal` foi usado somente nas avaliações congeladas de fusão e do
experimento de telemetria, depois do freeze correspondente. A aplicação e a
auditoria final leem `validation` e não reabrem essa partição.

## Modelos congelados

Todos os model cards declaram versão `1.0.0`. Os hashes completos dos cards e
artefatos estão em `reports/final_assurance/artifacts/audit_results.json`.

| Família | Model card | Artefato principal |
| --- | --- | --- |
| Weibull 2P | `reports/weibull/model_card.json` | `reports/weibull/artifacts/weibull_2p_model.json` |
| Random Forest | `reports/classical_ml/random_forest_model_card.json` | `reports/classical_ml/artifacts/models/random_forest_h15.joblib` e `random_forest_h30.joblib` |
| XGBoost | `reports/classical_ml/xgboost_model_card.json` | `reports/classical_ml/artifacts/models/xgboost_h15.joblib` e `xgboost_h30.joblib` |
| Hazard discreto | `reports/discrete_hazard/model_card.json` | `reports/discrete_hazard/artifacts/model.joblib` |
| Isolation Forest | `reports/anomaly_detection/model_card.json` | `reports/anomaly_detection/artifacts/isolation_forest.joblib` |
| Fusão | `reports/fusion/model_card.json` | `reports/fusion/artifacts/stacking_h15.joblib` e `stacking_h30.joblib` |
| TCN | `reports/tcn/model_card.json` | `reports/tcn/artifacts/tcn_model.pt` |
| Transformer | `reports/transformer/model_card.json` | `reports/transformer/artifacts/transformer_model.pt` |

TCN e Transformer são comparadores e permanecem fora da fusão. Isolation
Forest produz `anomaly_score`, não probabilidade de falha.

## Configurações, features e thresholds

As configurações científicas ficam em `configs/*.toml`; a auditoria registra o
SHA-256 de cada uma. `configs/final_assurance.toml` fixa as guardas de escopo e
`configs/local_app.toml` fixa modelos, políticas, horizontes e fontes da
aplicação. O manifesto de 324 features causais é
`reports/classical_ml/artifacts/feature_manifest.json`, SHA-256
`876dd00527f4a8ad8060cedf73ec5b5cd1aca3eb3c5bd157f0f1e3f7f0055ce2`.
RUL, vida normalizada, ciclo terminal, ciclo máximo e alvos não aparecem nele.

A política de fusão está em `configs/fusion_alert_policy.toml`, SHA-256
`3eb00fe69a1c4a73413bec640a5158d6d1a935918617875cd7cbd37b821833dd`:

- atenção H30: `0.0065678744209281296`;
- alerta H30: `0.15811159606353034`;
- crítico H15: `0.20137471216222377`;
- persistência: três ciclos.

São thresholds experimentais escolhidos em validation. A política de redução
de telemetria e seus thresholds pareados estão em
`configs/telemetry_reduction_alert_policy.toml`, SHA-256
`fc41e714bede925f6cacdca561a04830910dbc00027176b2c92c568d4b00ee12`.

## Ambiente efetivo

Python 3.11.16; NumPy 2.4.6; pandas 3.0.5; PyArrow 25.0.1;
scikit-learn 1.9.1; XGBoost 3.2.0; SciPy 1.17.1; joblib 1.6.0;
threadpoolctl 3.6.0; PyTorch 2.14.0; SHAP 0.51.0; Streamlit 1.64.0.
O `pyproject.toml` limita Python a `>=3.11,<3.12`.

## Evidências correspondentes

- contrato: `docs/prediction_contract.md`;
- validação e verificação: `reports/requirements_validation_report.md` e
  `reports/requirements_verification_report.md`;
- resultados: relatórios Weibull, classical ML, hazard, anomalia, fusão, TCN,
  Transformer, telemetria e explicabilidade em `reports/`;
- freeze: `reports/fusion/freeze_manifest.json` e
  `reports/telemetry_filtering/freeze_manifest.json`;
- auditoria executável: `final-assurance-local` e
  `reports/final_assurance/artifacts/audit_results.json`.
