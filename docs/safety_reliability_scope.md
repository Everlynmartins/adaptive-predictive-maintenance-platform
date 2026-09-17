# Escopo de segurança e confiabilidade do demonstrador

## Função e fronteira

Extensão 0.7.0: hazard discreto landmark logístico com avaliação de desenvolvimento.
Mantêm-se todos os limites de interpretação, ausência de política operacional,
severidades regulatórias e alegações de conformidade. Coerência dos horizontes
é uma propriedade matemática, não evidência de adequação a manutenção real.

Fornecer estimativas reproduzíveis de risco de atingir o evento terminal do
benchmark em horizonte configurável e fornecer indicadores auxiliares de
degradação para apoiar uma decisão simulada de manutenção.

Essa é a função pretendida; a versão 0.6.0 contém contratos, dados preparados,
EDA, controles iniciais, Weibull 2P, Random Forest e XGBoost com features
causais. A Weibull foi rejeitada como forma global dos tempos de treino; os
modelos clássicos têm apenas avaliação de desenvolvimento. Nenhum é modelo
físico. O sistema é exclusivamente local, não comanda ativos e não recomenda
manutenção real. A versão 0.9.0 implementa calibração e uma política inicial de
alertas somente para decisão simulada no FD001; filtragem operacional permanece
ausente.

Na versão 0.8.0, Isolation Forest acrescenta um monitor analítico de desvio
multivariado. Ele não altera a função principal de estimar risco, não controla
ativos e não constitui monitor independente. Seu escopo, latência e limites
estão em `monitoring_architecture.md`.

Na versão 0.9.0, stacking e média simples combinam probabilidades comparáveis,
com status explícito, calibração e thresholds selecionados em validation. Uma
única avaliação congelada foi executada em `test_internal`. Esses resultados
não constituem validação industrial nem alteram o escopo conceitual SAE.

Na versão 0.10.0, filtros sequenciais e receptor HLV tornam idade, validade,
staleness e cadência explícitos. A versão 0.11.0 executou a comparação causal
no receptor e congelou apenas `subset_train17` para avaliação interna. A versão
0.15.0 adicionou aplicação local offline e a 0.16.0 fechou o pacote de
assurance. Não há comunicação real, política industrial ou controle de ativo.

As referências SAE são delimitadas em [arp_mapping.md](arp_mapping.md). Os
estados abaixo são **failure conditions internas do demonstrador apenas para
organização da engenharia**. Não equivalem a failure conditions de aeronave
real e não recebem classificação regulatória de severidade.

## Estados indesejados e observação futura

| ID no registro | Estado indesejado | Como poderá ser percebido |
| --- | --- | --- |
| HAZ001 | Saída probabilística indisponível quando solicitada. | Status, causa e fração de solicitações sem escore. |
| HAZ002 | Risco subestimado próximo ao evento terminal. | Eventos não cobertos, antecedência insuficiente, calibração. |
| HAZ003 | Risco superestimado com excesso de falsos alertas. | Falsos alertas por unidade/exposição e precisão. |
| HAZ004 | Entrada inválida aceita como válida. | Violações de esquema/causalidade não bloqueadas. |
| HAZ005 | Telemetria antiga tratada como atual. | Diferença entre instante do dado, recebimento e previsão. |
| HAZ006 | Perda de rastreabilidade entre dados, configuração e modelo. | Ausência/inconsistência de hashes, versões e manifesto. |
| HAZ007 | Mudança de modelo ou threshold sem revalidação. | Artefatos/evidências incompatíveis com a configuração ativa. |
| HAZ008 | Atraso de alerta causado por filtragem de telemetria. | Antecedência menor ao comparar execução causal filtrada e referência. |

Esses estados são cenários de projeto. As avaliações Weibull e clássica fornecem
evidência de aderência, discriminação e calibração, sem encerrar HAZ002/HAZ003. Causas,
requisitos e evidências estão no
[hazard_log.md](hazard_log.md). Falta de probabilidade não deve aparecer como
risco zero ou saúde 100; o status deve ser visível ao consumidor futuro.

## Propagação, causas compartilhadas e independência

Uma entrada antiga aceita pode gerar feature defasada, escore atrasado e
alerta simulado tardio. Um rótulo contaminado pode afetar simultaneamente
treinamento, calibração e avaliação. Filtragem excessiva pode remover informação
útil mesmo sendo causal; causalidade sozinha não garante antecedência.

Modelos com algoritmos diferentes podem compartilhar erros de origem dos
dados, partição, feature, rótulo ou dependência. Concordância entre modelos não
prova correção; disagreement pequeno não demonstra independência. Avaliar
causas compartilhadas e diversidade de evidência futuramente, sem multiplicar
probabilidades presumindo independência. Revisão e testes desta etapa foram
feitos no mesmo fluxo de desenvolvimento, sem alegação de independência formal.

O raciocínio de manutenção limitar-se-á a comparação simulada entre cobertura,
antecedência, falsos alertas e indisponibilidade. Não há orçamento probabilístico
de certificação, limite de despacho, tarefa obrigatória de manutenção, severidade
regulatória ou safety objective regulatório. Ingestão/EDA anteriores e partições
foram preservadas; teste oficial NASA continua reservado.

A análise inspirada em FMEA está em
[predictive_function_fmea.md](predictive_function_fmea.md) e as dependências
compartilhadas em [model_common_dependencies.md](model_common_dependencies.md).
