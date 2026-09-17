# Mecanismo local de filtragem de telemetria

## Escopo

Esta entrega implementa políticas sequenciais locais e o estado causal do
receptor. Não executa comparação de desempenho preditivo, não lê
`test_internal` ou o teste oficial NASA e não modela hardware, enlace,
protocolo aeronáutico, cloud ou streaming externo.

## Contrato sequencial

`TelemetryFilter.process` recebe uma única `TelemetryRecord`. Para cada unidade,
o ciclo precisa ser estritamente maior que o último processado. A decisão usa
somente a observação corrente e estado anterior; acrescentar um sufixo futuro
não altera decisões já produzidas. `filter` é uma conveniência que reinicia a
política e chama `process` na ordem recebida.

Um pacote contém `unit_id`, `cycle`, `logical_timestamp`, mapa e nomes dos
sensores transmitidos, quantidade de valores, bytes estimados, motivo do envio
e nome da política. O timestamp é lógico e usa o ciclo por padrão. Ele não é
timestamp físico de aquisição ou recebimento.

## Políticas

- `FullTelemetryFilter`: transmite todos os valores em todo ciclo.
- `FixedIntervalFilter`: transmite a primeira observação e depois uma observação
  completa quando passaram pelo menos K ciclos desde o último envio da unidade.
- `SensorSubsetFilter`: transmite em todo ciclo apenas o subset declarado. O
  construtor exige `selection_source="train"`; a configuração inicial usa os
  sensores com tendência retrospectiva identificada somente no treino pela EDA.
- `AdaptiveTelemetryFilter`: usa intervalo estável reduzido e entra em modo de
  alta frequência por duração configurável quando mudança absoluta, relativa,
  desvio da média móvel causal, variação causal ou `anomaly_score` auxiliar
  excede seu critério. RUL, alvo e informação futura são bloqueados.

Média e variação adaptativas incluem somente o histórico anterior da unidade e
o valor corrente quando necessário. O score de anomalia continua indicador
auxiliar e não é convertido em probabilidade.

## Receptor e hold-last-value

Quando não há transmissão, o receptor preserva o último valor realmente
recebido. Para cada sensor publica:

| Campo | Semântica |
| --- | --- |
| `last_observed_cycle` | Ciclo do último pacote que continha o sensor. |
| `sensor_age_cycles` | Ciclo atual menos `last_observed_cycle`. |
| `was_transmitted_this_cycle` | Verdadeiro somente se o pacote corrente continha o sensor. |
| `value_validity` | `valid_observed`, `valid_held`, `stale` ou `unavailable`. |

`telemetry_stale` é verdadeiro quando qualquer sensor requerido está `stale`
ou `unavailable`. Com limite L, o valor fica stale quando sua idade é maior que
L. Valor mantido nunca recebe `last_observed_cycle` novo.

`inference_cadence="each_cycle"` marca inferência em todo ciclo com o estado
mais recente, inclusive para que o consumidor possa tratar staleness.
`"on_transmission"` marca inferência apenas quando chega pacote novo.

## Contabilidade local

Para V valores transmitidos, tamanho configurado b por valor e overhead m:

`bytes_estimados_pacote = m + V*b`.

A referência full soma a mesma expressão usando todos os valores gerados em
cada ciclo. A redução é `1 - bytes_transmitidos/bytes_full`. Isso é uma
estimativa analítica local e não reproduz cabeçalhos, codificação, compressão,
retransmissão ou timing de qualquer protocolo real.

Métricas: observações geradas/transmitidas, valores transmitidos, bytes, redução,
frequência efetiva e tempo de decisão medido com relógio local. Para adaptive,
também ativações, motivos, ciclos e durações do modo de alta frequência.

## Exemplo determinístico pequeno

Exemplo com 7 ciclos, 2 sensores, 8 bytes por valor e 16 bytes de metadata.
Adaptive usa valores `[0,0,0,10,10,10,10]`, intervalo estável 4, mudança
absoluta 5 e modo alto por 3 ciclos.

| Política | Ciclos transmitidos | Observações | Valores | Bytes | Redução vs full |
| --- | --- | ---: | ---: | ---: | ---: |
| Full | 1,2,3,4,5,6,7 | 7 | 14 | 224 | 0,00% |
| Fixed K=3 | 1,4,7 | 3 | 6 | 96 | 57,14% |
| Subset de 1 sensor | 1,2,3,4,5,6,7 | 7 | 7 | 168 | 25,00% |
| Adaptive | 1,4,5,6 | 4 | 8 | 128 | 42,86% |

No adaptive, o ciclo 4 ativa `absolute_change:sensor_a`; o modo alto dura os
ciclos 4–6. No Fixed K=3 com staleness L=1, no ciclo 2 o valor do ciclo 1 é
`valid_held` com idade 1; no ciclo 3 é `stale` com idade 2; no ciclo 4 um pacote
novo redefine idade para zero.

## Limitações e próxima evidência

Os thresholds da configuração adaptive são pontos iniciais, não foram avaliados
contra risco, lead time ou calibração. O subset deriva somente da EDA de treino,
mas ainda precisa de ablação preditiva. O experimento futuro deverá reajustar
features/modelos quando exigido, usar validation para decisões e preservar o
gate congelado dos holdouts.
