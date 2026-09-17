# Relatórios

`telemetry_filter_engine.md` descreve as quatro políticas, receptor HLV,
staleness, cadência, bytes e exemplos determinísticos. O relatório
`telemetry_change_impact.md` aplica o template de mudança e identifica
requisitos, hipóteses, métricas, regressões e artefatos afetados. Nenhum deles
contém comparação preditiva ou uso de holdouts.

`fusion_report.md` registra o protocolo OOF de stacking, comparação de
calibradores, thresholds escolhidos em validation e a única avaliação congelada
em `test_internal`. `fusion/` contém previsões, métricas por unidade, curvas de
confiabilidade, modelos/calibradores, manifesto de freeze e recibo da leitura.
O teste oficial NASA não foi usado.

`discrete_hazard_report.md` compara o hazard landmark logístico aos três
baselines anteriores. `discrete_hazard/` contém OOF/validation, modelos e
preprocessors de folds/final, métricas por unidade/idade, curvas e model card.
`discrete_hazard_verification.txt` registra testes de software; suas fixtures
sintéticas não são resultados do FD001. `discrete_hazard_preservation.json`
confere hashes históricos, sem consumir os testes reservados.

`fd001_data_status.md` registra a execução aprovada com os arquivos oficiais.
As métricas estruturais também estão em
`data/processed/fd001/validation_report.json`.

`eda_report.md` contém a EDA apenas no treino e a definição dos alvos.
`eda/figures` contém oito figuras; `eda/summary.json` registra estatísticas,
configuração e hashes dos dados processados utilizados.
`weibull_report.md` descreve o ajuste populacional Weibull 2P, aderência,
intervalos, sensibilidade e avaliação em validation. `weibull/` contém model
card, métricas JSON, artefato de modelo JSON, previsões/resultado por unidade
em Parquet e cinco figuras. Esses arquivos não usam sensores nem conjuntos de teste.

`classical_ml_report.md` compara Weibull, Random Forest e XGBoost para H=15/30.
`classical_ml/` contém previsões OOF/validation, métricas por unidade, modelos,
model cards, manifestos de features/folds, importâncias e figuras. A pipeline
clássica usa sensores de treino/validation, mas não lê nenhum conjunto de teste.

`anomaly_detection_report.md` documenta Isolation Forest, escala do score,
evolução, regiões retrospectivas, referências diagnósticas e dependências.
`anomaly_detection/` contém scores OOF/validation, detector, feature engineer,
model card, métricas por unidade, manifests e figuras. O score não é risco.

`tcn_report.md` compara a TCN causal com XGBoost, hazard discreto e fusão em
validation. `tcn/` contém checkpoint, model card, métricas e tabelas Parquet
de previsões e métricas por unidade, todos regenerados no Python 3.11 oficial.
A TCN não integra o stacking atual e não consumiu conjuntos de teste.

`transformer_report.md` compara o Transformer Encoder causal com XGBoost,
hazard discreto e TCN nas mesmas 15 unidades de validation. `transformer/`
contém checkpoint, model card, métricas e Parquets por linha/unidade. O custo
inclui timing CPU e memória analítica, sem afirmar equivalência a hardware edge.

`explainability_uncertainty_report.md` descreve SHAP do XGBoost, métodos
econômicos dos demais modelos, calibração e bootstrap por unidade.
`explainability_uncertainty/` contém explicações por origem, reliability curves,
intervalos, importâncias e ablações em Parquet/JSON. Os relatórios
`requirements_validation_report.md` e `requirements_verification_report.md`
mantêm validação de requisito separada da evidência de implementação.
