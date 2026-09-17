# Assurance case do demonstrador local FD001

Este argumento simples organiza claim, argumento, evidência e limitações. Ele é
inspirado em práticas de organização de engenharia e não declara conformidade
com SAE ARP4754B/ARP4761A, certificação, segurança operacional ou adequação à
manutenção real.

## Claim principal

O pipeline local implementa de forma reproduzível a estimativa de risco por
horizonte no benchmark FD001 e mantém evidências de validação, verificação,
rastreabilidade e análise de impacto das principais decisões de modelagem.

## Argumentos e evidências

| claim subordinado | argument | evidence | limitations |
| --- | --- | --- | --- |
| O evento e a probabilidade estão definidos sem ambiguidade. | RUL, alvo inclusivo H15/H30, sobrevivência condicionada, risk, health, anomaly e disagreement possuem semânticas separadas. | `prediction_contract.md`; testes de contrato e alvos. | FD001 tem evento terminal simulado; censura operacional não foi observada. |
| Features e sequências respeitam o histórico causal. | Estado é reiniciado por unidade, janelas terminam em t e nomes retrospectivos são bloqueados. | Testes de prefixo, fronteira por motor, TCN/Transformer, manifesto de 324 features e auditoria final. | Testes não provam ausência de todo alias semântico futuro em outra fonte. |
| Desenvolvimento e avaliação controlam reutilização de unidades. | Splits, folds OOF, stacking e calibradores são agrupados por `unit_id`; test_internal só é aberto após freeze da decisão correspondente. | Split/fold manifests, OOF audit, freeze manifests e recibos. | A partição teve exposição histórica documentada e não representa avaliação externa. |
| Saídas inválidas não são ocultadas. | Contratos propagam `input_validity` e estados `valid`, `degraded`, `unavailable`; risco inválido ou componente incompatível não vira valor plausível. | Testes de aplicação/fusão e simulações de falha controlada. | Não há transporte físico, relógio de recebimento nem recuperação operacional. |
| Resultados científicos são rastreáveis. | Model cards, configurações, hashes, relatórios, requisitos, hipóteses e matriz ligam cada família às evidências. | `configuration_index.md`, cards e `traceability_matrix.csv`. | Ausência de commit Git reduz a força da identidade do código. |
| A redução de telemetria é tratada como mudança de informação. | O receptor HLV preserva idade/origem; políticas são comparadas contra Full e impacto é documentado. | `telemetry_filtering_report.md`, change impact, FMEA e árvore lógica. | Bytes e latência são proxies locais; não representam enlace real. |
| Diversidade não é chamada de independência. | Modelos, monitor, ensemble e redes compartilham dados, alvo, runtime e parte do preprocessing. | `common_dependency_analysis.md` e `monitoring_architecture.md`. | Nenhuma análise de independência de desenvolvimento/física foi realizada. |

## Limite da conclusão

As evidências sustentam somente a implementação local e reproduzível no FD001.
Elas não demonstram segurança de aeronave, certificação, aeronavegabilidade,
generalização industrial, tarefa real de manutenção ou despacho. Requisitos
parciais, hipóteses abertas e problemas abertos continuam visíveis; nenhum foi
convertido em fato para encerrar artificialmente a fase.

