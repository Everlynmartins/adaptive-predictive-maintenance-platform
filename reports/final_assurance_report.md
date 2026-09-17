# Relatório final de assurance da fase local — FD001

## Escopo

Este relatório encerra a configuração 0.16.0 do demonstrador local. O pacote
usa conceitos de organização de engenharia inspirados em SAE ARP4754B e SAE
ARP4761A para requisitos, validação, verificação, rastreabilidade, hipóteses,
modos de falha, dependências e mudanças. Não declara conformidade, certificação
ou segurança operacional. NASA C-MAPSS FD001 é um benchmark simulado.

## Arquitetura final e função

O fluxo local contém ingestão validada, partições por unidade, features causais,
modelos versionados, calibração/fusão, monitor analítico de anomalia, receptor
de telemetria filtrada, explicações, aplicação CLI/Streamlit e assurance. A
função é estimar de forma reproduzível o risco de atingir o evento terminal do
benchmark em H=15 ou H=30 e fornecer indicadores auxiliares para uma decisão
simulada de manutenção.

## Contrato preditivo

Para uma origem operacional t, `risk_score_i,t,H` estima
`P(T_i <= t+H | I_i,t, T_i > t)`. `survival_score=1-risk_score` e
`health_score=100*survival_score`; health é somente representação visual
dependente de H. `anomaly_score` é anormalidade e `disagreement` é divergência
entre probabilidades comparáveis. Nenhum deles é intervalo de confiança.

## Requisitos, validação e verificação

Os 95 requisitos possuem source, rationale, métodos de validação/verificação e
status. A matriz mantém a mesma ordem e liga implementação, evidência e testes.
Na baseline auditada, 77 estão `verified`, 17 `partial` e um `planned`. A
validação de requisitos avaliou clareza, necessidade, consistência,
verificabilidade, rastreabilidade e completude; a verificação só marcou como
verified os itens com evidência objetiva. Requisitos parciais refletem limites
reais como atualidade física, contexto operacional e configuration management.

## Hipóteses

As 52 hipóteses têm `impact_if_false` e status permitido: 37 `open`, 14
`confirmed` e uma `invalidated`. As abertas incluem transferibilidade do FD001,
adequação de janelas/arquiteturas únicas, interpretação de ciclo, estabilidade
de thresholds, censura futura, atualização física da telemetria e suficiência
das 15 unidades de validation. Elas não são tratadas como fatos.

## Modelos e versões

Weibull 2P, Random Forest, XGBoost, hazard discreto, Isolation Forest, fusão,
TCN e Transformer possuem model card versão 1.0.0. A fusão combina somente
Weibull/RF/XGBoost/hazard; Isolation Forest permanece covariável de anomalia e
TCN/Transformer ficam fora por não possuírem OOF neural aprovado. Hashes dos
cards e artefatos estão no `configuration_index.md` e no JSON da auditoria.

## Resultados principais e calibração

Em validation, o Transformer foi o melhor comparador individual: H15
Brier 0,007844, PR AUC 0,987997 e ROC AUC 0,998966; H30 Brier 0,017680,
PR AUC 0,983398 e ROC AUC 0,997069. A fusão congelada obteve H15 Brier
0,012694, PR AUC 0,973083, ROC AUC 0,997760 e H30 Brier 0,025415,
PR AUC 0,960961, ROC AUC 0,988694. O Transformer não substitui a fusão.

O diagnóstico de calibração da fusão registrou ECE 0,010208, intercepto
0,831342 e slope 0,998545 em H15; ECE 0,022204, intercepto 1,138545 e slope
0,999480 em H30. Os intervalos de métricas usam 1.000 reamostragens de
trajetórias completas por `unit_id`, registrando réplicas não calculáveis.

## Telemetria filtrada

`subset_train17` foi a única configuração aprovada nos critérios experimentais
em validation. Ela transmite observações a cada ciclo, 17 sensores do schema
selecionado e reduz 25% dos bytes estimados sem staleness, `degraded` ou
`unavailable`. No test_internal congelado, a diferença de PR AUC variou de
-0,00062 a +0,00021 e o Brier mudou no máximo 0,00034; nenhuma falha
antecipada foi perdida. K=5 reduziu 79,77%, mas gerou 59,93% de saídas
degraded e 19,84% unavailable, portanto foi rejeitado. Esses resultados não
definem porcentagem universalmente segura.

## Modos de falha e árvore lógica

A FMEA interna cobre entrada/feature inválida, preprocessing, indisponibilidade,
calibração/threshold, fusão, monitor, filtros, TCN, Transformer e aplicação.
Controles com evidência apontam para testes, manifests e relatórios reais. A
árvore conceitual usa como top event “aviso não fornecido com antecedência
requerida” e organiza telemetria, preprocessing, modelos, risco, calibração,
threshold, filtragem e apresentação. Ela não é quantificada e não presume
independência entre ramos.

## Dependências comuns e monitoring architecture

Ensemble, Isolation Forest, TCN e Transformer compartilham telemetria,
população FD001, evento/alvo, partições, runtime e parte da preparação. Eles
oferecem diversidade analítica, sem evidência de independência. O Isolation
Forest pode revelar desvio multivariado, mas pode falhar junto com modelos
quando dados, preprocessing ou runtime falham. A aplicação apresenta sua
indisponibilidade explicitamente.

## Configuration index e problem reports

`docs/configuration_index.md` identifica dados, splits, configs, features,
thresholds, versões, artefatos e ambiente. A auditoria encontrou e corrigiu:
acesso desnecessário ao endpoint retrospectivo no modo nominal, ausência de
validação de probabilidade persistida, seletores/versões codificados e texto de
assurance obsoleto. Caches foram removidos. O pacote histórico `predmain.zip`
foi preservado mas excluído da baseline. A ausência de commit Git permanece
problema aberto controlado por versão e hashes.

## Verificação executável

`final-assurance-local` confere campos de requisitos,
alinhamento da matriz, referências de testes, hipóteses, splits, features
proibidas, folds OOF, isolamento do teste oficial, cards, caches e simula três
unidades até a fronteira anterior ao evento. Unidades 1, 26 e 28 produziram,
respectivamente, 191, 198 e 164 origens válidas, sem risco fora de [0,1]. Os
testes controlados cobrem telemetria ausente/stale, modelo ausente, artefato
incompatível, risco inválido, preprocessing inválido e componente de fusão
indisponível, sempre com `degraded` ou `unavailable` explícito. Todos os checks
passaram após a remoção controlada dos caches temporários; os testes foram
executados com bytecode e cache do pytest desabilitados.

A regressão final aprovou **165 testes e 226 subtests em 47,46 s**, com três
warnings de depreciação internos do SHAP. `pip check` não encontrou dependências
quebradas e a auditoria encerrou com `failed_checks=[]`.

## Limitações

- benchmark simulado com uma única condição FD001 e 15 unidades de validation;
- test_internal já teve exposições congeladas documentadas, não é avaliação
  externa historicamente virgem;
- ciclo não é tempo físico e não há timestamps de recebimento, sensor real,
  enlace, edge ou cloud;
- thresholds, critérios de telemetria, reason codes e métricas são experimentais;
- nenhuma análise formal de safety de uma função real foi executada;
- não há commit Git na configuração local atual.

## Trabalho futuro

Docker, MLflow/MLOps, cloud, streaming, edge real, dados reais de equipamentos,
contexto de manutenção real, integração com arquitetura de sistema real e
análise formal de safety somente quando existirem funções, failure conditions,
severidades, requisitos e dados operacionais apropriados.
