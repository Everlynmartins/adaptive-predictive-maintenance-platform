# Experimento de redução de telemetria — FD001

## Escopo e protocolo

Este relatório registra o experimento científico da versão 0.11.0. O objetivo é
medir, somente no NASA C-MAPSS FD001, quanto da telemetria pode ser omitido sem
perder os critérios experimentais de desempenho e antecedência definidos antes
da leitura do holdout. As políticas foram aplicadas sequencialmente e o receptor
reconstruiu o estado disponível no ciclo; as features foram recalculadas sobre
esse estado. Nenhum resultado foi calculado a partir da telemetria completa e
atribuído ao cenário filtrado.

Foram avaliados XGBoost, hazard discreto e fusão para H=15 e H=30. A primeira
fase usou modelos treinados com FullTelemetryFilter e apenas filtrou a
inferência. A segunda fase refez filtro, receptor, features, preprocessing,
modelos, calibração e fusão por folds de `unit_id` para os candidatos escolhidos
em desenvolvimento. A seleção ocorreu apenas em treino/validation.

Os critérios experimentais pré-declarados estão em
`configs/telemetry_reduction_experiment.toml`: redução mínima de bytes de 20%,
perda máxima de PR AUC de 0,03, perda de ROC AUC de 0,015, perda de recall e
precision de 0,05, aumento de Brier de 0,01, perda de lead time de 3 ciclos,
latência mediana/P90 de 3/5 ciclos, aumento de 0,25 episódio falso por unidade,
zero falhas antecipadas perdidas, idade máxima de dados de 3 ciclos, no máximo
75% de saídas `degraded` e zero `unavailable`. São limites de comparação para o
benchmark, não objetivos de segurança ou limites aeronáuticos.

## Desenvolvimento: modelos treinados com telemetria completa

O FullTelemetryFilter foi usado como referência. A equivalência da inferência
full com os artefatos anteriores foi verificada: diferença máxima de 0,0 para
XGBoost, `4,66e-15` para hazard e `2,66e-15` para fusão.

| política/configuração | bytes relativos | redução | observações transmitidas | sensores transmitidos | idade máx. | degraded | unavailable | decisão |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Full | 1,0000 | 0,00% | 100,00% | 100,00% | 0 | 0,00% | 0,00% | referência |
| FixedInterval K=2 | 0,5013 | 49,87% | 50,13% | 50,13% | 1 | 49,89% | 0,00% | rejeitada |
| FixedInterval K=3 | 0,3343 | 66,57% | 33,43% | 33,43% | 2 | 66,50% | 0,00% | rejeitada |
| FixedInterval K=5 | 0,2023 | 79,77% | 20,23% | 20,23% | 4 | 59,93% | 19,84% | rejeitada |
| Adaptive q95 | 0,6761 | 32,39% | 67,61% | 67,61% | 3 | 32,38% | 0,00% | rejeitada |
| Adaptive q99 | 0,3742 | 62,58% | 37,42% | 37,42% | 3 | 62,56% | 0,00% | rejeitada |
| SensorSubset `subset_train17` | 0,7500 | 25,00% | 100,00% | 71,43% | 0 | 0,00% | 0,00% | selecionada |

No regime de modelos treinados com FullTelemetryFilter, a redução de 25% por
`subset_train17` preservou as métricas da referência dentro da tolerância e não
criou staleness. K=2, K=3, K=5 e os adaptativos reduziram mais bytes, mas
degradaram desempenho, antecedência ou disponibilidade. K=5 também produziu
19,84% de saídas `unavailable` por idade acima do limite.

## Desenvolvimento: treino e inferência pareados

Os dois candidatos inicialmente selecionados foram retreinados por unidade. O
critério conjunto exige aprovação para todos os três modelos e os dois
horizontes. Apenas `subset_train17` passou; `fixed_k3` foi mantido como
comparador rejeitado.

| política | modelo | H | PR AUC | recall | Brier | lead mediano | falsos/unidade | latência mediana | idade máx. | degraded | unavailable |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| subset_train17 | XGBoost | 15 | 0,97682 | 0,90667 | 0,01023 | 13 | 0,60 | 0 | 0 | 0% | 0% |
| subset_train17 | XGBoost | 30 | 0,97244 | 0,90667 | 0,02230 | 25 | 0,93 | 0 | 0 | 0% | 0% |
| subset_train17 | hazard | 15 | 0,95300 | 0,91556 | 0,01506 | 12 | 0,60 | 0 | 0 | 0% | 0% |
| subset_train17 | hazard | 30 | 0,95656 | 0,93556 | 0,02717 | 27 | 0,80 | 0 | 0 | 0% | 0% |
| subset_train17 | fusão | 15 | 0,97422 | 0,96444 | 0,01275 | 13 | 0,73 | 0 | 0 | 0% | 0% |
| subset_train17 | fusão | 30 | 0,96064 | 0,89111 | 0,02557 | 26 | 0,47 | 0 | 0 | 0% | 0% |
| fixed_k3 | XGBoost | 15 | 0,91667 | 0,50667 | 0,03200 | 5,5 | 0,07 | 7 | 2 | 66,50% | 0% |
| fixed_k3 | XGBoost | 30 | 0,93540 | 0,69556 | 0,04510 | 18 | 0,27 | 7 | 2 | 66,50% | 0% |
| fixed_k3 | hazard | 15 | 0,94900 | 0,42222 | 0,04310 | 5,5 | 0,07 | 7,5 | 2 | 66,50% | 0% |
| fixed_k3 | hazard | 30 | 0,94950 | 0,68000 | 0,05250 | 18 | 0,07 | 9 | 2 | 66,50% | 0% |
| fixed_k3 | fusão | 15 | 0,92450 | 0,46667 | 0,04220 | 5 | 0,00 | 7 | 2 | 66,50% | 0% |
| fixed_k3 | fusão | 30 | 0,90420 | 0,68889 | 0,05531 | 16 | 0,20 | 6 | 2 | 66,50% | 0% |

O candidato aprovado remove 25% dos bytes estimados, mantém toda a frequência
de observações e transmite 17 das 21 medições variáveis (71,43% dos sensores
transmitidos; as configurações omitidas são constantes no schema selecionado).
Não houve perda de lead mediano no validation para XGBoost H15/H30, hazard H30
ou fusão H15 em relação ao Full; a diferença é de até 1 ciclo nos demais casos.

## Avaliação congelada em `test_internal`

O gate foi criado em `reports/telemetry_filtering/freeze_manifest.json` após a
seleção. Somente `full` e `subset_train17` foram avaliados, em uma leitura, com
recibo em `reports/telemetry_filtering/test_evaluation_receipt.json`. O recibo
registra explicitamente que o projeto teve exposição histórica em uma fase
anterior (`reports/fusion/test_evaluation_receipt.json`); portanto esta é uma
avaliação congelada desta mudança, não uma alegação de holdout historicamente
virgem. O teste oficial NASA e o RUL oficial não foram lidos.

| configuração/modelo | H | bytes relativos | redução | PR AUC | recall | Brier | lead mediano | falsos/unidade | latência mediana | idade máx. | degraded | unavailable |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Full XGBoost | 15 | 1,0000 | 0,00% | 0,98100 | 0,96889 | 0,01226 | 15 | 1,00 | — | 0 | 0% | 0% |
| Subset XGBoost | 15 | 0,7500 | 25,00% | 0,98254 | 0,97333 | 0,01223 | 15 | 0,93 | 0 | 0 | 0% | 0% |
| Full XGBoost | 30 | 1,0000 | 0,00% | 0,98819 | 0,97556 | 0,01418 | 30 | 1,33 | — | 0 | 0% | 0% |
| Subset XGBoost | 30 | 0,7500 | 25,00% | 0,98840 | 0,98000 | 0,01432 | 30 | 1,00 | 0 | 0 | 0% | 0% |
| Full hazard | 15 | 1,0000 | 0,00% | 0,93922 | 0,93333 | 0,01672 | 15 | 0,93 | — | 0 | 0% | 0% |
| Subset hazard | 15 | 0,7500 | 25,00% | 0,93922 | 0,93333 | 0,01672 | 15 | 0,93 | 0 | 0 | 0% | 0% |
| Full hazard | 30 | 1,0000 | 0,00% | 0,96578 | 0,92000 | 0,02663 | 32 | 1,00 | — | 0 | 0% | 0% |
| Subset hazard | 30 | 0,7500 | 25,00% | 0,96578 | 0,92000 | 0,02663 | 32 | 1,00 | 0 | 0 | 0% | 0% |
| Full fusão | 15 | 1,0000 | 0,00% | 0,97931 | 0,97778 | 0,01018 | 17 | 0,87 | — | 0 | 0% | 0% |
| Subset fusão | 15 | 0,7500 | 25,00% | 0,97869 | 1,00000 | 0,01020 | 17 | 1,07 | -1 | 0 | 0% | 0% |
| Full fusão | 30 | 1,0000 | 0,00% | 0,98978 | 0,97778 | 0,01354 | 32 | 1,00 | — | 0 | 0% | 0% |
| Subset fusão | 30 | 0,7500 | 25,00% | 0,98922 | 0,97556 | 0,01388 | 30 | 0,87 | 0 | 0 | 0% | 0% |

No teste congelado houve redução máxima aprovada de **25%** dos bytes
estimados. As diferenças de PR AUC foram de -0,00062 (fusão H15) a +0,00021
(XGBoost H30); Brier mudou no máximo 0,00034. Não houve aumento de idade,
staleness, `degraded` ou `unavailable`, e nenhuma falha antecipada foi perdida
no protocolo por unidade. Esses números são evidência deste split FD001 e desta
configuração, não uma porcentagem transferível para operação.

## Impacto e artefatos

Cada candidato foi comparado com Full em
`reports/telemetry_change_impact.md`. O impacto principal é sobre validade e
idade da entrada, latência lógica, calibração, features temporais, o monitor de
anomalias e a rastreabilidade. K=5 e os adaptativos aumentam idade ou estados
degradados; o subconjunto compatível não altera a idade, mas depende do schema
aprendido no treino. A FMEA e a árvore de falhas foram atualizadas com perda,
atraso, staleness, recuperação de valor mantido e erro de contabilidade.

As curvas solicitadas estão em `reports/telemetry_filtering/figures/`:
bytes versus PR AUC, recall, lead time, falsos alertas, fração `degraded` e
staleness versus erro de calibração. Os artefatos de desenvolvimento,
predições, métricas por unidade, folds e hashes estão em
`reports/telemetry_filtering/artifacts/`.

Não foi escolhido threshold operacional. Os thresholds usados para medir os
episódios são exploratórios e foram derivados em validation, permanecendo em
`configs/telemetry_reduction_alert_policy.toml`.
