# Explicabilidade, calibração e incerteza empírica — FD001

## Escopo

Auditoria retrospectiva dos artefatos congelados em validation. Nenhum modelo foi criado ou reajustado; `test_internal`, `test_FD001.txt` e `RUL_FD001.txt` não foram lidos. Os resultados se limitam às 15 unidades de validation do FD001.

## Semântica

- SHAP descreve contribuições do XGBoost no espaço de margem bruta; não prova causalidade e não acrescenta significado físico aos nomes dos sensores.
- `anomaly_score` é um indicador de anormalidade, não uma probabilidade de falha.
- `disagreement` é divergência observada entre probabilidades comparáveis, não um intervalo de confiança.
- Os intervalos abaixo quantificam variação empírica das métricas ao reamostrar motores inteiros; não são intervalos por observações independentes.

## Calibração em validation

| Modelo | H | Brier | ECE | Intercepto | Inclinação |
| --- | ---: | ---: | ---: | ---: | ---: |
| weibull | 15 | 0.060652 | 0.022421 | -0.042656 | 0.922322 |
| weibull | 30 | 0.098197 | 0.064031 | 0.089808 | 0.959357 |
| random_forest | 15 | 0.013750 | 0.009437 | -0.007881 | 1.332084 |
| random_forest | 30 | 0.026506 | 0.011457 | 0.298720 | 1.064250 |
| xgboost | 15 | 0.010510 | 0.006696 | 0.078119 | 0.812121 |
| xgboost | 30 | 0.022978 | 0.014499 | 0.311502 | 0.756857 |
| discrete_hazard | 15 | 0.015063 | 0.011757 | 0.253803 | 0.685512 |
| discrete_hazard | 30 | 0.027172 | 0.020733 | -0.157966 | 0.522516 |
| tcn | 15 | 0.034437 | 0.052131 | -3.131839 | 1.423055 |
| tcn | 30 | 0.039308 | 0.031714 | -0.880506 | 0.726620 |
| transformer | 15 | 0.007844 | 0.009946 | -1.227937 | 1.230438 |
| transformer | 30 | 0.017680 | 0.017555 | -1.151080 | 1.040070 |
| fusion | 15 | 0.012694 | 0.010208 | 0.831342 | 0.998545 |
| fusion | 30 | 0.025415 | 0.022204 | 1.138545 | 0.999480 |

## Exemplos de explicação

### Alerta correto

Unidade 58, ciclo 145, RUL retrospectivo 2, risco final H30 0.970574, `anomaly_score` 0.995176 e `disagreement` 0.839315.

Principais contribuições XGBoost:

- `sensor_4__mean_w5`: increases_risk, magnitude relativa 0.0535, SHAP +0.577423.
- `sensor_15__mean_w10`: increases_risk, magnitude relativa 0.0479, SHAP +0.516825.
- `sensor_2__min_w10`: increases_risk, magnitude relativa 0.0408, SHAP +0.440999.

Reason codes: `XGB_INCREASES_RISK:sensor_4__mean_w5`, `FINAL_RISK_ABOVE_FROZEN_H30_THRESHOLD`, `ANOMALY_SCORE_ABOVE_TRAIN_HEALTHY_Q95_DIAGNOSTIC`

### Falso alerta

Unidade 94, ciclo 227, RUL retrospectivo 31, risco final H30 0.927427, `anomaly_score` 0.994886 e `disagreement` 0.487152.

Principais contribuições XGBoost:

- `sensor_4__mean_w5`: increases_risk, magnitude relativa 0.0664, SHAP +0.643565.
- `sensor_6__cumulative_abs_change`: decreases_risk, magnitude relativa 0.0563, SHAP -0.545371.
- `sensor_15__mean_w10`: increases_risk, magnitude relativa 0.0561, SHAP +0.543318.

Reason codes: `XGB_INCREASES_RISK:sensor_4__mean_w5`, `FINAL_RISK_ABOVE_FROZEN_H30_THRESHOLD`, `ANOMALY_SCORE_ABOVE_TRAIN_HEALTHY_Q95_DIAGNOSTIC`

## Métodos econômicos para os demais modelos

A Weibull permanece explicável apenas por idade populacional. O hazard discreto usa coeficientes padronizados como associação global. TCN e Transformer usam ablação de um canal por vez em amostra determinística: o canal é substituído por zero após normalização, isto é, pela média do treino. Essa ablação é sensibilidade do modelo, não intervenção física.

## Intervalos bootstrap

Os artefatos registram estimativa observada, mediana, limites percentis de 95%, número de réplicas válidas e cada motivo de réplica inválida. Recall, lead time médio e falsos alertas por unidade são calculados somente para a fusão com a política congelada; os demais modelos não receberam um threshold operacional nesta etapa.

| H | Métrica da fusão | Observado | IC 95% inferior | IC 95% superior | Válidas | Inválidas |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 15 | brier | 0.012694 | 0.008987 | 0.016982 | 1000 | 0 |
| 15 | pr_auc | 0.973083 | 0.961040 | 0.987557 | 1000 | 0 |
| 15 | roc_auc | 0.997760 | 0.996746 | 0.998948 | 1000 | 0 |
| 15 | recall_policy | 0.902222 | 0.848889 | 0.946667 | 1000 | 0 |
| 15 | mean_lead_time | 12.866667 | 11.066667 | 14.800000 | 1000 | 0 |
| 15 | false_alerts_per_unit | 0.533333 | 0.266667 | 0.866667 | 1000 | 0 |
| 30 | brier | 0.025415 | 0.017538 | 0.034566 | 1000 | 0 |
| 30 | pr_auc | 0.960961 | 0.944564 | 0.978107 | 1000 | 0 |
| 30 | roc_auc | 0.988694 | 0.980871 | 0.995142 | 1000 | 0 |
| 30 | recall_policy | 0.897778 | 0.844444 | 0.951111 | 1000 | 0 |
| 30 | mean_lead_time | 27.066667 | 24.266667 | 30.133333 | 1000 | 0 |
| 30 | false_alerts_per_unit | 0.466667 | 0.200000 | 0.800000 | 1000 | 0 |

## Limitações

Quinze motores fornecem evidência limitada para quantis extremos. ECE depende da escolha de dez bins. SHAP e ablação explicam sensibilidade da implementação, sem identificar mecanismos físicos, causas ou segurança operacional.
