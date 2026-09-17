# CHG-0.7.0 — modelo landmark

Data: 2026-09-13. Revisão interna no mesmo fluxo de desenvolvimento.
Versão anterior 0.6.0, proposta 0.7.0; nova família sob RiskModel.

| Aspecto | Avaliação |
| --- | --- |
| Requisitos | SRQ001/002/003/004/006/009/010/011/015/024 e novos SRQ031–034; SRQ025 explicita o escopo clássico de sua ponderação. |
| Hipóteses | ASM016–018 abertas; ASM011 permanece aberta, sem dados reais censurados. |
| Estados indesejados | HAZ001/002/003/004/006/007; FMEA estendida sem severidade/RPN. |
| Métricas | Brier, log loss, ROC AUC, AP e calibração; coerência em H por construção, sem inferir calibração. |
| Regressão | Evento inclusivo, censura, perda/gradiente, prefixos, unidade, folds, round-trip, falhas numéricas e suíte anterior. |
| Artefatos regenerados | Somente novos artefatos hazard em reports/discrete_hazard; versão instalada e docs. Modelos anteriores não reajustados. |
| Interpretação | Logit aditivo e perda composta com peso por passo, sem balanceamento. H15/30 são prefixos de um modelo, não modelos independentes. |
| Dados/partições | Somente treino/validation preparados. Nenhuma alteração nos dados ou acesso analítico aos testes. |
| Dependências | SciPy, joblib e threadpoolctl já instalados, agora explicitamente declarados; versão/scaler/hash no card. |
| Causas comuns | Features, dados, folds, runtime e avaliação compartilhados com RF/XGB. |
| Reversão | Desativar comando hazard e usar artefatos anteriores preservados; não requer regenerar dados. |

Foi identificada uma lacuna defensiva: a validação de features verificava nomes
depois de gerar sufixos; um campo bruto RUL poderia se tornar RUL__current.
Agora nomes retrospectivos são rejeitados também na entrada do transformador.
O hazard restringe seu vocabulário aos nomes revisados do gerador. Nenhum campo
proibido foi encontrado no schema real anterior de 26 colunas; resultados
anteriores não precisam ser regenerados. Aliases arbitrários ainda exigem revisão.

Validação: revisão da coerência entre informação na origem, evento discreto e
objetivo do demonstrador. Adequação estatística/operacional permanece aberta.
Verificação: testes e execução registrados em reports/discrete_hazard_verification.txt
e docs/progress.md. Testes não validam censura não informativa ou uso industrial.
Critério de aceitação de software: testes passam, sem falha de convergência,
OOF completo e coerência em H. Não é critério de desempenho operacional.
