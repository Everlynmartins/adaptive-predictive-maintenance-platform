# Análise de impacto da redução de telemetria — FD001, versão 0.11.0

Esta análise aplica o template de mudança à passagem FullTelemetryFilter → pacote → receptor hold-last-value → features receiver-aware → modelo. O experimento é local, reproduzível e limitado às trajetórias completas do FD001. Bytes são uma estimativa analítica com 32 bytes de metadados e 8 bytes por valor; não representam um protocolo aeronáutico.

## Protocolo e controles

A grade versionada em `configs/telemetry_reduction_experiment.toml` contém Full, K=2/3/5, `subset_train17` e Adaptive q95/q99. Os quantis adaptativos são estimados exclusivamente no treino; os folds de OOF reestimam o quantil apenas nas unidades de ajuste. Features são recalculadas no estado do receptor. Um valor mantido carrega idade e não avança o histórico temporal.

O desenvolvimento tem duas partes. Primeiro, os artefatos treinados com telemetria completa recebem somente o fluxo reconstruído. Depois, as candidatas `subset_train17` e `fixed_k3` são reajustadas por folds agrupados, incluindo preprocessing, RF, XGBoost, hazard, Isolation Forest, Weibull OOF, stacking e calibração. A Full foi exigida como controle de equivalência: na validation a diferença máxima foi 0 para XGBoost, `4,66e-15` para hazard e `2,66e-15` para fusão.

Os critérios foram congelados antes da comparação: redução mínima de 20%, perda máxima de PR AUC 0,03, ROC AUC 0,015, recall/precision 0,05, aumento de Brier 0,01, perda de lead mediano 3 ciclos, latência mediana/p90 de 3/5 ciclos, nenhuma falha antecipada perdida, falso alerta adicional máximo de 0,25 por unidade, stale e unavailable nulos, degraded até 75% e idade máxima de três ciclos. São critérios experimentais de seleção no FD001, não safety objectives regulatórios e não sustentam uma redução universal.

## Impacto observado na validation

| Configuração | Requisitos afetados | Métricas degradadas | Métricas melhoradas | Hipóteses afetadas | Novos controles/evidência |
| --- | --- | --- | --- | --- | --- |
| Full | SRQ061, SRQ062, SRQ065 | Nenhuma por referência | Controle de equivalência | ASM032 | Comparação estrita de features/scores e teste de prefixo |
| K=2 | SRQ062, SRQ066, SRQ067, SRQ068 | Recall, lead e calibração caem com HLV | Redução de bytes de 49,87% | ASM028, ASM030, ASM031 | Idade máxima 1; status degraded explícito |
| K=3 | SRQ062, SRQ066, SRQ067, SRQ068 | Perdas maiores de antecedência; sem stale no limite 3 | Redução de bytes de 66,57% | ASM028, ASM029 | Idade máxima 2; selecionada para retraining pareado |
| K=5 | SRQ043, SRQ062, SRQ066, SRQ067 | Stale 19,84%, unavailable, recall e lead | Maior redução entre intervalos | ASM028/ASM030 não suportadas para este K | Staleness rompe persistência e remove a configuração dos gates |
| `subset_train17` | SRQ061, SRQ062, SRQ064, SRQ065 | Nenhuma mensurável na rota full-trained | Redução de bytes de 25%; 71,43% dos valores de sensores transmitidos | ASM028, ASM029, ASM032 | Schema coincide com os 17 canais usados pelo treino; retraining pareado |
| Adaptive q95 | SRQ062, SRQ065–068 | Recall/lead e calibração em H15/H30 | Redução de bytes de 32,39% | ASM028, ASM029, ASM033 | Threshold `0,0081177469` somente do treino; idade máxima 3 |
| Adaptive q99 | SRQ062, SRQ065–068 | Perdas fortes de recall, lead e calibração | Redução de bytes de 62,58% | ASM028, ASM029, ASM033 | Threshold `0,0103196927` somente do treino; idade máxima 3 |

As métricas completas por modelo, horizonte, estado e unidade estão em `reports/telemetry_filtering/artifacts/development_metrics.parquet` e nos arquivos de previsões. PR AUC, ROC AUC e Brier usam apenas probabilidades disponíveis e carregam cobertura e denominadores completos; stale, degraded e unavailable não são apagados.

## Mudanças de assurance e FMEA

Foram adicionados os requisitos SRQ061–SRQ069 para equivalência Full, fluxo causal ponta a ponta, semântica de HLV, treino pareado, seleção reproduzível, denominadores, métricas temporais, critérios pré-especificados e gate do `test_internal`. A FMEA inclui previsão feita com dados completos, HLV contado como nova amostra, recuperação de sensores omitidos, artefatos incompatíveis, exclusão de stale/unavailable dos denominadores, ausência de alerta convertida em atraso e alteração após o teste. A árvore lógica inclui esses ramos sob preprocessing e filtragem; permanece qualitativa e não quantificada.

## Freeze e avaliação interna

O manifesto `reports/telemetry_filtering/freeze_manifest.json` registra hashes da configuração, código, partições, thresholds, critérios, candidatos e artefatos. Somente Full e candidatas que passam todos os gates finais de validation podem ser abertas no `test_internal`. A leitura possui recibo próprio, uma única vez, sem reajuste posterior. O projeto já havia lido essa partição na fase 0.9.0; portanto esta é uma avaliação congelada específica da mudança de telemetria, não um holdout historicamente virgem. O teste NASA oficial continua fora do escopo.

### Evidência final congelada

Após o freeze, somente Full e `subset_train17` foram lidos uma vez no
`test_internal`. A redução do subconjunto foi 25%; no pior caso observado a
PR AUC caiu 0,00062 (fusão H15) e o Brier aumentou 0,00034 (fusão H30).
XGBoost H30 melhorou PR AUC em 0,00021. Nenhum cenário aprovado aumentou
staleness, `degraded`, `unavailable` ou `missed_anticipated_failures`. Estes
valores são evidência específica do FD001 e do split congelado.

| comparação | H | Δ PR AUC (subset − Full) | Δ recall | Δ Brier | Δ lead mediano |
| --- | ---: | ---: | ---: | ---: | ---: |
| XGBoost | 15 | +0,00154 | +0,00444 | −0,00003 | 0 |
| XGBoost | 30 | +0,00021 | +0,00444 | +0,00014 | 0 |
| hazard | 15 | 0,00000 | 0,00000 | 0,00000 | 0 |
| hazard | 30 | 0,00000 | 0,00000 | 0,00000 | 0 |
| fusão | 15 | −0,00062 | +0,02222 | +0,00002 | 0 |
| fusão | 30 | −0,00056 | −0,00222 | +0,00034 | −2 |
