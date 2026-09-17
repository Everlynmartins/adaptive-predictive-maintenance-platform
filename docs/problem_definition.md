# Problema de manutenção preditiva — FD001

O contrato canônico 0.4.0 está em [prediction_contract.md](prediction_contract.md).
Este documento mantém o contexto e os níveis conceituais definidos na EDA.

## População, evento e informação disponível

O caso considera motores do treino original FD001 com trajetórias completas
até a falha, já divididas por unidade. Desenvolvimento = treino + validação.
A análise e os candidatos a sensores usam apenas o treino.
Testes interno e oficial permanecem reservados.

T_i é o ciclo terminal da unidade i; t é o ciclo observado; F_it contém
somente telemetria e histórico disponíveis até t. O objetivo futuro é:

`p_H(i,t) = P(0 < T_i - t <= H | T_i > t, F_it)`.

É a probabilidade de falha nos próximos H ciclos de um ativo operacional,
não uma taxa instantânea de falha ou uma estimativa de RUL. A hipótese de
término como falha vale para essas trajetórias completas, não para censura.

## Alvos de avaliação

- `RUL = max(T_i - t, 0)`: inteiro em ciclos, sem teto artificial.
- `failure_within_horizon = (RUL <= H)`.
- `failure_within_critical_horizon = (RUL <= H_critical)`.
- `is_operational = (RUL > 0)`: máscara de avaliação prospectiva.

A fronteira é inclusiva: em H=30, RUL=30 é positivo e RUL=31 é negativo.
O terminal RUL=0 fica preservado com ambos os alvos positivos. Para treinamento,
calibração e avaliação do risco condicionado a T_i>t, excluir esse ciclo usando
a máscara; `build_operational_targets` fornece essa população. Isso implica até H+1
positivos por trajetória, ou H em registros ainda operacionais.

RUL é preservado para avaliação de erro em ciclos, horizonte e antecedência.
Alvos conhecidos retrospectivamente não são escores preditos.
As tabelas contêm somente chaves e resultados, separadas da telemetria.
Os metadados gravam horizontes e proveniência. Não inferir falha a partir do
máximo observado em teste oficial truncado ou ativos em serviço.

## Horizontes e alertas experimentais

`configs/fd001_eda.toml` define H=30 e H_critical=15 ciclos. São inteiros
positivos configuráveis, com H_critical < H. **Não são regras industriais,
limites de segurança ou thresholds definitivos.**
Probabilidades coerentes devem satisfazer p_critical <= p_H.

| Nível | Interpretação futura |
| --- | --- |
| normal | Monitoramento de rotina. |
| atenção | Evidência inicial ou incerta que exige acompanhamento. |
| alerta | Risco no horizonte principal que justifique planejamento. |
| crítico | Risco no horizonte curto que justifique priorização. |

Nenhum nível por observação ou threshold foi implementado. Limiares,
persistência, histerese e escalada serão definidos com validação:
precisão/recall, PR-AUC, Brier/calibração, falsos alarmes por motor/exposição,
antecedência, cobertura de eventos e custos. Respeitar dependência por
unidade e excluir falhas já ocorridas das métricas prospectivas.

## Proteção contra vazamento de informação

RUL real, ciclo terminal, vida normalizada, alvos binários e máscara operacional
nunca serão atributos. O eixo retrospectivo `(t - 1)/(T_i - 1)` e a
centralização por trajetória completa são exclusivamente ferramentas de EDA.
Normalizadores futuros serão ajustados no treino; janelas devem ser causais.
Testes só serão usados após congelar decisões. `unit_id` é chave.

Nenhum treinamento, calibração ou validação operacional foi feito nesta etapa.
