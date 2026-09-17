# Análise de modos de falha da função preditiva

## Extensão de filtragem de telemetria — 0.10.0

| failure_mode | local_effect | higher_level_effect_on_demonstrator | detection_means | current_controls | linked_requirements | evidence |
| --- | --- | --- | --- | --- | --- | --- |
| Pacote perdido | Receptor não atualiza sensores enviados. | Features envelhecem e o aviso pode atrasar ou ficar indisponível. | Ausência de pacote, idade por sensor e `telemetry_stale`. | HLV preserva último valor com ciclo original; ausência não vira observação nova. | SRQ054; SRQ055 | testes de HLV, idade e staleness. |
| Pacote atrasado | Evidência chega depois do ciclo pretendido. | Inferência pode representar um estado ultrapassado. | Comparação futura entre timestamp lógico, recebimento e ciclo. | Ordem não crescente é rejeitada; contrato registra timestamp lógico. Transporte real ainda não existe. | SRQ052; SRQ053; SRQ055 | contrato sequencial; ASM004 permanece aberta. |
| Sensor omitido | Pacote não contém sensor exigido ou subset exclui sinal útil. | Feature fica indisponível ou perde capacidade preditiva. | Schema declarado, validade por sensor e futura comparação de desempenho. | Subset explícito, selecionado somente no treino; receptor mantém apenas schema declarado. | SRQ053; SRQ054; SRQ058 | teste de subset e `selection_source=train`. |
| Valor antigo interpretado como atual | HLV é tratado como nova medição. | Risco parece atualizado e o aviso pode atrasar. | `last_observed_cycle`, `sensor_age_cycles` e flag de transmissão. | Estados `valid_observed`, `valid_held`, `stale`, `unavailable`; staleness configurável. | SRQ054; SRQ055 | teste de valor mantido sem nova observação. |
| Frequência adaptativa não ativada | Mudança causal não satisfaz critério ou score auxiliar falta. | Evidência relevante continua em cadência reduzida. | Motivos, ativações, idade e medição de lead time. | Critérios configuráveis e envio imediato quando ocorre trigger. | SRQ059; SRQ060 | testes de ativação e `reports/telemetry_filtering_report.md`; limitação permanece aberta. |
| Frequência adaptativa presa em modo alto | Critério ruidoso renova continuamente o modo alto. | Redução de bytes desaparece e custo local aumenta. | Duração e ciclos de alta frequência por episódio. | Duração configurável e métricas de ativações/motivos; thresholds ainda experimentais. | SRQ057; SRQ059; SRQ060 | métricas adaptativas verificadas; ASM029 open. |
| Contagem de bytes incorreta | Economia estimada não corresponde ao contrato de tipos. | Comparação de políticas induz decisão errada. | Reconciliação entre quantidade de valores, overhead e total. | `metadata_overhead_bytes` e `value_bytes` versionados; fórmula simples testada. | SRQ053; SRQ057 | teste com valores e resultado conhecidos. |

Os modos descrevem a camada local do demonstrador. Perda, atraso e bytes são
representações analíticas; nenhum protocolo, enlace ou hardware aeronáutico foi
modelado. O experimento causal de redução está documentado em
`reports/telemetry_filtering_report.md`.

## Extensão de fusão e política de alertas — 0.9.0

| failure_mode | local_effect | higher_level_effect_on_demonstrator | detection_means | current_controls | linked_requirements | evidence |
| --- | --- | --- | --- | --- | --- | --- |
| Meta-modelo ajustado com previsão in-sample | Relação base/target fica otimista. | Risco e thresholds aparentam funcionar melhor do que fora da amostra. | Proveniência `train_oof`, folds e auditoria de chaves. | `fit_frame` recusa partição diferente de train_oof; base e meta são cross-fitted por unidade. | SRQ039; SRQ040 | testes de meta OOF e `reports/fusion/oof_audit.json`. |
| Probabilidades base desalinhadas | Score de outro motor, ciclo ou horizonte entra na fusão. | Aviso incorreto e rastreabilidade perdida. | Join one-to-one por `(unit_id,cycle,horizon)`. | Chaves duplicadas/ausentes interrompem a execução. | SRQ039; SRQ049 | auditoria OOF: zero duplicatas/ausências. |
| Calibrador ajustado no próprio score in-sample | Frequências estimadas ficam otimistas. | Thresholds usam risco numericamente enganoso. | Manifesto de cross-fitting e comparação de calibradores. | Calibrador aprende de scores cross-fitted; Platt/isotonic avaliados por folds de unidade. | SRQ041; SRQ046 | `metrics.json:calibration_selection`; testes de calibrador. |
| Calibração extrema | Isotonic produz 0/1 em amostra pequena. | Log loss cresce e positivos podem receber risco zero. | Brier, log loss e inspeção de limites. | Escolha por log loss OOF entre Platt/isotonic; Platt selecionado. | SRQ046 | execução de desenvolvimento 0.9.0. |
| Componente ausente ocultado | Fusão aparenta risco baixo com evidência incompleta. | Aviso pode não ocorrer sem indicação de falha. | `component_status` e `prediction_status`. | Média simples declara `degraded`; stacking fica `unavailable`; ausência nunca vira zero. | SRQ044; SRQ045 | testes de status degradado/indisponível. |
| Telemetria antiga aceita como atual | Scores coerentes são calculados sobre estado passado. | Aviso atrasado. | Futuro timestamp de evento/recebimento e política de staleness. | `input_validity=stale` existe e impede probabilidade válida. | SRQ042; SRQ043 | contrato testado; FD001 não contém timestamps. |
| Threshold excessivamente alto ou baixo | Omissões ou falsos alertas aumentam. | Antecedência insuficiente ou excesso de episódios. | Métricas validation por linha/unidade e análise de episódios. | Critérios, thresholds e partição são versionados. | SRQ047 | `configs/fusion_alert_policy.toml`; métricas de validation. |
| Persistência inadequada | Ruído é emitido ou evidência útil é atrasada. | Episódios falsos ou redução da antecedência. | Primeiro alerta, lead time e durações por unidade. | Três ciclos configuráveis; efeito permanece explícito. | SRQ048 | Parquet de métricas por unidade. |
| `anomaly_score` tratado como probabilidade | Média perde interpretação probabilística. | Risk score sem semântica do contrato. | Revisão das colunas e teste da média. | Anomalia só é covariável do stacking; disagreement usa quatro riscos. | SRQ050 | teste de separação e model card. |
| Resultado de test_internal usado para reajuste | Holdout deixa de ser avaliação congelada. | Métrica final fica otimista. | Freeze anterior, recibo único e gate contra repetição. | Teste só abre após congelar modelos, calibradores e thresholds. | SRQ051 | `freeze_manifest.json` e recibo final. |

Os modos compartilham causas descritas em `common_dependency_analysis.md`; a
presença de vários algoritmos não autoriza tratá-los como barreiras independentes.

## Extensão do monitor de anomalia — 0.8.0

| failure_mode | local_effect | higher_level_effect_on_demonstrator | detection_means | current_controls | linked_requirements | evidence |
| --- | --- | --- | --- | --- | --- | --- |
| Monitor indisponível | Não há anomaly_score para a observação. | Evidência auxiliar ausente pode ser confundida com normalidade. | `prediction_status=unavailable`, explicação e cobertura futura. | Contrato explícito, save/load e validação de schema. | SRQ038 | testes de entrada inválida e round-trip. |
| Monitor silencioso | Score baixo apesar de mudança/degradação. | Investigação simulada perde indicador auxiliar. | Evolução por RUL e análise por unidade. | Comparar regiões retrospectivas; não converter silêncio em baixo risco. | SRQ035; SRQ036 | relatório de anomalia; ASM020 open. |
| Monitor excessivamente sensível | Scores altos em região saudável. | Falsos positivos analíticos e investigação excessiva simulada. | Percentil saudável e distribuição por região. | Referência 0,95 somente diagnóstica; sem threshold operacional. | SRQ035; SRQ036 | `healthy_region_high_scores` no relatório. |
| Monitor insensível | Score pouco muda perto do evento. | Pouca antecedência analítica. | Distribuição near-event e primeiras indicações. | Relatar limitações e não alegar cobertura. | SRQ035; SRQ036 | relatório de anomalia; ASM020 open. |
| Score inválido | Valor não finito ou escala incompatível é publicado. | Consumidor interpreta resultado incorreto. | Verificação de finitude e estado. | CDF persistida, `AnomalyPrediction` e testes. | SRQ035; SRQ038 | testes de orientação/finitude. |
| Monitor e modelo afetados pela mesma falha de dados | Ambos divergem/silenciam conjuntamente. | Concordância falsa e perda de defesa aparente. | Análise de dependências e revisão de mudança. | Classificar como diversidade analítica, não independência. | SRQ035; SRQ037 | monitoring_architecture.md; model_common_dependencies.md. |

## Extensão hazard discreto — 0.7.0

| failure_mode | local_effect | higher_level_effect_on_demonstrator | detection_means | current_controls | linked_requirements | evidence |
| --- | --- | --- | --- | --- | --- | --- |
| Hazard fora de [0,1] por falha numérica | Produto inválido. | Risco sem interpretação probabilística. | Finitude/limites após expit. | Falha explícita; não substituir por zero. | SRQ003; SRQ033; SRQ034 | test_bounds_and_horizon_coherence; test_invalid_input_explicit_status_and_forbidden_features |
| Sobrevivência crescente com k | Probabilidade de sobreviver aumenta ao estender janela. | Contradição temporal. | Diferenças de prefixos. | Produto dos mesmos fatores em [0,1]. | SRQ033 | test_bounds_and_horizon_coherence |
| Incoerência entre horizontes | Risco curto maior que longo. | Interpretação conjunta incorreta. | Pareamento OOF/validation. | Mesmo modelo e mesmo prefixo; sem ajustes separados. | SRQ033 | metrics.json: coherence |
| Registro landmark incorreto | Evento deslocado ou feature usa t+k. | Leakage ou desfecho incorreto. | Testes de evento inclusivo, prefixo e unidade. | Features congeladas; alvos em caminho separado; chaves únicas. | SRQ031; SRQ032 | test_landmark_event_step_and_no_unit_mixing; test_prefix_features_frozen_in_landmarks |
| Censura tratada incorretamente | Passo desconhecido vira negativo. | Subestimação e calibração distorcida. | Teste sintético de máscara/perda. | k>C−t excluído; sem censura fabricada no FD001. | SRQ032 | test_synthetic_censoring_masks_unknown_steps; ASM011 open |
| Otimizador sem convergência | Coeficientes incompletos. | Resultado não reproduzível/instável. | Status L-BFGS-B e finitude. | Ajuste interrompido; resumo registra convergência. | SRQ034 | training_summary no card; teste de falha de convergência |

Esta extensão mantém ausência de severidade regulatória e RPN; não encerra os
estados indesejados gerais. Controles numéricos não demonstram calibração.

Esta análise usa uma estrutura inspirada em FMEA para organizar falhas internas
do demonstrador. Não é FMEA de certificação, não atribui severidade regulatória
e não calcula RPN. Os efeitos se limitam ao demonstrador FD001 e à decisão
simulada de manutenção.

## Aplicação local integrada — 0.16.0

| failure_mode | local_effect | higher_level_effect_on_demonstrator | detection_means | current_controls | linked_requirements | evidence |
| --- | --- | --- | --- | --- | --- | --- |
| Probabilidade persistida inválida | Artefato contém NaN, infinito ou risco fora de [0,1]. | Resultado não satisfaz o contrato. | Guarda de probabilidade no consumidor. | `unavailable`, `input_validity=invalid` e reason code; nenhum fallback numérico. | SRQ003; SRQ006; SRQ007 | `test_invalid_persisted_risk_is_explicitly_unavailable`. |
| Modelo indisponível ou artefato incompatível | Componente não pode ser carregado para a origem. | Saída parcial ou ausente. | Validação de card, hash/schema e status por componente. | Fusão degradada somente quando a política permite; ausência explícita. | SRQ005; SRQ042; SRQ044; SRQ045 | testes de modelo ausente/incompatível e `audit_results.json`. |
| Configuração do consumidor divergente | Selector ou versão não corresponde ao artefato. | Resultado difícil de reproduzir. | Configuração TOML e model card são comparados no carregamento. | Listas permitidas em `configs/local_app.toml`; versão lida do card. | SRQ009; SRQ010; SRQ013 | testes de opções e `configuration_index.md`. |
| Endpoint retrospectivo usado no modo nominal | Cálculo de RUL acessa informação posterior sem ser solicitado. | Fronteira causal fica ambígua. | Teste nominal/retrospectivo e revisão de código. | RUL só é calculado com `retrospective=True`; aviso visual de avaliação. | SRQ001; SRQ002; SRQ091 | teste `test_retrospective_rul_is_explicitly_evaluation_only`. |
| Estado stale ou entrada inválida tratado como válido | Receptor mantém valor antigo sem propagar idade/validade. | Alerta pode atrasar ou ocultar indisponibilidade. | `telemetry_stale`, idade, validade e estado de saída. | Hold-last-value causal não marca hold como observação nova. | SRQ017; SRQ052; SRQ054; SRQ055 | testes de receptor, aplicação e simulações de falha. |

Esses modos permanecem internos ao demonstrador. A evidência é local e não
constitui assurance de sistema físico.

| failure_mode | local_effect | higher_level_effect_on_demonstrator | detection_means | current_controls | linked_requirements | evidence |
| --- | --- | --- | --- | --- | --- | --- |
| Entrada inválida aceita | Feature vector não finito ou com schema errado alcança o estimador. | Risco aparentemente disponível sobre informação inadequada. | Validação de schema, finitude e estado da saída. | Telemetria FD001 estrita; `predict_risk` devolve `unavailable/invalid` para registro inválido. | SRQ003; SRQ006; SRQ026 | `test_invalid_input_returns_explicit_unavailable_status`; testes de ingestão. |
| Feature ausente | Ordem ou conjunto de atributos difere do artefato. | Inferência falha ou associa valores à feature errada. | Comparação exata do schema e hash do preprocessor. | Schema persistido; ausência produz status explícito. | SRQ005; SRQ006; SRQ026 | Model cards; `causal_feature_engineer.json`; teste de entrada inválida. |
| Feature antiga | Histórico causal é válido, mas não representa o estado atual. | Risco atrasado e possível perda de antecedência. | Política futura de timestamps/idade; estado `stale`. | Contrato distingue `stale`; FD001 offline não contém timestamps. | SRQ017 | ASM004 permanece aberta; não há controle online nesta versão. |
| Erro de preprocessing | Janela atravessa motor, usa futuro, muda ordem ou imputador vê holdout. | Distorção comum a RF e XGBoost; métricas otimistas. | Invariância a sufixo, testes de fronteira por unidade e manifesto dos folds. | Janelas alinhadas à direita; estado reajustado dentro de cada fold; seleção/imputação somente no treino. | SRQ001; SRQ002; SRQ023; SRQ024 | `test_future_suffix_cannot_change_existing_features`; `test_windows_and_accumulation_never_cross_unit_id`. |
| Modelo indisponível ou artefato incompatível | Não há probabilidade computável. | Cobertura reduzida ou consumidor pode confundir ausência com baixo risco. | Falha explícita no load; `prediction_status` e explicação. | Schema de artefato, tipo do modelo e horizonte verificados; ausência nunca vira zero. | SRQ005; SRQ007; SRQ026 | Testes save/load e contrato de indisponibilidade. |
| `risk_score` fora de [0,1] | Saída não representa probabilidade válida. | Métricas e níveis simulados tornam-se incoerentes. | Validação no `RiskPrediction` e testes de limites. | `predict_proba`, clipping apenas contra erro numérico e registro comum. | SRQ003; SRQ026 | `test_scores_bounds_reproducibility_and_horizon_contract`. |
| Subestimação persistente de risco | Probabilidades abaixo da frequência observada perto do evento. | Alertas tardios ou eventos sem cobertura. | Curvas de confiabilidade, Brier, log loss, recall e análise por unidade. | Avaliação OOF e validation; nenhuma política operacional ativada. | SRQ011; SRQ015; SRQ030 | `metrics.json`; validation XGB tem diferença média -0,001141 em H15 e -0,007711 em H30. |
| Superestimação persistente de risco | Probabilidades acima da frequência observada. | Falsos alertas simulados e baixa precisão. | Curvas de confiabilidade, precisão e falsos positivos por unidade. | Pesos documentados; threshold somente exploratório. | SRQ003; SRQ012; SRQ030 | Métricas OOF mostram diferença média positiva nos quatro modelos/horizontes. |
| Calibração ruim | Ranking pode ser bom enquanto a probabilidade é numericamente inadequada. | Consumidor interpreta score como frequência sem suporte. | Brier, log loss, calibração média e reliability curve. | Reporte separado de discriminação/calibração; model cards dizem que não houve calibração adicional. | SRQ003; SRQ011; SRQ030 | `reports/classical_ml/metrics.json` e figura de confiabilidade. |
| Modelo correto com threshold inadequado | Probabilidade útil é convertida em classe por limiar sem relação com custos. | Excesso de omissões ou falsos alertas apesar do modelo. | Variação de precision/recall; futura análise de custo e antecedência. | Threshold 0,5 rotulado como exploratório; nenhuma política de alerta definida. | SRQ012; SRQ030 | Relatório compara precision/recall/F1 sem recomendar limiar. |
| Horizontes incoerentes | Modelo H15 produz risco maior que H30 na mesma observação. | Interpretação conjunta dos níveis temporais fica contraditória. | Verificação pareada por `(unit_id, cycle)` em validation. | Violações quantificadas e mantidas visíveis; nenhum pós-processamento silencioso. | SRQ004; SRQ029 | RF: 11/3.045; XGBoost: 38/3.045, com magnitudes máximas 0,006115 e 0,000331. |

Uma mesma causa pode produzir vários modos: erro de preprocessing pode causar
entrada semanticamente inválida, má calibração e subestimação persistente. Os
controles atuais fornecem detecção e contenção parcial; não encerram HAZ001–008
nem demonstram adequação a uma operação real.

## Modos adicionais da redução de telemetria (0.11.0)

| failure_mode | local_effect | higher_level_effect_on_demonstrator | detection_means | current_controls | linked_requirements | evidence |
| --- | --- | --- | --- | --- | --- | --- |
| Previsão filtrada calculada com telemetria completa | Join posterior recupera sensores omitidos ou usa feature artifact da fonte completa | Métrica otimista e fluxo causal falsificado | Auditoria de chaves, comparação de receiver values e teste de equivalência Full | `reconstruct_receiver_stream`; features receiver-aware; artifacts por política | SRQ061; SRQ062; SRQ064 | `development_results.json`; testes de reconstrução |
| HLV contado como amostra nova | Deltas, rolling ou slope avançam em ciclos sem pacote | Risco e staleness subestimados | Máscara `was_transmitted_this_cycle`, invariância a prefixo e teste de hold | `transform_receiver_frame` carrega estado derivado | SRQ062; SRQ063 | `tests/test_receiver_aware_features.py` |
| Sensor omitido recuperado por join | Feature ausente é preenchida silenciosamente com dataset original | Saída disponível sobre informação que não chegou ao receptor | Schema requerido versionado por artefato; status unavailable | `subset_train17` preserva schema; subset incompatível não é imputado | SRQ062; SRQ064; SRQ066 | Auditoria de compatibilidade por política |
| Artefato/preprocessador/calibrador incompatível | Feature names, escala ou horizonte não correspondem | Probabilidade inválida ou calibração deslocada | Hashes, load schema e freeze manifest | Namespace por cenário e modelos salvos por política | SRQ005; SRQ065; SRQ069 | `freeze_manifest.json` |
| Estado aprendido com unidade de avaliação | Threshold adaptativo ou imputador usa holdout | OOF e validation ficam otimistas | Auditoria de fitting/holdout units e manifest de folds | Quantis e ajuste dentro de cada fold | SRQ064; SRQ065 | fold manifests dos candidatos |
| Full não reproduz baseline | Nova rota altera score com todos os pacotes | Toda comparação de redução fica inválida | Tolerância estrita nos scores por chave/horizonte | Gate de equivalência antes da seleção | SRQ061 | XGB 0; hazard/fusão <3e-15 em validation |
| Stale/unavailable excluído do denominador | Ciclos difíceis desaparecem das métricas | Recall e calibração parecem melhores | Contagem sobre oportunidades e coverage explícita | Status preservado, scores ausentes, métricas com denominadores | SRQ066; SRQ067 | development metrics incluem status |
| Ausência de alerta convertida em atraso finito | Unidade sem alerta recebe latency/lead inventado | Falha antecipada é ocultada | Pareamento por unidade; `missed_anticipated_failures` | Latência nula e contador de falha sem alerta | SRQ067 | métricas por unidade |
| Staleness permissivo ou restritivo | Estado válido por tempo excessivo ou indisponível cedo demais | Mudança entre cobertura e atraso de alerta | Sensibilidade a `stale_after_cycles` e idade máxima | Limite versionado em config; sem interpolação futura | SRQ054; SRQ066; SRQ068 | grid fixa limite 3 |
| Grade/critério alterado após test_internal | Decisões são reotimizadas no holdout | Avaliação deixa de ser congelada | Gate one-shot, hash e recibo | Freeze antes da leitura; resultado não seleciona | SRQ068; SRQ069 | `test_evaluation_receipt.json` |

## Extensão TCN temporal — 0.12.0

| failure_mode | local_effect | higher_level_effect_on_demonstrator | detection_means | current_controls | linked_requirements | evidence |
| --- | --- | --- | --- | --- | --- | --- |
| Sequência curta tratada como completa | Padding domina a entrada | Risco inicial mal calibrado | Máscara e comprimento válido | Padding à esquerda e máscara | SRQ070; SRQ071 | `test_short_sequences_are_left_padded_and_masked` |
| Padding incorreto | Origem deslocada ou valor artificial ativo | Score responde ao padding | Teste de alinhamento | Zero padronizado somente à esquerda | SRQ071 | testes TCN |
| Máscara incorreta | Posições inválidas ficam ativas | Dependência do tamanho do padding | Máscaras adversariais | Máscara binária 0...1 validada | SRQ071; SRQ078 | `test_mask_rejects_nonbinary_or_right_padding_and_masks_left_values` |
| Checkpoint incompatível | Contrato e pesos divergem | Previsão inválida ou indisponível | Schema e round trip | `load` rejeita schema incompatível | SRQ074; SRQ078 | teste save/load/incompatibilidade |
| Não determinismo residual | Pesos podem variar por plataforma | Reprodutibilidade limitada | Reexecução com seed | Seeds e algoritmos determinísticos | SRQ075 | teste no mesmo ambiente; ASM040 |
| Saída inválida | NaN, infinito ou probabilidade fora de faixa | Alerta incorreto | Contrato numérico | Sigmoid, cabeça conjunta e status explícito | SRQ072; SRQ078 | testes de limites/entrada inválida |
| Latência excessiva | Inferência atrasa | Atualização pode chegar tarde | Timing e parâmetros | Rede de 3.570 parâmetros; medição local | SRQ076 | model card e relatório |
| Uso acidental de futuro | t+1 entra na sequência de t | Métrica otimista e contrato violado | Invariância de prefixo | Grupo por unidade, fatia até t e convolução causal | SRQ070 | testes de causalidade |
| TCN no stacking sem OOF | Meta-modelo recebe previsão in-sample | Fusão contaminada | Auditoria de componentes | OOF desativado e TCN fora da fusão | SRQ077 | config, model card e busca da fusão |

Esses modos organizam o demonstrador, sem severidade regulatória ou RPN. A
arquitetura neural fornece diversidade analítica e compartilha causas comuns.

## Extensão Transformer Encoder — 0.13.0

| failure_mode | local_effect | higher_level_effect_on_demonstrator | detection_means | current_controls | linked_requirements | evidence |
| --- | --- | --- | --- | --- | --- | --- |
| Máscara causal incorreta | Token consulta t+1 ou posterior | Métricas otimistas e contrato causal violado | Invariância de prefixo e inspeção triangular | Máscara superior booleana em toda camada | SRQ080 | `test_causal_mask_blocks_future_observations` |
| Representação posicional incorreta | Ordem temporal perdida ou posição deslocada | Risco responde à posição errada | Teste determinístico e dependente da posição | Codificação senoidal fixa versionada | SRQ081 | `test_positional_encoding_is_deterministic_and_position_dependent` |
| Sequência fora do tamanho esperado | Encoder recebe forma incompatível | Saída inválida ou indisponibilidade | Validação de shape/comprimento | Comprimento 30 fixo e rejeição explícita | SRQ081; SRQ087 | teste de comprimento e máscara |
| Latência excessiva | Atenção atrasa inferência | Atualização local pode perder cadência | Tempo por origem e razão contra TCN | Modelo pequeno e medição CPU | SRQ086 | metrics/model card 0.13.0 |
| Uso de memória excessivo | Atenção ou runtime excede recurso | Processo degrada ou fica indisponível | Parâmetros, checkpoint e estimativa analítica | 2 camadas, d=32, 4 heads e janela 30 | SRQ086 | model card; ASM045 |
| Checkpoint incompatível | Arquitetura, normalização ou pesos divergem | Previsão incorreta ou indisponível | Schema e round trip | `transformer-risk-model/v1` e load estrito | SRQ085; SRQ087 | teste save/load/incompatibilidade |
| Saída inválida | NaN, infinito ou score fora de [0,1] | Alerta incorreto | Validação do contrato | Cabeça sigmoid monotônica e status explícito | SRQ084; SRQ087 | testes de limites e entrada inválida |

O Transformer adiciona diversidade analítica, mas compartilha telemetria,
alvo, partições, features, runtime PyTorch e protocolo de avaliação. Não é
classificado como canal independente.
