# Etapa concluída — 0.16.0: encerramento local e assurance

1. Auditar causalidade, partições, OOF, calibração, thresholds, contratos,
   requirements, assumptions, FMEA, árvore lógica e dependências comuns.
2. Corrigir o consumidor local para não acessar endpoint retrospectivo no modo
   nominal e rejeitar probabilidades persistidas inválidas.
3. Criar índice de configuração, problem reports, assurance case, relatório
   final e auditoria executável.
4. Simular unidades completas e cenários controlados de entrada, telemetria,
   preprocessing, modelo, artefato e componente de fusão.
5. Executar regressão completa, `pip check`, limpar caches e atualizar changelog.

Estado: concluído. 165 testes e 226 subtests aprovados; auditoria sem checks
falhos. Nenhum modelo, dado bruto, partição ou threshold foi alterado.

# Etapa concluída — 0.15.0: aplicação local integrada

1. Criar serviço de aplicação independente de UI, consumindo somente dados de
   validation e artefatos científicos congelados.
2. Integrar seleção de unidade, horizonte, modelo, política de telemetria e
   cadência, com contratos explícitos `valid`, `degraded` e `unavailable`.
3. Montar trajetória por ciclo com risco, sobrevivência, health visual,
   componentes, anomalia, disagreement, alertas, explicações, idade e bytes.
4. Implementar CLI e Streamlit sobre o mesmo serviço, mantendo RUL/lead time
   atrás de modo retrospectivo explícito.
5. Expor comparações de modelos, políticas e Engineering assurance sem claim de
   certificação.
6. Testar entradas, artefatos, configuração, staleness e degradação; atualizar
   arquitetura, decisões, progresso, README e changelog.

Estado: concluído. Nenhuma nova modelagem, retreinamento, infraestrutura externa
ou auditoria final foi adicionada nesta etapa.

# Etapa concluída — 0.14.0: explicabilidade, calibração e incerteza empírica

1. Auditar os artefatos congelados de validation sem reajustar ou adicionar
   modelos e sem ler `test_internal` ou o teste oficial NASA.
2. Calcular Brier, curva de confiabilidade, ECE, intercepto e inclinação de
   calibração para os modelos probabilísticos H15/H30.
3. Gerar SHAP local do XGBoost, importância por coeficientes padronizados do
   hazard e ablação econômica por canal da TCN e do Transformer.
4. Produzir explicações integradas mantendo `anomaly_score`, `disagreement` e
   incerteza estatística com semânticas distintas.
5. Estimar intervalos percentis por bootstrap de `unit_id`, registrar réplicas
   não calculáveis e usar a política de alerta já congelada somente onde ela se
   aplica.
6. Validar a redação dos requisitos, verificar apenas os que têm evidência
   objetiva e atualizar requisitos, hipóteses, matriz, progresso e changelog.
7. Executar a aplicação, conferir os artefatos e rodar toda a suíte Python 3.11.

Estado: concluído. Foram auditados sete modelos em validation, geradas
explicações SHAP/ablação, 1.000 réplicas por horizonte e três relatórios de
assurance. Nenhum modelo novo, retreinamento, alteração de threshold ou uso de
conjuntos de teste ocorreu. A suíte terminou com 149 testes e 218 subtests.

# Etapa concluída — 0.10.0: filtragem local de telemetria

1. Substituir o contrato batch reservado por processamento primário sequencial.
2. Implementar Full, intervalo fixo, subset do treino e adaptive causal.
3. Implementar receptor HLV, idade/validade, staleness e cadência de inferência.
4. Registrar pacotes, bytes, frequência, tempo e episódios de alta frequência.
5. Aplicar análise de impacto; atualizar FMEA, árvore, requisitos e matriz.
6. Verificar com fixtures pequenas, sem experimento preditivo ou holdouts.

Estado: concluído. 103 testes aprovados; `test_internal` e teste oficial NASA
permaneceram fora do uso.

# Etapa concluída — 0.9.0: fusão probabilística e política inicial de alertas

1. Auditar previsões OOF, manifests, contratos e assurance; bloquear qualquer
   leitura de `test_internal` até o congelamento.
2. Gerar Weibull OOF por `unit_id`, reajustando beta e eta em cada fold, e
   alinhar as quatro probabilidades com o `anomaly_score` auxiliar.
3. Implementar ensemble aritmético apenas das probabilidades e stacking
   logístico por horizonte, com previsões cross-fitted do meta-modelo.
4. Comparar Platt e isotonic por cross-fitting agrupado; selecionar o
   calibrador no treino OOF e ajustar a versão final em scores cross-fitted.
5. Avaliar em validation, selecionar thresholds experimentais e persistência,
   verificar a rota de inferência congelada em validation e gravar o manifesto.
6. Executar uma única leitura/avaliação de `test_internal` após o congelamento,
   persistindo recibo e métricas por linha e unidade.
7. Atualizar FMEA, requisitos, hipóteses, rastreabilidade, dependências comuns,
   árvore lógica, relatório, README, progresso e changelog; executar os testes.

Estado: concluído. A configuração foi congelada antes de uma única avaliação em
`test_internal`; o teste oficial NASA permaneceu fora do escopo.

# Etapa concluída — 0.8.0: detecção analítica de anomalia

1. Ajustar Isolation Forest na região saudável experimental do treino, sem usar
   RUL como feature ou selecionar o limite em validation.
2. Gerar scores OOF por unidade e ajuste final aplicado a validation.
3. Analisar evolução, regiões retrospectivas, variação por unidade, indicações
   aparentes e falsos positivos com referência somente diagnóstica.
4. Persistir detector, feature engineer, referência saudável, cards e artefatos.
5. Documentar monitoramento, dependências comuns, FMEA, requisitos, hipóteses
   e rastreabilidade; verificar contrato, OOF e round-trip.

Resultado 0.8.0: concluído. Não há conversão para risco, fusão, threshold
operacional, teste interno, teste oficial, cloud ou hardware edge.

# Etapa anterior — 0.7.0: hazard discreto landmark

1. Revisar contratos, metodologia, assurance e resultados anteriores.
2. Implementar logit aditivo com features congeladas em t, idade e passo relativo.
3. Verificar evento inclusivo, censura sintética e equivalência da perda fatorada.
4. Reajustar preprocessing e modelo por fold agrupado; salvar OOF e ajuste final.
5. Avaliar validation, calibração por idade e coerência entre horizontes.
6. Atualizar card, relatório, FMEA, requisitos, hipóteses, matriz e changelog.
7. Executar toda a suíte; preservar partições e resultados anteriores.

Sem tuning, thresholds, calibração posterior, fusão ou acesso aos testes reservados.

# Etapa anterior — 0.6.0: atributos causais, Random Forest e XGBoost

1. Auditar integralmente documentação metodológica/assurance, relatórios EDA e
   Weibull, código, testes, partições e dependências antes de alterar o projeto.
2. Implementar atributos temporais causais configuráveis, seleção de constantes
   e imputação ajustadas exclusivamente no treino, com invariância a sufixos.
3. Produzir folds determinísticos por `unit_id`; em cada fold, reajustar todo o
   preprocessing e gerar previsões OOF para H=15 e H=30.
4. Ajustar Random Forest e XGBoost separados por horizonte, com pesos explícitos
   de classe e unidade; salvar modelos finais, previsões OOF e de validation.
5. Avaliar métricas globais e por unidade, threshold exploratório fixo em 0,5,
   importâncias XGBoost por gain e permutação exclusivamente OOF.
6. Criar model cards, relatório comparativo, análise dos modos de falha e das
   dependências compartilhadas; atualizar requisitos, hipóteses e matriz.
7. Atualizar documentação, versão e changelog; executar a pipeline real e toda
   a suíte, comprovando que `test_internal` e teste oficial não foram lidos.

Critério de conclusão: artefatos reproduzíveis para os dois horizontes, ausência
de leakage conhecido, rastreabilidade consistente e testes aprovados. Nenhum
threshold operacional, SHAP, tuning extenso, fusão ou uso de holdout nesta etapa.

Resultado 0.6.0: concluído. Foram geradas 58.256 previsões OOF e 12.180 de
validation com 324 features causais e quatro modelos finais. SRQ023–SRQ030,
ASM012–ASM015, FMEA interna e dependências comuns foram registradas. Os 37
artefatos protegidos permaneceram idênticos; 61 testes e `pip check` passaram.

---

# Etapa anterior — 0.5.0: baseline populacional Weibull de 2 parâmetros

1. Ler integralmente contrato, arquitetura, decisões, progresso, referências
   conceituais, requisitos, hipóteses, matriz e EDA; inspecionar código e testes.
2. Implementar Weibull 2P por máxima verossimilhança com uma duração por unidade,
   interface de risco por idade, funções de confiabilidade e persistência JSON.
3. Ajustar somente nos 70 motores de treino; estimar IC por bootstrap de unidades
   e aderência por bootstrap paramétrico com reajuste em cada réplica.
4. Avaliar H=15 e H=30 somente nas linhas operacionais de validation, incluindo
   métricas globais, por unidade, curvas de confiabilidade e sensibilidade.
5. Criar artefato, model card, figuras e relatório; atualizar hipóteses,
   decisões, rastreabilidade, README, progresso, versão e changelog.
6. Executar toda a suíte e conferir por hash que dados, partições, EDA e
   holdouts anteriores não foram modificados.

Resultado 0.5.0: concluído. Baseline Weibull 2P ajustado e avaliado em
validation operacional; forma paramétrica rejeitada e limitação registrada.
ICs e aderência usam 2.000 reamostragens, resultados H=15/30 e por unidade
foram salvos. 48 testes aprovados; nenhum holdout ou sensor utilizado.

---

# Etapa anterior — 0.4.0: contrato e assurance do demonstrador

1. Ler integralmente os seis documentos solicitados e inspecionar código,
   configurações e testes (concluído antes de qualquer alteração).
2. Auditar RUL, elegibilidade operacional, semântica da previsão e vazamento.
3. Corrigir contratos e criar verificações sem modelos nem novas features.
4. Documentar requisitos, hipóteses, estados indesejados, rastreabilidade e
   controle de mudanças; referências SAE exclusivamente conceituais.
5. Executar toda a suíte, conferir preservação dos artefatos existentes e
   registrar evidências. Não reexecutar ingestão ou EDA reais.

Resultado 0.4.0: concluído. Contrato auditado/corrigido; 18 requisitos, seis
hipóteses, oito estados indesejados e matriz criados. 38 testes aprovados;
21 artefatos anteriores preservados por SHA-256; nenhum modelo implementado.

---

# Plano de implementação — 0.1.0
# Etapa atual — 0.3.0: EDA e definição do problema

1. Ler arquitetura, decisões e progresso; inspecionar os Parquets existentes.
2. Definir desenvolvimento como treino + validação. Manter teste interno e
   teste oficial fora da leitura desta etapa; EDA e candidatos apenas no treino.
3. Criar alvos separados: RUL sem truncamento e eventos em horizontes
   experimentais configuráveis (30 e 15 ciclos), sem treino de modelos.
4. Gerar estatísticas e gráficos reproduzíveis com igual peso por motor nas
   curvas de vida normalizada. Registrar limitações e vazamento de informação.
5. Documentar objetivo probabilístico e níveis conceituais sem thresholds.
6. Validar alvos, isolamento dos dados, execução e figuras; atualizar changelog.

Resultado 0.3.0: concluído. EDA executada nos 70 motores de treino, oito
figuras produzidas e alvos gerados para treino/validação. Vinte e oito testes
aprovados; nenhum sensor removido ou modelo treinado.

---

## Escopo

Criar a fundação local em Python 3.11, começando pelo estudo de caso futuro
NASA C-MAPSS FD001. Nesta etapa não haverá dados ingeridos, modelos concretos,
API, dashboard, infraestrutura de cloud ou execução em edge.

## Inspeção antes de alterações

- Repositório inspecionado em 2026-09-07: apenas `.git`, sem commits ou arquivos.
- Nenhum changelog preexistente; criar `CHANGELOG.md` para a versão 0.1.0.
- Python padrão encontrado: 3.13.9; localizar um runtime 3.11 para validação.

## Etapas

1. Criar empacotamento `src`, configuração Python 3.11 e diretórios solicitados.
2. Definir registros comuns e contratos abstratos independentes para ingestão,
   atributos, risco, anomalia, fusão, filtragem e avaliação.
3. Documentar responsabilidades, fluxo, decisões e limites desta entrega.
4. Verificar importações, contratos, saída padronizada e empacotamento local.
5. Registrar resultados em `docs/progress.md` e atualizar changelog.
6. Encerrar; aguardar autorização futura para ingestão ou modelos concretos.

## Resultado

Etapas 1 a 5 concluídas. Instalação editável e seis testes passaram em Python
3.11.16; `pip check` não encontrou conflitos. Evidências e inventário completo
registrados em `docs/progress.md`. Etapa 6: entrega encerrada neste escopo.

---

# Plano de implementação — 0.2.0

## Escopo

Implementar exclusivamente a ingestão, validação, divisão por unidades e
persistência local em Parquet do NASA C-MAPSS FD001. Não criar dados, modelos,
atributos avançados, análise exploratória, dashboard ou infraestrutura.

## Inspeção antes de alterações

- `docs/architecture.md`, `docs/decisions.md` e `docs/progress.md` lidos por
  completo em 2026-09-07.
- Código, configuração, testes, documentação, changelog e estado do Git
  inspecionados.
- `data/raw` contém somente `.gitkeep`; os arquivos oficiais estão ausentes.

## Etapas

1. Declarar esquema FD001 e configuração reprodutível da divisão interna.
2. Implementar carregador estrito e validações estruturais e temporais.
3. Separar unidades inteiras em treino, validação e teste interno.
4. Persistir Parquet, manifesto e relatório apenas quando o treino oficial
   estiver disponível e válido.
5. Criar testes com fixtures mínimas geradas temporariamente.
6. Atualizar README, arquitetura, decisões, progresso e changelog.
7. Executar todos os testes no Python 3.11 e encerrar esta etapa.

## Resultado

Etapas 1 a 7 concluídas. Os arquivos oficiais estavam ausentes e não foram
substituídos. Vinte testes passaram em Python 3.11.16, incluindo validações,
isolamento por unidade e round-trip Parquet em diretório temporário.

---

# Etapa 0.12.0 — TCN temporal causal

1. Revisar o patch fora do repositório e preservar alterações posteriores.
2. Auditar sequências, convolução, máscara, alvos e cabeça conjunta contra o
   contrato causal e probabilístico.
3. Fortalecer testes antes do treinamento real.
4. Selecionar época apenas dentro do treino e reajustar um modelo limpo nas 70
   unidades; avaliar somente nas 15 unidades de validation.
5. Regenerar checkpoint, Parquets, métricas, model card, relatório e hashes no
   Python 3.11 do projeto.
6. Atualizar FMEA, dependências, requisitos, hipóteses e rastreabilidade sem
   modificar fusão, thresholds, dados ou artefatos históricos.

Resultado: concluído. Época 3, CPU, 3.570 parâmetros e zero violações H15>H30.
Os resultados oficiais estão em `reports/tcn`; a TCN permanece fora da fusão.

---

# Etapa 0.13.0 — Transformer Encoder causal pequeno

1. Reutilizar unidades, features, alvos H15/H30, janela e protocolo de early
   stopping da TCN.
2. Implementar dataset temporal, posição senoidal, atenção causal, padding,
   cabeça monotônica, checkpoint e estados de erro.
3. Testar invariância a futuro, posição, limites, isolamento, save/load e
   reprodutibilidade antes do treinamento real.
4. Ajustar somente no treino, avaliar em validation e comparar XGBoost, hazard,
   TCN e Transformer sem retreinar os três primeiros.
5. Registrar desempenho, alertas, tempo, parâmetros, checkpoint e estimativa
   analítica de memória; atualizar assurance e changelog.

Resultado: concluído. Época 7, 17.762 parâmetros e melhor desempenho
probabilístico em validation, com maior custo que TCN/XGBoost. Sem OOF, fusão
ou uso de conjuntos de teste.
