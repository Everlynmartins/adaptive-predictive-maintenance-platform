# Requisitos de segurança e confiabilidade do demonstrador

## SRQ052

- requirement_id: SRQ052
- statement: Toda política de filtragem deve processar uma observação por vez, rejeitar ciclos não crescentes por unidade e não acessar observações futuras.
- source: solicitação da etapa de filtragem; SRQ001; SRQ018
- rationale: Preservar causalidade e impedir que a decisão de transmitir antecipe mudanças futuras.
- validation_method: Revisar a fronteira sequencial e a semântica de estado por unidade.
- verification_method: Testar ordem estrita e invariância das decisões de prefixo à inclusão de sufixos futuros.
- status: verified

## Requisitos da TCN temporal (0.12.0)

## SRQ070

- requirement_id: SRQ070
- statement: Toda sequência TCN deve conter somente observações da mesma `unit_id` até a origem t, sem atravessar unidade ou incluir t+1.
- source: prediction_contract.md; Prompt 11
- rationale: Preservar causalidade temporal e impedir vazamento.
- validation_method: Revisar a construção contra o conjunto de informação causal.
- verification_method: Testar invariância a sufixos, fronteira por unidade e alinhamento da origem.
- status: verified

## SRQ071

- requirement_id: SRQ071
- statement: Sequências curtas devem usar padding somente à esquerda, máscara binária explícita e padding neutro após normalização do treino.
- source: SRQ070; projeto da TCN
- rationale: Impedir que padding seja interpretado como telemetria.
- validation_method: Revisar semântica da máscara e da origem.
- verification_method: Testar posição, máscara adversarial e sequência curta.
- status: verified

## SRQ072

- requirement_id: SRQ072
- statement: A TCN deve produzir riscos H15/H30 em [0,1] com H30 maior ou igual a H15 por parametrização.
- source: prediction_contract.md; coerência de horizontes
- rationale: Os eventos são aninhados.
- validation_method: Confirmar interpretação da cabeça conjunta.
- verification_method: Testar fórmula, limites e violações em validation.
- status: verified

## SRQ073

- requirement_id: SRQ073
- statement: Normalização, seleção de época e estado aprendido devem usar somente treino; validation não pode participar do early stopping.
- source: SRQ011; regra de holdout
- rationale: Evitar ajuste indireto à avaliação.
- validation_method: Revisar separação das partições.
- verification_method: Testar disjunção agrupada e inspecionar provenance.
- status: verified

## SRQ074

- requirement_id: SRQ074
- statement: O checkpoint deve preservar schema, versão, features, horizontes, configuração, normalização e pesos, rejeitando incompatibilidades.
- source: SRQ005; SRQ009; configuration management
- rationale: Impedir uso silencioso de artefato incompatível.
- validation_method: Revisar checkpoint e model card.
- verification_method: Testar save/load e schema incompatível.
- status: verified

## SRQ075

- requirement_id: SRQ075
- statement: A execução deve versionar seed e solicitar determinismo; não determinismo residual de plataforma deve permanecer documentado.
- source: SRQ010; model card TCN
- rationale: Backends neurais podem variar entre ambientes.
- validation_method: Avaliar a política de reprodutibilidade local.
- verification_method: Testar repetição no mesmo ambiente e registrar a limitação entre plataformas.
- status: partial

## SRQ076

- requirement_id: SRQ076
- statement: Registrar parâmetros, tempos de seleção/ajuste/inferência, dispositivo e latência média por origem.
- source: objetivo comparativo do Prompt 11
- rationale: Interpretar desempenho junto ao custo local.
- validation_method: Confirmar que timings não são tratados como benchmark universal.
- verification_method: Inspecionar métricas e model card.
- status: verified

## SRQ077

- requirement_id: SRQ077
- statement: A TCN só pode entrar em fusão treinável após gerar OOF agrupado por `unit_id`; sem OOF deve permanecer excluída.
- source: SRQ039; política OOF da fusão
- rationale: Evitar previsão neural in-sample no meta-modelo.
- validation_method: Revisar compatibilidade com o stacking.
- verification_method: Conferir config/model card e ausência da TCN na fusão.
- status: verified

## SRQ078

- requirement_id: SRQ078
- statement: Entrada inválida, feature não finita ou sequência sem origem válida deve produzir status explícito, sem probabilidade aparentemente válida.
- source: SRQ004; SRQ007; contrato TCN
- rationale: Não ocultar falha de entrada.
- validation_method: Revisar estados contra o contrato geral.
- verification_method: Testar entrada inválida e saída indisponível.
- status: verified

## SRQ079

- requirement_id: SRQ079
- statement: Model card e relatório devem registrar arquitetura, seed, dependências, treino, contratos, horizontes, métricas, limitações e causas comuns.
- source: rastreabilidade e assurance do demonstrador
- rationale: Tornar a evidência interpretável sem alegar independência.
- validation_method: Revisar completude e limites de escopo.
- verification_method: Inspecionar os artefatos e sua ligação à matriz.
- status: verified

## SRQ080

- requirement_id: SRQ080
- statement: Toda atenção do Transformer deve impedir que a representação na posição t consulte qualquer posição posterior.
- source: prediction_contract.md; etapa Transformer
- rationale: Preservar causalidade dentro de cada camada de atenção.
- validation_method: Revisar a semântica da máscara triangular contra F_i,t.
- verification_method: Testar invariância do prefixo a sufixos distintos e forma exata da máscara.
- status: verified

## SRQ081

- requirement_id: SRQ081
- statement: Posição, padding e comprimento devem ser explícitos, determinísticos e compatíveis com a origem no último elemento válido.
- source: SRQ070; arquitetura Transformer
- rationale: Evitar perda ou deslocamento da ordem temporal.
- validation_method: Revisar posição relativa à janela e semântica do padding.
- verification_method: Testar posição, padding mascarado, shape e alinhamento da origem.
- status: verified

## SRQ082

- requirement_id: SRQ082
- statement: Transformer, TCN e baselines comparados devem usar as mesmas unidades, alvos operacionais e horizontes H15/H30.
- source: protocolo comparativo desta etapa
- rationale: Tornar as métricas comparáveis.
- validation_method: Revisar manifestos, chaves e definição do alvo.
- verification_method: Verificar loader, provenance e contagens de validation.
- status: verified

## SRQ083

- requirement_id: SRQ083
- statement: Normalização e seleção de época do Transformer devem usar apenas treino, com holdout interno agrupado e modelo final recriado.
- source: SRQ073; protocolo TCN
- rationale: Evitar seleção por validation.
- validation_method: Revisar o fluxo de ajuste e early stopping.
- verification_method: Testar disjunção e registrar unidades no provenance.
- status: verified

## SRQ084

- requirement_id: SRQ084
- statement: A cabeça deve produzir riscos H15/H30 em [0,1] e H30 maior ou igual a H15 sem reparo posterior.
- source: prediction_contract.md; SRQ072
- rationale: Preservar eventos probabilísticos aninhados.
- validation_method: Revisar a parametrização da cabeça.
- verification_method: Testar fórmula, limites e coerência em validation.
- status: verified

## SRQ085

- requirement_id: SRQ085
- statement: O checkpoint deve preservar arquitetura, posição, normalização, features, configuração e pesos, rejeitando schema incompatível.
- source: SRQ074; configuration management
- rationale: Impedir carregamento silencioso de artefato incompatível.
- validation_method: Revisar conteúdo do checkpoint e model card.
- verification_method: Testar save/load e schema inválido.
- status: verified

## SRQ086

- requirement_id: SRQ086
- statement: Parâmetros, checkpoint, tempo de treino/inferência e memória aproximada devem ser registrados com método e limitações.
- source: objetivo de custo da etapa Transformer
- rationale: Comparar desempenho com viabilidade local e futura edge.
- validation_method: Revisar se medidas não são apresentadas como benchmark universal.
- verification_method: Inspecionar métricas e model card.
- status: verified

## SRQ087

- requirement_id: SRQ087
- statement: Entrada, máscara, comprimento ou saída inválidos devem produzir erro ou status explícito, nunca risco aparentemente válido.
- source: SRQ078; contrato Transformer
- rationale: Não ocultar falha estrutural ou numérica.
- validation_method: Revisar comportamento de falha.
- verification_method: Testar máscaras/shapes inválidos, feature não finita e saída indisponível.
- status: verified

## SRQ088

- requirement_id: SRQ088
- statement: O Transformer não deve ser descrito como independente e só poderá entrar na fusão após OOF agrupado compatível.
- source: common_dependency_analysis.md; SRQ077
- rationale: Arquitetura diferente não elimina causas comuns nem leakage do stacking.
- validation_method: Revisar dependências e protocolo OOF.
- verification_method: Conferir documentação, config e ausência na fusão.
- status: verified

## SRQ089

- requirement_id: SRQ089
- statement: Model card e relatório devem registrar configuração, contratos, métricas, custos, limitações, dependências e provenance do Transformer.
- source: rastreabilidade do demonstrador
- rationale: Tornar resultados e trade-offs auditáveis.
- validation_method: Revisar completude dos artefatos.
- verification_method: Ligar artefatos e testes na matriz de rastreabilidade.
- status: verified

## SRQ053

- requirement_id: SRQ053
- statement: Cada transmissão deve registrar unit_id, cycle, timestamp lógico, sensores e quantidade de valores, bytes estimados, motivo e política.
- source: solicitação da etapa de filtragem; SRQ009
- rationale: Permitir rastrear o fluxo de informação que alimentará features e previsões.
- validation_method: Revisar se o pacote contém contexto suficiente para reproduzir a decisão local.
- verification_method: Inspecionar o contrato TelemetryPacket e testar conteúdo/contabilidade.
- status: verified

## SRQ054

- requirement_id: SRQ054
- statement: O receptor deve manter por sensor somente o último valor realmente transmitido, seu ciclo de observação, idade, indicador de transmissão no ciclo e validade; valor mantido não pode ser marcado como observação nova.
- source: solicitação da etapa de filtragem; HAZ005
- rationale: Evitar que hold-last-value oculte a idade efetiva da evidência.
- validation_method: Revisar a semântica observed/held/stale/unavailable para consumo futuro.
- verification_method: Testar retenção causal, idade, ciclo de origem e was_transmitted_this_cycle.
- status: verified

## SRQ055

- requirement_id: SRQ055
- statement: O limite de staleness deve ser configurável; sensor nunca recebido ou com idade acima do limite deve tornar telemetry_stale verdadeiro.
- source: SRQ017; SRQ043; solicitação da etapa de filtragem
- rationale: Impedir que dados ausentes ou antigos sejam tratados como estado atual.
- validation_method: Definir o limite adequado por fonte antes de experimento ou uso operacional.
- verification_method: Testar fronteira do limite e propagação de value_validity/telemetry_stale.
- status: verified

## SRQ056

- requirement_id: SRQ056
- statement: A cadência de inferência deve ser configurável entre cada ciclo e somente na chegada de nova telemetria, sem alterar a marca de observação dos valores mantidos.
- source: solicitação da etapa de filtragem
- rationale: Tornar explícita a relação entre comunicação, atualização do estado e execução preditiva.
- validation_method: Revisar o compromisso de latência e custo na futura comparação preditiva.
- verification_method: Testar inference_due nas duas cadências.
- status: verified

## SRQ057

- requirement_id: SRQ057
- statement: A contabilidade local deve registrar observações geradas/transmitidas, valores, bytes estimados, redução, frequência efetiva e tempo da política usando tamanhos e overhead configurados.
- source: solicitação da etapa de filtragem
- rationale: Permitir comparação reprodutível de comunicação sem alegar equivalência a protocolo real.
- validation_method: Revisar fórmula, tipos assumidos e limites da estimativa.
- verification_method: Testar contagens e cálculo de bytes contra exemplo conhecido.
- status: verified

## SRQ058

- requirement_id: SRQ058
- statement: FixedIntervalFilter deve respeitar K por unidade e SensorSubsetFilter deve transmitir somente sensores de uma seleção cuja fonte declarada seja train.
- source: solicitação da etapa de filtragem; SRQ002; SRQ028
- rationale: Evitar cadence incorreta e seleção de sensores contaminada por holdouts.
- validation_method: Revisar futuramente K/subset com métricas somente de desenvolvimento.
- verification_method: Testar ciclos transmitidos, subset, ausência e recusa de selection_source diferente de train.
- status: verified

## SRQ059

- requirement_id: SRQ059
- statement: AdaptiveTelemetryFilter deve usar somente estado causal, critérios configurados e anomaly_score auxiliar opcional; RUL, alvos e informação futura são proibidos em execução.
- source: solicitação da etapa de filtragem; SRQ001; SRQ008; SRQ018
- rationale: Permitir adaptação sem transformar desfechos retrospectivos em sinais de controle.
- validation_method: Avaliar futuramente sensibilidade, ativação e latência somente em desenvolvimento.
- verification_method: Testar bloqueio de nomes, prefixo, reprodução, motivos e duração do modo alto.
- status: verified

## SRQ060

- requirement_id: SRQ060
- statement: Configuração, motivos de envio, ativações e duração do modo de frequência alta devem ser reproduzíveis e rastreáveis.
- source: SRQ009; SRQ010; solicitação da etapa de filtragem
- rationale: Permitir análise de impacto e repetição do fluxo filtrado.
- validation_method: Revisar suficiência dos registros antes do experimento comparativo.
- verification_method: Repetir a mesma trajetória/configuração e comparar decisões e métricas determinísticas, exceto tempo de CPU.
- status: verified

## SRQ039

- requirement_id: SRQ039
- statement: O meta-modelo deve ser ajustado exclusivamente com previsões de treino out of sample, alinhadas por unit_id, cycle e horizon; sua avaliação OOF deve usar folds disjuntos por unit_id.
- source: solicitação da etapa de fusão; SRQ024
- rationale: Evitar que o stacking aprenda desempenho in-sample dos modelos base ou misture trajetórias correlacionadas.
- validation_method: Revisar a cadeia base OOF para meta cross-fit e sua adequação ao objetivo probabilístico.
- verification_method: Testar recusa de partições não OOF, disjunção de unidades e cobertura das chaves.
- status: verified

## SRQ040

- requirement_id: SRQ040
- statement: Cada previsão Weibull usada no treino da fusão deve vir de beta e eta ajustados sem a unidade prevista, usando os mesmos folds agrupados dos riscos base.
- source: solicitação da etapa de fusão; SRQ019; SRQ024
- rationale: Evitar que a duração terminal da própria unidade entre indiretamente no meta-modelo.
- validation_method: Revisar a unidade estatística e o papel age-only da Weibull.
- verification_method: Inspecionar fitting/holdout de cada fold e testar sobreposição vazia.
- status: verified

## SRQ041

- requirement_id: SRQ041
- statement: Calibração deve usar scores cross-fitted e comparação Platt/isotonic agrupada por unit_id, sem reutilizar prediction in-sample nem validation para ajustar o calibrador.
- source: solicitação da etapa de fusão; SRQ011
- rationale: Evitar estimativa otimista de calibração e manter unidades inteiras fora de cada ajuste.
- validation_method: Comparar Brier, log loss e comportamento extremo das alternativas.
- verification_method: Testar calibradores, folds e artefatos de seleção.
- status: verified

## SRQ042

- requirement_id: SRQ042
- statement: A fusão deve propagar validade da entrada; somente input_validity valid pode produzir risk_score.
- source: SRQ006; solicitação da etapa de fusão
- rationale: Impedir um score aparentemente utilizável sobre entrada inválida ou não verificada.
- validation_method: Revisar semântica de validade em cada adaptador futuro.
- verification_method: Testar combinações de status/validade e ausência de probabilidade inválida.
- status: verified

## SRQ043

- requirement_id: SRQ043
- statement: Telemetria considerada antiga pela política da fonte deve usar input_validity stale e não pode produzir saída probabilística válida.
- source: SRQ017; árvore lógica do aviso
- rationale: Evitar que evidência passada seja apresentada como estado atual.
- validation_method: Definir futuramente a janela de atualidade por fonte e frequência.
- verification_method: Testar o estado stale no contrato; timestamps e adaptador permanecem pendentes.
- status: partial

## SRQ044

- requirement_id: SRQ044
- statement: Quando parte dos componentes falhar e um fallback declarado ainda puder operar, a saída deve ser degraded e identificar os componentes usados e ausentes.
- source: solicitação da etapa de fusão; HAZ001
- rationale: Preservar disponibilidade limitada sem ocultar perda de evidência.
- validation_method: Revisar se o fallback é adequado a cada futura decisão simulada.
- verification_method: Testar média com componentes ausentes, mínimo de cobertura e component_status.
- status: verified

## SRQ045

- requirement_id: SRQ045
- statement: Quando não houver componentes suficientes ou a entrada não for válida, a saída deve ser unavailable, sem risk_score, survival_score ou health_score e com causa explícita.
- source: SRQ007; árvore lógica do aviso
- rationale: Não converter indisponibilidade em baixo risco.
- validation_method: Revisar comportamento do consumidor diante de ausência.
- verification_method: Testar indisponibilidade e proibição de risco zero implícito.
- status: verified

## SRQ046

- requirement_id: SRQ046
- statement: Método, folds, critério, parâmetros e métricas do calibrador devem ser versionados e rastreados até os scores OOF usados no ajuste.
- source: solicitação da etapa de fusão; SRQ009; FMEA de calibração
- rationale: Permitir reproduzir probabilidades e detectar troca de transformação.
- validation_method: Revisar Brier, log loss, reliability curve e risco de extremos.
- verification_method: Verificar model card, hashes, seleção e round-trip dos calibradores.
- status: verified

## SRQ047

- requirement_id: SRQ047
- statement: Thresholds de atenção, alerta e crítico devem ser estritamente ordenados, configurados, escolhidos somente em validation e rotulados como experimentais.
- source: solicitação da etapa de fusão; SRQ012; ASM005
- rationale: Evitar ajuste ao holdout e interpretação como limite aeronáutico real.
- validation_method: Revisar critérios de recall/precision e métricas por unidade; adequação operacional permanece aberta.
- verification_method: Testar ordem e inspecionar configuração, partição e freeze.
- status: partial

## SRQ048

- requirement_id: SRQ048
- statement: A política deve aplicar persistência temporal configurável e registrar seu efeito sobre primeiro alerta, antecedência e episódios por unidade.
- source: solicitação da etapa de fusão; FMEA de threshold
- rationale: Tornar explícito o compromisso entre oscilação e atraso de aviso.
- validation_method: Revisar episódios e lead time em validation antes do freeze.
- verification_method: Testar ciclos consecutivos e métricas temporais sem cruzar unit_id.
- status: verified

## SRQ049

- requirement_id: SRQ049
- statement: Cada artefato fusionado deve ser rastreável aos quatro modelos base, monitor analítico, meta-modelo, calibrador, configuração de horizonte e política de threshold.
- source: SRQ009; solicitação da etapa de fusão
- rationale: Detectar combinações incompatíveis e permitir análise de impacto.
- validation_method: Revisar suficiência do freeze e model card para reprodução da fase.
- verification_method: Verificar hashes, chaves, versões, manifests e rota serializada em validation.
- status: verified

## SRQ050

- requirement_id: SRQ050
- statement: anomaly_score não deve entrar na média de probabilidades; disagreement deve usar apenas riscos comparáveis, ser não negativo e ser descrito como divergência, não intervalo de confiança.
- source: prediction_contract.md; solicitação da etapa de fusão
- rationale: Preservar a semântica distinta dos indicadores auxiliares.
- validation_method: Revisar contrato, relatório e uso do score no meta-modelo.
- verification_method: Testar média, covariável de anomalia e cálculo do disagreement.
- status: verified

## SRQ051

- requirement_id: SRQ051
- statement: test_internal só pode ser lido depois de congelar modelos, calibradores e thresholds; deve haver uma única avaliação registrada e nenhum resultado pode reajustar esta fase.
- source: solicitação da etapa de fusão; SRQ011
- rationale: Preservar interpretação de holdout final para a versão congelada.
- validation_method: Revisar sequência do protocolo e proibir decisões pós-teste.
- verification_method: Testar gate/recibo e conferir freeze anterior à leitura.
- status: verified

Identificadores estáveis; não são requisitos de certificação. `verified` significa
que o escopo de implementação especificado foi verificado pelos testes citados;
`partial` indica controles/evidências parciais; `planned` indica implementação futura.
Nenhum status afirma adequação operacional, calibração ou aprovação independente.
Validação examina a correção e completude do requisito para o objetivo; verificação
examina a implementação. As revisões de coerência desta etapa são internas.
A [matriz](traceability_matrix.csv) liga requisitos a evidências e pendências.

## SRQ035

- requirement_id: SRQ035
- statement: O detector de anomalia deve usar exclusivamente features causais e publicar anomaly_score com semântica não probabilística, sem conversão automática para risk_score.
- source: prediction_contract.md: anomaly_score; solicitação Isolation Forest
- rationale: Evitar que desvio estatístico seja interpretado como probabilidade de evento.
- validation_method: Revisar escala, população de referência e separação entre anomalia e risco.
- verification_method: Testar nomes proibidos, orientação, finitude e contrato de saída.
- status: verified

## SRQ036

- requirement_id: SRQ036
- statement: A população saudável para ajuste deve ser selecionada somente no treino por regra RUL versionada; validation e testes não podem definir ou ajustar esse limite.
- source: solicitação Isolation Forest; SRQ011
- rationale: Evitar ajuste do detector à avaliação e registrar hipótese de normalidade.
- validation_method: Revisar adequação experimental da regra RUL>60 e seu impacto nos scores.
- verification_method: Testar caminhos lidos, máscara saudável por fold e manifesto/configuração.
- status: verified

## SRQ037

- requirement_id: SRQ037
- statement: Scores OOF devem usar folds disjuntos por unit_id, com feature engineer e detector reajustados no conjunto de fitting; o detector final deve usar treino completo e somente aplicar em validation.
- source: SRQ024; solicitação Isolation Forest
- rationale: Evitar contaminação de unidade e estado aprendido nas saídas futuras de análise/fusão.
- validation_method: Revisar unidade estatística e cobertura OOF.
- verification_method: Testar disjunção, cobertura, reprodução e isolamento de test_internal/teste oficial.
- status: verified

## SRQ038

- requirement_id: SRQ038
- statement: O detector deve preservar configuração, referência saudável e resultados após save/load; entrada inválida deve produzir status explícito e score ausente.
- source: SRQ005–SRQ010; monitoring_architecture.md
- rationale: Evitar monitor aparentemente disponível com estado incompatível.
- validation_method: Revisar suficiência de metadados e limitação dos estados no demonstrador offline.
- verification_method: Testar round-trip, reprodutibilidade, score finito e indisponibilidade explícita.
- status: verified

## SRQ001

- requirement_id: SRQ001
- statement: Cada atributo em t deve depender somente do histórico causal da própria unidade até t e de estado aprendido no treino.
- source: prediction_contract.md: histórico causal
- rationale: Evitar antecipação artificial do evento.
- validation_method: Revisar definição de disponibilidade e proveniência de cada futura transformação.
- verification_method: Testar invariância ao alterar o sufixo posterior a t em cada transformador futuro.
- status: partial

## SRQ002

- requirement_id: SRQ002
- statement: Features não devem conter RUL, vida normalizada, tempo terminal, máximo final de ciclo, alvos ou qualquer derivação futura.
- source: prediction_contract.md: variáveis proibidas
- rationale: Manter separação entre evidência disponível e verdade retrospectiva.
- validation_method: Revisar caminhos de dados e aliases com o objetivo causal.
- verification_method: Testar bloqueio de nomes e mutação; revisar proveniência e testar futuras features.
- status: partial

## SRQ003

- requirement_id: SRQ003
- statement: RiskPrediction deve aceitar risk_score somente como real finito em [0,1] quando available, e None nos demais estados.
- source: prediction_contract.md: probabilidade e estados
- rationale: Impedir valores impossíveis ou ausência disfarçada de risco zero.
- validation_method: Revisar limites e semântica de ausência; limite numérico não comprova calibração.
- verification_method: Testar extremos, valores não finitos, tipos inválidos e ausência.
- status: verified

## SRQ004

- requirement_id: SRQ004
- statement: A interface de predição e cada RiskPrediction devem exigir horizonte inteiro positivo explícito em ciclos.
- source: prediction_contract.md: horizonte
- rationale: Evitar comparar probabilidades referentes a eventos temporais diferentes.
- validation_method: Revisar unidade, fronteira inclusiva e tratamento de horizonte não suportado.
- verification_method: Inspecionar assinatura e testar ausência, valor inválido e serialização do horizonte.
- status: verified

## SRQ005

- requirement_id: SRQ005
- statement: Cada previsão deve conter model_name e model_version não vazios, associados ao artefato produtor quando existir.
- source: prediction_contract.md: estrutura de saída
- rationale: Permitir identificar qual implementação e estado produziram o resultado.
- validation_method: Revisar se identificação é suficiente para reproduzir o resultado.
- verification_method: Testar campos obrigatórios; futuramente verificar correspondência ao manifesto do modelo.
- status: partial

## SRQ006

- requirement_id: SRQ006
- statement: A validade da entrada deve ser explícita; available exige valid e validação de esquema, qualidade, causalidade e atualidade aplicável.
- source: safety_reliability_scope.md: HAZ004
- rationale: Evitar que consumidores interpretem como confiável uma entrada não verificada.
- validation_method: Revisar regras por fonte e limites da evidência de validade.
- verification_method: Testar estados incompatíveis e validador FD001; causalidade e atualidade de fontes futuras pendentes.
- status: partial

## SRQ007

- requirement_id: SRQ007
- statement: Saída sem probabilidade deve preservar chave e horizonte, usar status explícito, escores principais None e explanation não vazia.
- source: safety_reliability_scope.md: HAZ001
- rationale: Não converter indisponibilidade em ausência de risco.
- validation_method: Revisar como o consumidor reconhecerá falha e causa.
- verification_method: Testar unavailable/not_operational, explicação obrigatória e proibição de zero substituto.
- status: verified

## SRQ008

- requirement_id: SRQ008
- statement: Risk_score e anomaly_score devem ter campos e semânticas distintos; nenhuma conversão implícita será permitida.
- source: prediction_contract.md: escores auxiliares
- rationale: Desvio estatístico não é probabilidade de evento futuro.
- validation_method: Revisar interpretação do detector e qualquer futuro adaptador de risco.
- verification_method: Testar registro com anomalia fora de [0,1] sem alteração do risco; revisar futuros adaptadores.
- status: partial

## SRQ009

- requirement_id: SRQ009
- statement: Resultados devem rastrear dados, partição, configuração, código e, quando existirem, modelo, features e thresholds por versões e hashes.
- source: safety_reliability_scope.md: HAZ006
- rationale: Detectar resultados produzidos com artefatos incompatíveis.
- validation_method: Revisar completude da cadeia de proveniência por caso de uso.
- verification_method: Verificar manifestos e correspondência de hashes; ampliar para artefatos preditivos futuros.
- status: partial

## SRQ010

- requirement_id: SRQ010
- statement: Execuções devem registrar configuração, seed, versões e entradas para reprodução no ambiente declarado.
- source: decisions.md: D001, D011, D012
- rationale: Distinguir variação de código, dados e aleatoriedade.
- validation_method: Revisar o que precisa permanecer fixo para comparar resultados.
- verification_method: Testar repetição da divisão e registrar ambiente; equivalência de modelos futura.
- status: partial

## SRQ011

- requirement_id: SRQ011
- statement: Seleção de features usa apenas treino; validation orientará ajustes; test_internal só após congelar decisões; teste oficial reservado à avaliação futura.
- source: decisions.md: D011, D013; solicitação desta etapa
- rationale: Evitar ajuste às unidades de avaliação e estimativa otimista.
- validation_method: Revisar papéis de partições e critérios de congelamento.
- verification_method: Testar disjunção por unidade e isolamento da EDA; verificar futuros consumidores.
- status: partial

## SRQ012

- requirement_id: SRQ012
- statement: Thresholds futuros devem ser versionados e justificados por métricas de validação, sem usar teste para ajustá-los.
- source: problem_definition.md: alertas; HAZ002, HAZ003, HAZ007
- rationale: Conectar alerta à decisão simulada e controlar falsos alertas/omissões.
- validation_method: Revisar métricas, custos e adequação dos horizontes com a finalidade simulada.
- verification_method: No futuro, testar carregamento/versionamento e reproduzir escolha em validation.
- status: planned

## SRQ013

- requirement_id: SRQ013
- statement: Mudanças relevantes devem registrar análise de impacto, revalidar requisitos afetados e verificar regressões antes de reutilizar resultados.
- source: safety_reliability_scope.md: HAZ007
- rationale: Evitar uso de evidência que a mudança tornou inválida.
- validation_method: Revisar cobertura do template para modelo, features, thresholds, telemetria, dados e dependências.
- verification_method: Inspecionar registros preenchidos e matriz por mudança; template disponível, processo contínuo.
- status: partial

## SRQ014

- requirement_id: SRQ014
- statement: Em trajetórias completas, calcular RUL=max(T_i-t,0) por unidade, preservando zero terminal e sem teto superior artificial.
- source: prediction_contract.md: RUL
- rationale: Manter referência retrospectiva correta e sem mistura de motores.
- validation_method: Revisar definição de evento/completude e fronteira terminal.
- verification_method: Testar zero, não negatividade, decréscimo e unidades intercaladas de tamanhos distintos.
- status: verified

## SRQ015

- requirement_id: SRQ015
- statement: O alvo por horizonte deve ser inclusivo RUL<=H; a população probabilística deve excluir T_i<=t e não inferir falha de trajetória censurada.
- source: prediction_contract.md: população e censura
- rationale: Distinguir previsão de evento futuro e descrição de evento já ocorrido.
- validation_method: Revisar população operacional e caso de seguimento insuficiente.
- verification_method: Testar fronteiras, seleção RUL>0 e rejeição de censura; integração ao futuro fit/evaluate pendente.
- status: partial

## SRQ016

- requirement_id: SRQ016
- statement: Survival_score deve ser 1-risk_score e health_score 100 vezes survival_score, ambos None sem probabilidade.
- source: prediction_contract.md: escores complementares
- rationale: Evitar interpretação independente de saúde ou percentual de vida restante.
- validation_method: Revisar interpretação visual dependente do horizonte e migração de escala.
- verification_method: Testar complementos, extremos e rejeição de saúde fornecida inconsistente.
- status: verified

## SRQ017

- requirement_id: SRQ017
- statement: Fontes futuras devem definir atualidade e disponibilidade temporal; telemetria stale/unknown não pode sustentar saída available.
- source: safety_reliability_scope.md: HAZ005
- rationale: Ciclo ordenado sozinho não demonstra atualidade da informação.
- validation_method: Revisar timestamps, recebimento e política de idade máxima para a fonte.
- verification_method: Testar incompatibilidade de estados agora; verificar detecção de atraso quando houver fonte temporal.
- status: partial

## SRQ018

- requirement_id: SRQ018
- statement: Antes do uso de filtragem, verificar causalidade e avaliar seu impacto na antecedência, disponibilidade e falsos alertas em validation.
- source: safety_reliability_scope.md: HAZ008
- rationale: Filtro causal também pode atrasar sinais úteis.
- validation_method: Revisar comparação de política filtrada e referência para a decisão simulada.
- verification_method: Testar prefixos e estado temporal agora; futuramente comparar métricas/latência nas mesmas unidades de validation.
- status: partial

## SRQ019

- requirement_id: SRQ019
- statement: O baseline de confiabilidade deve ser Weibull de dois parâmetros com localização zero, ajustado por máxima verossimilhança a uma duração por unidade de treino e sem sensores.
- source: escopo da etapa Weibull 2P
- rationale: Estabelecer referência populacional por idade sem confundir ciclos repetidos com tempos de vida independentes ou implementar forma de três parâmetros.
- validation_method: Revisar se a forma e a população respondem ao papel de baseline, mantendo sua adequação estatística como hipótese testável.
- verification_method: Testar ajuste, parâmetros positivos, rejeição de sensores e manifesto com 70 eventos, zero censuras e uma duração por unidade.
- status: verified

## SRQ020

- requirement_id: SRQ020
- statement: O baseline deve fornecer densidade, CDF, sobrevivência, hazard, hazard acumulado e risco condicional `1-S(t+H)/S(t)`, respeitando limites e monotonicidade no horizonte.
- source: escopo da etapa Weibull 2P e prediction_contract.md
- rationale: Tornar a semântica estatística explícita e verificável independentemente de uma aplicação.
- validation_method: Revisar as funções contra a parametrização Weibull 2P e o evento/horizonte do contrato.
- verification_method: Testar S(0), complementos, não negatividade, limites, H=0 e monotonicidade por H.
- status: verified

## SRQ021

- requirement_id: SRQ021
- statement: O modelo salvo deve preservar parâmetros, configuração de identidade, contagens, verossimilhança e manifesto; o model card deve registrar contrato, hipóteses, limitações, métricas e hash SHA-256 do artefato.
- source: SRQ005, SRQ009, SRQ010 e escopo da etapa
- rationale: Permitir reprodução, inspeção e detecção de troca do artefato.
- validation_method: Revisar se metadados permitem interpretar e reproduzir a previsão dentro do ambiente declarado.
- verification_method: Testar round-trip save/load, igualdade de previsões/configuração, esquema estrito e correspondência do hash no model card.
- status: verified

## SRQ022

- requirement_id: SRQ022
- statement: A Weibull deve ser ajustada somente no treino e avaliada somente em ciclos operacionais de validation para H=15 e H=30, com métricas globais, curvas de confiabilidade e resultados por unidade; nenhum teste ou sensor deve ser lido.
- source: SRQ011, SRQ015 e escopo da etapa
- rationale: Preservar holdouts, condicionamento T_i>t e dependência intraunidade visível.
- validation_method: Revisar população, métricas, limites da interpretação por linha e adequação dos dois horizontes.
- verification_method: Testar os únicos caminhos/colunas lidos, horizontes e artefatos; conferir 15 unidades e 3.045 ciclos operacionais na execução real.
- status: verified

## SRQ023

- requirement_id: SRQ023
- statement: Toda feature temporal deve usar somente o prefixo da própria unidade até t; janelas devem ser alinhadas à direita, reiniciar por `unit_id` e permanecer invariantes quando ciclos posteriores a t são alterados ou anexados.
- source: prediction_contract.md: conjunto de informação causal; predictive_function_fmea.md: erro de preprocessing
- rationale: Evitar antecipação do evento e contaminação entre motores.
- validation_method: Revisar cada definição de feature contra a informação disponível no instante t e a fronteira de unidade.
- verification_method: Testar invariância a sufixos futuros, reinício por unidade, acumulação e janelas causais.
- status: verified

## SRQ024

- requirement_id: SRQ024
- statement: Previsões OOF de treino devem usar folds disjuntos por `unit_id`, reajustando seleção, imputação e modelo dentro de cada fold, e fornecer exatamente uma previsão por chave elegível, modelo e horizonte.
- source: SRQ001, SRQ002, SRQ011; solicitação da etapa clássica
- rationale: Evitar que linhas correlacionadas da mesma trajetória ou estado aprendido no holdout contaminem as previsões destinadas à fusão.
- validation_method: Revisar a unidade estatística dos folds e a finalidade futura das previsões OOF.
- verification_method: Testar disjunção/cobertura dos folds, reprodução por seed, caminhos lidos e unicidade/cobertura das saídas.
- status: verified

## SRQ025

- requirement_id: SRQ025
- statement: O ajuste supervisionado clássico (RF/XGBoost) deve registrar e aplicar tratamento explícito do desbalanceamento e da contribuição desigual de trajetórias com durações diferentes.
- source: eda_report.md: desbalanceamento e dependência temporal; solicitação da etapa clássica
- rationale: Evitar que a classe majoritária e motores mais longos dominem silenciosamente a função de ajuste.
- validation_method: Revisar se a ponderação é coerente com o objetivo por unidade e documentar suas limitações.
- verification_method: Verificar fórmula, contagens, faixa dos pesos e metadados de treinamento nos artefatos.
- status: verified

## SRQ026

- requirement_id: SRQ026
- statement: Cada modelo clássico por horizonte deve implementar o contrato comum, limitar scores a [0,1], recusar horizonte incompatível, sinalizar entrada inválida e preservar configuração e previsões após save/load.
- source: SRQ003–SRQ007; prediction_contract.md; solicitação da etapa clássica
- rationale: Permitir substituição controlada de modelos sem ocultar falhas de entrada ou incompatibilidade de artefato.
- validation_method: Revisar a semântica de probabilidade, indisponibilidade e identidade do artefato.
- verification_method: Testar limites, horizonte, status inválido, reprodução com seed e round-trip dos dois adaptadores.
- status: verified

## SRQ027

- requirement_id: SRQ027
- statement: Relatórios e model cards de modelos múltiplos devem identificar dados, alvos, preprocessing, runtime e avaliação compartilhados e não descrever diversidade algorítmica como redundância independente.
- source: arp_mapping.md: common cause awareness e independence awareness; safety_reliability_scope.md
- rationale: Evitar confiança indevida em concordância entre modelos sujeitos às mesmas causas de erro.
- validation_method: Revisar a completude da análise de dependências comuns e seu efeito em futura fusão.
- verification_method: Inspecionar model cards, relatório comparativo e `model_common_dependencies.md`.
- status: verified

## SRQ028

- requirement_id: SRQ028
- statement: Seleção, imputação e importância usada para interpretar features devem ser ajustadas ou calculadas sem usar validation ou testes para escolher variáveis; a importância por permutação do XGBoost deve usar holdouts OOF por unidade.
- source: SRQ011; solicitação da etapa clássica
- rationale: Preservar validation como avaliação de desenvolvimento e evitar seleção otimista.
- validation_method: Revisar a finalidade de cada partição e distinguir diagnóstico de importância de efeito causal.
- verification_method: Verificar folds e artefato de permutação agregado exclusivamente de holdouts OOF; confirmar que gain vem do treino completo.
- status: verified

## SRQ029

- requirement_id: SRQ029
- statement: Quando horizontes forem ajustados por modelos separados, a avaliação deve quantificar casos em que o risco do horizonte curto excede o do horizonte longo na mesma chave antes de interpretar as saídas conjuntamente.
- source: prediction_contract.md: coerência futura dos horizontes; resultados desta etapa
- rationale: Eventos aninhados exigem probabilidades não decrescentes com H; modelos separados não garantem essa propriedade.
- validation_method: Revisar a consequência da incoerência para níveis e decisões simuladas.
- verification_method: Parear previsões por `(unit_id, cycle)` e registrar contagem, fração e magnitude máxima das violações.
- status: verified

## SRQ030

- requirement_id: SRQ030
- statement: Precision, recall e F1 devem registrar o threshold usado; thresholds exploratórios não podem ser apresentados como política operacional de alerta.
- source: SRQ012; problem_definition.md; solicitação da etapa clássica
- rationale: Separar avaliação binária provisória de uma decisão de manutenção que exige custos e critérios de aceitação.
- validation_method: Revisar a interpretação do limiar e a ausência de adequação operacional.
- verification_method: Testar cálculo com threshold explícito e inspecionar relatório/configuração/model cards.
- status: verified
## SRQ031

- requirement_id: SRQ031
- statement: Landmarks devem congelar features e idade na origem t, gerar k=1..Hmax e manter desfechos separados das entradas; preprocessing/scaler usam somente treino do fold.
- source: prediction_contract.md: hazard discreto; SRQ001, SRQ002, SRQ024
- rationale: Impedir sensores futuros, mistura de unidades e ajuste ao holdout.
- validation_method: Revisar informação disponível na origem contra a definição condicional do hazard.
- verification_method: Testar prefixos, máscaras, disjunção e estado aprendido por fold.
- status: verified

## SRQ032

- requirement_id: SRQ032
- statement: O evento deve ser positivo somente em k=T−t; passos após evento ou censura devem ser excluídos da perda; endpoints por unidade devem ser consistentes.
- source: solicitação hazard discreto; prediction_contract.md: censura; SRQ015
- rationale: Não converter acompanhamento desconhecido em ausência de falha ou incluir pós-evento.
- validation_method: Revisar fronteira inclusiva e interpretação de acompanhamento incompleto.
- verification_method: Comparar máscaras esperadas e perda com expansão explícita; testar censura sintética.
- status: verified

## SRQ033

- requirement_id: SRQ033
- statement: Hazards e sobrevivências devem ser finitos em [0,1]; um único modelo deve produzir prefixos iguais, sobrevivência não crescente e risco não decrescente com H dentro do suporte treinado.
- source: contrato probabilístico; solicitação hazard discreto; SRQ003, SRQ004, SRQ029
- rationale: Eventos aninhados exigem coerência probabilística; falhas numéricas não podem virar saída disponível.
- validation_method: Revisar produto pela regra da cadeia, sem pressupor independência entre passos.
- verification_method: Testar limites, prefixos e coerência; registrar violações OOF e validation.
- status: verified

## SRQ034

- requirement_id: SRQ034
- statement: O hazard deve sinalizar entrada inválida, rejeitar falha de convergência e preservar parâmetros, scaler, schema/configuração e previsões após save/load; salvar OOF por unidade e proveniência.
- source: SRQ005–SRQ010, SRQ024; modos de falha específicos do hazard
- rationale: Evitar resultados indisponíveis ou não reproduzíveis apresentados como probabilidades válidas.
- validation_method: Revisar suficiência da proveniência e significado dos estados no demonstrador offline.
- verification_method: Testar estados, convergência, persistência, cobertura OOF e hash do card.
- status: verified

## SRQ061

- requirement_id: SRQ061
- statement: FullTelemetryFilter deve reproduzir chaves, features, scores, status e alertas da rota completa dentro da tolerância versionada antes de qualquer comparação de redução.
- source: mudança de arquitetura de filtragem; prediction_contract.md
- rationale: Sem uma referência equivalente, uma diferença pode ser defeito da nova rota e não efeito da telemetria.
- validation_method: Confirmar que a equivalência é requisito suficiente para interpretar a comparação no FD001.
- verification_method: Comparar por `(unit_id, cycle, horizon)` e registrar a maior diferença absoluta antes da seleção.
- status: verified

## SRQ062

- requirement_id: SRQ062
- statement: Toda previsão sob filtragem deve ser calculada somente a partir do estado reconstruído no receptor e de features refeitas causalmente; artefatos de telemetria completa não podem ser unidos posteriormente.
- source: prediction_contract.md; mudança de fluxo de informação
- rationale: Impedir leakage de sensores omitidos e preservar a fronteira causal emissor-receptor.
- validation_method: Revisar o fluxo completo e a semântica do adaptador receiver-aware.
- verification_method: Testar reconstrução, schema, prefixos e previsões filtradas sem join do frame fonte.
- status: verified

## SRQ063

- requirement_id: SRQ063
- statement: Valor hold-last-value deve preservar ciclo de origem, idade e flag de transmissão; deltas, janelas, variação e slope só podem avançar quando uma observação nova for transmitida.
- source: docs/prediction_contract.md; SRQ023; D048
- rationale: Repetir HLV como amostra nova altera artificialmente a dinâmica temporal.
- validation_method: Revisar a definição das features receiver-aware e sua compatibilidade com a rota Full.
- verification_method: Testar hold, invariância a valores fonte não transmitidos e slope com ciclos reais.
- status: verified

## SRQ064

- requirement_id: SRQ064
- statement: Configurações matched devem refazer filtro, receptor, features, preprocessing, modelos, calibração e fusão por fold de `unit_id`, sem estado aprendido do holdout.
- source: SRQ024; protocolo de redução de telemetria
- rationale: Evitar OOF otimista quando o regime de telemetria muda o vetor de entrada.
- validation_method: Revisar unidade de reamostragem e suficiência do protocolo pareado.
- verification_method: Inspecionar manifests de folds, ausência de overlap, OOF e artefatos por política.
- status: verified

## SRQ065

- requirement_id: SRQ065
- statement: Grade, seeds, políticas, thresholds derivados, hashes e regra de seleção devem ser versionados e reproduzíveis usando apenas treino e validation.
- source: SRQ011; change_impact_template.md
- rationale: Tornar decisões de redução auditáveis antes do holdout.
- validation_method: Revisar se a configuração cobre todos os graus de liberdade relevantes.
- verification_method: Reexecutar por seed e conferir hashes/manifests.
- status: partial

## SRQ066

- requirement_id: SRQ066
- statement: Métricas de redução devem preservar todas as oportunidades de inferência e registrar cobertura, stale, degraded, unavailable, idade, bytes e ciclos omitidos; estados indisponíveis não podem ser descartados silenciosamente.
- source: SRQ043; protocolo de filtragem
- rationale: Excluir ciclos difíceis pode inflar desempenho aparente.
- validation_method: Revisar denominadores e a separação entre métricas probabilísticas disponíveis e métricas de serviço.
- verification_method: Conferir tabelas por política/modelo/horizonte e contagens por status.
- status: verified

## SRQ067

- requirement_id: SRQ067
- statement: First alert, lead time, episódios, persistência e latência devem ser pareados por unidade, modelo e horizonte; ausência de alerta deve ser explícita e contar como falha antecipada perdida.
- source: SRQ012; contrato de alertas experimentais
- rationale: Não transformar ausência de alerta em atraso finito conveniente.
- validation_method: Revisar a semântica de alerta e o tratamento de lacunas/stale.
- verification_method: Testar a máquina temporal e o pareamento Full versus filtrado.
- status: verified

## SRQ068

- requirement_id: SRQ068
- statement: Critérios de aceitação da redução devem ser configuráveis, rotulados como experimentais, salvos e congelados antes da leitura de `test_internal`.
- source: safety_assumptions.md; solicitação do experimento
- rationale: Separar seleção científica no FD001 de objetivos regulatórios.
- validation_method: Revisar se limites e denominadores são completos para a pergunta experimental.
- verification_method: Conferir hash da configuração no freeze manifest e impedir alteração pós-teste.
- status: partial

## SRQ069

- requirement_id: SRQ069
- statement: A fase de redução deve abrir `test_internal` somente uma vez após o freeze, produzir recibo por configuração congelada e proibir qualquer reajuste ou seleção posterior; a exposição histórica da fase 0.9 deve ser declarada.
- source: SRQ051; reports/fusion/test_evaluation_receipt.json
- rationale: Proteger a avaliação específica da mudança sem alegar que o conjunto é historicamente virgem.
- validation_method: Revisar o gate e a distinção entre holdout da fase e exposição do projeto.
- verification_method: Testar manifesto/recibo one-shot e registros de candidatos congelados.
- status: verified

## SRQ090

- requirement_id: SRQ090
- statement: Explicações locais do XGBoost devem usar o modelo e o preprocessing congelados, registrar direção e magnitude relativa no espaço de contribuição declarado e não atribuir causalidade ou significado físico não documentado aos sensores.
- source: prediction_contract.md; solicitação da etapa de explicabilidade
- rationale: Impedir que uma decomposição do modelo seja apresentada como mecanismo físico ou causa do evento.
- validation_method: Revisar a semântica de SHAP, a unidade da contribuição e os limites de interpretação.
- verification_method: Testar ranking, direção, magnitude relativa e schema; conferir consistência das previsões do artefato carregado.
- status: verified

## SRQ091

- requirement_id: SRQ091
- statement: A estrutura integrada de explicação deve manter riscos probabilísticos, `anomaly_score`, `disagreement`, status, validade e staleness em campos semanticamente distintos; anomalia e disagreement não podem ser apresentados como probabilidade ou intervalo de confiança.
- source: prediction_contract.md; monitoring_architecture.md; common_dependency_analysis.md
- rationale: Evitar interpretações incompatíveis de indicadores auxiliares e ocultação da validade da entrada.
- validation_method: Revisar a estrutura contra os contratos de risco, anomalia e fusão.
- verification_method: Testar schema, limites exclusivos dos campos de risco e aceitação separada de indicadores auxiliares finitos não negativos.
- status: verified

## SRQ092

- requirement_id: SRQ092
- statement: A auditoria de calibração deve registrar Brier, curva de confiabilidade, ECE e, quando identificáveis, intercepto e inclinação de calibração, incluindo status explícito quando o ajuste não puder ser calculado.
- source: SRQ041; solicitação da etapa de calibração
- rationale: Uma métrica isolada não caracteriza frequência observada, desvio global e distorção da escala probabilística.
- validation_method: Revisar definições, bins, população avaliada e condições de identificabilidade.
- verification_method: Testar ECE, ajuste logístico e tratamento explícito de classe ou previsão degenerada.
- status: verified

## SRQ093

- requirement_id: SRQ093
- statement: Intervalos empíricos de métricas temporais devem reamostrar `unit_id` completos, separar cópias repetidas da mesma unidade e registrar réplicas em que cada métrica não pôde ser calculada.
- source: dependência temporal do FD001; solicitação da etapa de incerteza
- rationale: Linhas da mesma trajetória não são observações independentes e métricas podem ser indefinidas em certas reamostragens.
- validation_method: Revisar a unidade estatística e a interpretação limitada dos intervalos percentis.
- verification_method: Testar preservação da trajetória, duplicatas, reprodução por seed e contagem de réplicas inválidas.
- status: verified

## SRQ094

- requirement_id: SRQ094
- statement: Relatórios de requisitos devem distinguir validação da redação e suficiência do requisito de verificação da implementação; nenhum requisito pode ser marcado verified sem implementação, evidência e teste objetivo existente.
- source: arp_mapping.md; definição formal de validação e verificação do projeto
- rationale: Evitar usar revisão metodológica e teste de código como evidências intercambiáveis.
- validation_method: Revisar os critérios dos dois relatórios e a cobertura de todos os requirement_id.
- verification_method: Comparar requisitos, matriz, testes existentes e relatórios; executar a verificação de rastreabilidade.
- status: verified

## SRQ095

- requirement_id: SRQ095
- statement: Reason codes devem ser derivados de scores, política congelada e contribuições reais do modelo, identificar seu método de origem e não declarar causalidade, diagnóstico físico ou adequação operacional.
- source: SRQ047; SRQ090; solicitação da etapa de explicabilidade
- rationale: Textos plausíveis sem vínculo numérico podem induzir decisões não sustentadas pela evidência.
- validation_method: Revisar exemplos corretos e falsos contra os artefatos numéricos e limites de linguagem.
- verification_method: Conferir chaves, contribuições, thresholds congelados e reason codes no artefato de explicações.
- status: verified

