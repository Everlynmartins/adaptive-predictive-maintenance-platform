# Changelog

## [0.16.0] - 2026-09-16

- 2026-09-17 — Portfolio publication preparation: English project landing page,
  case study, reviewed screenshot gallery and publication checklist. Excluded
  original imports, PDFs, local credentials, logs and Terraform state/inputs
  from publication. Scientific code, configurations, metrics, artifacts and
  deployed infrastructure remain unchanged. Dataset files remain local; the
  public README documents the demo prerequisites instead of implying that a
  fresh clone includes NASA telemetry. No new scientific execution or AWS call.

- 2026-09-17 — Prompt 23I: **Stage 3 AWS: VALIDATED — LAB**. Registrados os
  PASS reais fornecidos pelo operador: E2E cloud 40 ciclos/40 predictions/3
  alerts, persistência RDS, recovery ECS com 40/3 preservados após nova task e
  histórico confirmado visualmente no dashboard cloud. Criado relatório final
  com matriz de integração/evidência/status, achados e limites do demonstrador.
  Corrigidos somente login nativo do verificador ECR, prioridade de região no
  aws_check, exclusões de state/plan/tfvars/.env do contexto Docker e documentação
  desatualizada. 84 testes focados passaram (2 warnings, 38,82 s) no Python
  3.11.16; parser Windows PowerShell 5.1 aprovou 12 scripts. Hashes de 25 arquivos
  protegidos permaneceram iguais. Sem chamadas AWS reais, alteração de
  Terraform aplicado/recursos, ciência, thresholds, contratos ou artefatos.

- Prompt 23H: preparado teste local controlado de recuperacao ECS, interrompendo
  somente a task atual e mantendo desired count 1. Espera limitada por nova task
  HEALTHY, redescoberta de endpoint e comparacao dos registros anteriores pela
  API cloud, sem replay ou nova prediction. Execucao real pendente no Windows;
  parser PowerShell 5.1 aprovado e 34 testes focados de scripts com mocks
  passaram. Nenhuma chamada AWS real executada no Codex; Stage 3 nao declarada
  finalizada.

- Corrigido falso negativo do validator E2E Stage 3: alertas identificados por
  unidade/ciclo/horizonte e risco numerico com tolerancia, sem chave localizada
  alert_level ou campos ausentes no schema. Leitura historica com tres tentativas
  limitadas; registros realmente ausentes continuam causando FAIL. Sem chamadas
  AWS reais ou alteracoes de API, infraestrutura e ciencia. Parser PowerShell
  5.1 aprovado e 18 testes com mocks passaram, incluindo mojibake e retries.

- 2026-09-17: preparados scripts locais de replay Stage 3 cloud (endpoint
  descoberto por ECS/ENI, simulador existente, health/opcoes e recuperacao
  persistida pela API) e consulta limitada de logs CloudWatch com redacao de
  credenciais conhecidas. Respeitados idempotencia e filtros historicos reais;
  sem fallback local, acesso SQL publico ou mudancas de infraestrutura/ciencia.
  Parser Windows PowerShell 5.1 e 12 testes focados com mocks aprovados.
  Execucao E2E real permanece responsabilidade do operador Windows.

- 2026-09-17: preparada task ECS Fargate LAB com API e Streamlit na mesma imagem
  ECR stage3-lab-v1, service com desired_count=0, 1 vCPU/4 GiB configuráveis,
  health checks e dois log groups com retenção de sete dias. Reutilizados rede,
  roles e RDS privados; permissão GetSecretValue limitada ao ARN gerenciado.
  Bootstrap de infraestrutura monta conexão em memória com escaping e TLS
  verify-full, sem rebuild ou mudanças científicas. Adicionados scripts de
  endpoint/check somente leitura e controle LAB via plan Terraform restrito
  a desired_count. Execução AWS e validação integrada cloud permanecem locais
  ao operador; nenhuma chamada AWS mutável executada pelo Codex. Terraform
  fmt/validate, parser Windows PowerShell 5.1 e 18 testes focados com mocks
  aprovados, incluindo start/stop restritos e stderr sem falha falsa.

- 2026-09-17: preparado RDS PostgreSQL LAB privado Single-AZ (16.13 configurável,
  db.t4g.micro, 20 GiB gp3), senha master gerenciada pelo RDS/Secrets Manager,
  backup de um dia e exclusão descartável sem snapshot final. Rede/IAM existentes
  preservados; cinco outputs não sensíveis e aws_rds_check.ps1 somente leitura.
  Terraform fmt/validate e parser PowerShell aprovados; sem chamadas AWS mutáveis
  ou alteração da ciência/imagem ECR neste host.
- Stage 3 LAB: adicionado um repositório ECR privado para a única imagem
  compartilhada por API e Streamlit, scan on push, tags versionadas imutáveis,
  exceção mutável para `latest` e retenção de dez manifests. Adicionados scripts
  PowerShell para publicar e verificar imagem via perfil AWS local; sem push,
  apply, destroy ou chamadas AWS mutáveis neste host.
- Networking/segurança Terraform LAB da Stage 3: VPC, uma subnet pública,
  duas privadas, rotas, subnet group RDS, Security Groups restritos e roles
  ECS separadas. Preparado acesso opcional a ARN específico de secret futuro,
  sem senha no state, NAT, ALB, banco ou serviços ECS criados nesta etapa.
  Código preparado sem apply nem criação de recursos AWS reais.
  Revisão estática realizada; fmt/validate pendentes no Windows local porque
  Terraform não está disponível no host Codex.
- Adicionada fundação Terraform da Stage 3 AWS com provider, versões, tags,
  state local ignorado, exemplo não sensível e scripts PowerShell de checagem
  AWS/planejamento. Não há recursos Terraform, apply, destroy ou credenciais.
- Planejamento Stage 3 AWS, sem infraestrutura implementada: LAB com uma task
  ECS Fargate API/dashboard e RDS privado Single-AZ; PORTFOLIO opcional com ALB/HTTPS.
  Criados planos de arquitetura, custos e ciclo de vida; sem recursos AWS reais
  ou alterações científicas.
- Fechamento Stage 2 VALIDATED: consolidados PASS Windows 22A (40 ciclos,
  40 predictions, 3 alerts), 22B (API/DB, retenção após restart e zero duplicações)
  e 22C (dashboard API sem fallback), mais implementação/testes do histórico 22E.
  Regressão focada: 30 testes aprovados em 23,66 s, dois warnings externos;
  parser PowerShell e seis comandos local_stack com Docker simulado aprovados.
  Arquitetura, relatório e README atualizados; Stage 3 não implementada.
- Dashboard em modo API agora mostra histórico operacional persistido por meio
  de `/api/v1/predictions` e `/api/v1/alerts`, sem acesso direto ao PostgreSQL
  nem reconstrução local de previsões.
- Auditoria final de integração da Etapa 2: 28 testes locais aprovados e
  controle PowerShell validado com Docker simulado. Corrigida a raiz e as
  chamadas Compose do local_stack.ps1. Naquela auditoria, Stage 2 pending por
  retenção após restart ainda sem evidência e dashboard sem histórico;
  ambas as pendências foram posteriormente resolvidas no fechamento acima.
- Adicionado script PowerShell de validação somente leitura da persistência da
  Etapa 2, incluindo comparação API/PostgreSQL e sobrevivência a restart normal.
- Adicionado script PowerShell de preparação do replay ponta a ponta da Etapa 2,
  que valida Compose, health, opções expostas, simulador e persistência sem
  alterar artefatos científicos ou encerrar containers.
- Corrigida a resolução do `project_root` da API com
  `PREDICTIVE_MAINTENANCE_PROJECT_ROOT`, incluindo `/app` no Compose e
  descoberta segura no checkout local.
- Auditada a integração da Etapa 2 entre simulador, FastAPI, serviço local,
  persistência e dashboard; um fluxo curto de três ciclos confirmou ordem,
  persistência de previsões/alertas e contratos de status.
- Adicionado adaptador HTTP do Streamlit para a FastAPI, sem fallback
  silencioso nem duplicação da lógica científica do `LocalApplicationService`.
- O endpoint de saúde agora verifica o banco quando `DATABASE_URL` está ativa;
  o simulador permite delimitar `start_cycle` e `max_cycles` para smoke tests.
- Criados arquitetura e relatório de validação da Etapa 2. O build e o smoke
  do Compose permanecem não executados porque Docker não está disponível no host.
- Adicionada API REST local FastAPI que reutiliza `LocalApplicationService` para
  opções, predição por ciclo e trajetórias de unidades, sem carregar modelos
  diretamente nos endpoints ou alterar artefatos científicos.
- Adicionado simulador local de telemetria ciclo a ciclo via HTTP, com modos
  `real_time_simulated` e `fast`, velocidade configurável e interrupção limpa.
- Adicionada persistência opcional via `DATABASE_URL` para eventos simulados,
  previsões e alertas, com PostgreSQL como alvo e SQLite em memória para testes.
- Adicionada conteinerização local com uma imagem Python 3.11 compartilhada por
  API, dashboard e simulador opcional, além de PostgreSQL com volume persistente.
- Encerramento da fase local com auditoria estrutural executável, simulação de
  três unidades até o evento e verificação de leakage, partições, OOF, cards,
  estados e artefatos temporários.
- Criados índice de configuração, problem reports, assurance case e relatório
  final de assurance; requisitos, hipóteses, FMEA, árvore lógica e dependências
  foram alinhados às evidências reais.
- Corrigido acesso retrospectivo desnecessário no caminho nominal da aplicação,
  validação de riscos persistidos inválidos e seletores/versionamento hardcoded.
- Nenhum modelo foi adicionado ou reajustado; dados brutos, partições e
  artefatos históricos foram preservados.
- Os 17 diretórios de cache temporário foram removidos após validação dos alvos
  dentro do workspace; a suíte final foi executada sem bytecode/cache do pytest.
- Verificação final: 165 testes e 226 subtests aprovados em 47,46 s, três
  warnings internos do SHAP, `pip check` aprovado e auditoria sem falhas.

## [0.15.0] - 2026-09-15

- Aplicação local integrada com Streamlit e CLI, ambas consumindo o mesmo
  `LocalApplicationService` e sem lógica científica duplicada na interface.
- Seleção de `unit_id`, H15/H30, modelo, política de telemetria e cadência;
  reprodução somente leitura dos artefatos congelados de `validation`.
- Visualização por ciclo de riscos, sobrevivência, health visual, alerta,
  anomalia, disagreement, status, validade, staleness, idade, reason codes e
  custos de telemetria.
- Estados `valid`, `degraded` e `unavailable` sem substituição silenciosa de
  erro. RUL e lead time reais aparecem somente no modo retrospectivo.
- Seção Engineering assurance apresenta manifesto, versões, requisitos,
  hipóteses e limitações sem claim de segurança ou certificação.
- Streamlit incluído nas dependências Python 3.11; testes cobrem entradas e
  configurações inválidas, staleness, ausência/incompatibilidade de modelo e
  contratos de status.
- Verificação final: 160 testes e 223 subtests aprovados em 34,16 s; três
  warnings internos do SHAP registrados, `pip check` aprovado, CLI e servidor
  Streamlit validados no ambiente local.

## [0.14.0] - 2026-09-15

- Auditoria de calibração em validation para Weibull, Random Forest, XGBoost,
  hazard discreto, TCN, Transformer e fusão, com Brier, reliability curves,
  ECE, intercepto e inclinação de calibração.
- TreeSHAP local do XGBoost para todas as origens H15/H30, com direção,
  magnitude relativa, agregação por sensor e reprodução exata dos scores
  congelados. Nenhuma interpretação física ou causal foi adicionada.
- Coeficientes padronizados do hazard e ablação econômica por canal da TCN e
  do Transformer registram sensibilidade global, sem criar novos modelos.
- Intervalos percentis com 1.000 reamostragens de unidades completas, incluindo
  contagem explícita de réplicas não calculáveis e métricas da política de
  alerta congelada.
- Estrutura integrada de explicação preserva `anomaly_score` como indicador e
  `disagreement` como divergência, separados das probabilidades e dos intervalos.
- Criados relatórios distintos de validação e verificação dos 95 requisitos;
  SRQ090–SRQ095 e ASM048–ASM052 foram adicionados à rastreabilidade.
- Nenhum modelo foi reajustado, nenhum threshold foi alterado e `test_internal`
  e o teste oficial NASA não foram lidos.
- Verificação final: 149 testes e 218 subtests aprovados em 54,47 s; três
  warnings de depreciação internos do SHAP foram registrados e `pip check`
  não encontrou dependências quebradas.

## [0.13.0] - 2026-09-15

- Transformer Encoder temporal pequeno em PyTorch: janela 30, d=32, quatro
  heads, duas camadas, posição senoidal, máscaras causal/padding e cabeça
  monotônica H15/H30.
- Early stopping agrupado exclusivamente no treino selecionou época 7; modelo
  limpo ajustado nas 70 unidades e avaliado nas 15 unidades de validation.
- H15: Brier 0,007844, log loss 0,027611, ROC AUC 0,998966 e PR AUC 0,987997.
  H30: Brier 0,017680, log loss 0,059983, ROC AUC 0,997069 e PR AUC 0,983398.
- Registrados 17.762 parâmetros, timings CPU, checkpoint e memória analítica.
  O Transformer permanece fora da fusão e não usa holdouts de teste.
- FMEA, dependências comuns, HAZ013, SRQ080–089, ASM042–047 e matriz de
  rastreabilidade atualizados.
- Verificação final: 142 testes e 212 subtests aprovados em 27,08 s, sem
  warnings; `pip check` aprovado e 89 requisitos alinhados à matriz.

## [0.12.0] - 2026-09-15

- TCN pequena em PyTorch com sequências causais por unidade, padding somente à
  esquerda, máscara explícita e cabeça probabilística conjunta para H15/H30.
- Early stopping restrito a um subconjunto agrupado das unidades de treino; o
  modelo final é recriado e ajustado nas 70 unidades pelo número de épocas
  selecionado, sem utilizar validation no ajuste.
- Testes TCN fortalecidos para causalidade da convolução e das sequências,
  fronteira entre motores, padding/máscara, features proibidas, coerência dos
  horizontes, checkpoint e disjunção do early stopping.
- PyTorch adicionado às dependências. A execução oficial usa Python 3.11 e
  Parquet; os CSV e resultados preliminares do patch não são artefatos finais.
- A TCN permanece fora da fusão. Uma inclusão futura exige previsões OOF
  agrupadas por `unit_id`.
- Execução oficial em Python 3.11.16/CPU selecionou época 3, treinou 3.570
  parâmetros e gerou Parquet. H15: Brier 0,034437 e PR AUC 0,931467; H30:
  Brier 0,039308 e PR AUC 0,929680; zero violações entre horizontes.
- Regressão final: 131 testes e 194 subtests aprovados em 25,88 s, sem warnings;
  `pip check` aprovado e 204/204 artefatos históricos preservados por SHA-256.

## [0.11.0] - 2026-09-15

- Experimento causal de redução de telemetria no FD001 com Full, intervalos
  fixos, subset selecionado no treino e Adaptive por mudança relativa.
- Features receiver-aware não contam hold-last-value como nova amostra; Full foi
  comparada aos artefatos anteriores antes da seleção.
- Validation inclui XGBoost, hazard discreto e fusão, métricas probabilísticas e
  de alerta, bytes, staleness, idade e estados valid/degraded/unavailable.
- Retraining pareado selecionado por folds de `unit_id`, com OOF, calibração,
  manifestos, critérios experimentais e gate one-shot para `test_internal`.
- A fase declara a exposição histórica do `test_internal`; o teste oficial NASA
  permanece fora do uso. Nenhum percentual de redução é declarado universalmente
  seguro ou como objetivo regulatório.

## [0.10.0] - 2026-09-14

- Interface sequencial de filtragem com Full, intervalo fixo, subset do treino
  e adaptive causal por mudança absoluta/relativa, média móvel, variação e
  anomaly score auxiliar.
- Receptor hold-last-value com idade, ciclo de origem, validade, staleness e
  cadência de inferência configurável; valor mantido não vira observação nova.
- Pacotes e métricas de bytes/frequência/tempo, além de ativações, motivos e
  duração do modo alto para adaptive.
- Análise de impacto, FMEA, árvore lógica, SRQ052–SRQ060 e ASM027–ASM029.
- Nenhuma comparação preditiva, leitura de `test_internal` ou uso do teste
  oficial NASA nesta etapa.
- 103 testes aprovados em Python 3.11; `pip check` sem conflitos.

## [0.9.0] - 2026-09-14

- Fusão probabilística com média simples das quatro probabilidades e stacking
  logístico por horizonte, treinado somente em previsões OOF.
- Weibull OOF reajustada por fold de `unit_id`; `anomaly_score` preservado como
  covariável analítica separada e excluído da média probabilística.
- Calibração Platt/isotonic avaliada por cross-fitting agrupado, política
  experimental de quatro níveis selecionada apenas em validation e gate para
  uma única avaliação congelada em `test_internal`.
- Status `valid`, `degraded` e `unavailable`, disagreement entre probabilidades,
  métricas temporais por unidade e rastreabilidade da fusão adicionados.

### Resultados

- Validation stacking: H15 Brier 0,012694, log loss 0,043651, PR AUC 0,973083
  e F1 0,896247; H30 0,025415, 0,097943, 0,960961 e 0,909910.
- Avaliação congelada única em `test_internal`: H15 Brier 0,010178, log loss
  0,033190, PR AUC 0,979309 e F1 0,883534; H30 0,013538, 0,049782, 0,989777
  e 0,925342. O recibo registra uma leitura e nenhum reajuste posterior.
- Thresholds validation: atenção 0,006568, alerta 0,158112 e crítico 0,201375,
  com persistência de três ciclos. Dependências comuns, árvore lógica, FMEA,
  requisitos SRQ039–SRQ051 e hipóteses ASM022–ASM026 foram registrados.
- 92 testes aprovados em Python 3.11; dependências sem conflitos no `pip check`.
- O teste oficial NASA permaneceu fora do uso.

## [0.8.0] - 2026-09-14

- Isolation Forest treinado em região saudável experimental do treino, com
  scores OOF por unidade e aplicação final em validation.
- `anomaly_score` passou a ter contrato de disponibilidade explícito e escala
  documentada: CDF empírica saudável de `-score_samples`; não é `risk_score`.
- Arquitetura de monitoramento, model card, FMEA, requisitos SRQ035–SRQ038 e
  hipóteses ASM019–ASM021 adicionados.
- Monitor classificado como diversidade analítica, sem independência de safety,
  devido a dados, sensores, preprocessing, runtime e avaliação compartilhados.

## [0.7.0] - 2026-09-13

- Hazard discreto logístico L2 com features congeladas na origem e máscara de censura.
- Perda fatorada equivalente à expansão, evitando replicar a matriz de features.
- H=15/30 coerentes, OOF por unidade, modelos, card e calibração por idade.
- SRQ031–SRQ034, ASM016–ASM018, FMEA e rastreabilidade do hazard.
- SciPy, joblib e threadpoolctl declarados como dependências diretas.
- Bloqueio de nomes retrospectivos também antes de gerar sufixos de features;
  schema real anterior não foi afetado e os baselines foram preservados.
- Resultados e verificação da execução em docs/progress.md.

## [0.6.0] - 2026-09-12

### Adicionado

- 324 features causais: idade, valor atual, delta, diferença relativa,
  variação absoluta acumulada e estatísticas/inclinação em janelas 5/10/20.
- Seleção de constantes e imputação ajustadas somente no treino, inclusive
  dentro de cinco folds OOF disjuntos por `unit_id`.
- Random Forest e XGBoost separados para H=15/30, com ponderação explícita por
  unidade e classe, contrato comum, status inválido e save/load.
- Artefatos separados de previsões OOF, validation, quatro modelos finais,
  métricas por unidade, folds, feature manifest e model cards.
- Gain e permutation importance OOF do XGBoost, comparação com Weibull e curvas
  de confiabilidade; threshold 0,5 somente exploratório.
- FMEA interna da função preditiva, análise de dependências compartilhadas,
  requisitos SRQ023–SRQ030 e hipóteses ASM012–ASM015.

### Corrigido

- Detecção de colunas constantes agora combina valor único e variância. A
  primeira execução reteve três constantes devido a resíduos de ponto flutuante;
  os artefatos foram regenerados com as sete constantes corretamente removidas.

### Resultados

- Validation H=15: RF Brier 0,013750/PR AUC 0,955479/F1 0,861607; XGBoost
  0,010510/0,975207/0,907080.
- Validation H=30: RF Brier 0,026506/PR AUC 0,954507/F1 0,881395; XGBoost
  0,022978/0,969911/0,893226.
- Coerência p15≤p30: 11 violações RF e 38 XGBoost em 3.045 chaves, registradas
  sem correção silenciosa. Dados, partições, EDA e Weibull foram preservados.
- 61 testes aprovados em Python 3.11.16; `pip check` sem conflitos. Os 37
  arquivos protegidos de dados e resultados anteriores conservaram SHA-256.

Não inclui tuning extenso, calibração posterior, SHAP, fusão, threshold
operacional ou uso de test_internal/teste oficial.

## [0.5.0] - 2026-09-07

### Adicionado

- Baseline populacional Weibull de dois parâmetros por idade, com MLE de beta
  e eta, densidade, CDF, sobrevivência, hazard, hazard acumulado e risco por H.
- Likelihood preparada para censura à direita futura; execução FD001 com 70
  tempos de vida de unidades e 70 eventos, sem censura fabricada.
- ICs 95% por 2.000 bootstraps de unidades; Cramér–von Mises por 2.000
  bootstraps paramétricos com reajuste e resolução de ciclos reproduzida.
- Avaliação operacional de validation em H=15/30: Brier, ROC AUC, PR AUC/AP,
  log loss, calibração, reliability curves e resultados por unidade.
- Save/load JSON estrito, model card, SHA-256, previsões Parquet, métricas,
  análise de sensibilidade, cinco figuras e relatório Weibull.
- Requisitos SRQ019–SRQ022 e hipóteses estatísticas ASM007–ASM011.

### Resultados

- beta=4,428466; eta=227,987974 ciclos. ICs bootstrap: beta
  [3,860107; 5,670466] e eta [215,252370; 241,177970].
- Aderência rejeitada: W²=0,345778, crítico 5%=0,122799 e p=0,000500.
- Validation H=15: Brier 0,060652; ROC AUC 0,876394; PR AUC/AP 0,309878;
  log loss 0,197435. H=30: 0,098197; 0,882405; 0,484177; 0,293576.
- 48 testes aprovados e dependências íntegras. Dados, partições e relatórios
  anteriores preservados; sensores, test_internal e teste oficial não lidos.

Não inclui Weibull 3P, Crow-AMSAA, ML ou threshold operacional. A Weibull é
baseline estatístico age-only, não modelo físico automático da degradação.

## [0.4.0] - 2026-09-07

### Adicionado

- Contrato matemático do risco condicionado à sobrevivência, requisitos
  SRQ001–SRQ018, hipóteses, registro de estados indesejados e matriz rastreável.
- Escopo conceitual SAE ARP4754B/ARP4761A, sem conformidade, análises formais
  ou classificações regulatórias; template de impacto de mudanças.
- Seleção de alvos operacionais com horizontes explícitos, sem escrita de dados.
- Bloqueio de nomes retrospectivos em FeatureRecord e proteção de seu mapeamento.
- Testes de escores/estados, causalidade nominal, alvos e referências da matriz.

### Corrigido / migração de contrato

- RiskPrediction exige horizon, prediction_status e input_validity; construção
  por argumentos nomeados. RiskModel.predict_risk exige horizon nomeado.
- Risco disponível representa probabilidade em [0,1]; ausência é None com causa.
- Survival_score = 1 - risk_score; health_score mantém o nome e passa a
  100 * survival_score. Valores antigos independentes em [0,1] não são aceitos.
- RUL explicita max(T_i - t, 0), sem alterar resultados completos válidos.
- Fusão e avaliação declaram alinhamento por horizonte e tratamento de ausência.

Dados brutos, partições, alvos e relatórios anteriores preservados. Nenhum modelo,
threshold, ingestão ou EDA real executado nesta etapa. Teste oficial não utilizado.

## [0.3.0] - 2026-09-07

### Adicionado

- EDA reproduzível somente no treino: estatísticas, correlações, trajetórias,
  candidatos a sensores e oito figuras.
- RUL sem truncamento e alvos em horizontes configuráveis de 30 e 15 ciclos,
  em tabelas de avaliação separadas para treino e validação.
- Definição do risco probabilístico e níveis conceituais sem thresholds.
- Relatório EDA, sumário e metadados com hashes, configuração e versões.
- Testes de fronteiras, censura, conservação de chaves e isolamento dos dados.

### Alterado

- Versão 0.3.0; NumPy e Matplotlib declarados para EDA local.
- Documentação de arquitetura, decisões, progresso e reprodução atualizada.

Nenhum sensor removido ou modelo treinado. Testes interno e oficial não são
lidos pela EDA; a validação é usada somente para chaves e alvos.

## [0.2.0] - 2026-09-07

### Adicionado

- Carregador reutilizável e esquema explícito das 26 colunas do C-MAPSS FD001.
- Validação agregada de estrutura, valores, identificadores, duplicidades e
  sequência temporal por unidade.
- Divisão reprodutível em treino, validação e teste interno exclusivamente por
  `unit_id`, configurada em `configs/fd001.toml`.
- Preparação local com Parquet, manifesto de unidades e relatório JSON quando
  o arquivo oficial de treino estiver disponível.
- Testes automatizados de ingestão, validação, isolamento de unidades,
  persistência e preservação do conjunto oficial de teste.

### Alterado

- Versão do projeto atualizada para 0.2.0.
- Dependências locais adicionadas para dados tabulares e Parquet: pandas e
  pyarrow.
- Documentação atualizada para o fluxo FD001 e a ausência atual dos arquivos
  oficiais em `data/raw`.

### Validado

- Pipeline executada com os três arquivos oficiais presentes em `data/raw`.
- Treino com 100 motores e 20.631 ciclos aprovado nas verificações estruturais
  e temporais.
- Divisão interna 70/15/15 sem sobreposição de unidades e três Parquets
  verificados por leitura e reconstrução do treino original.
- Teste oficial e RUL validados separadamente e mantidos fora das partições
  internas.
- Relatório de dados atualizado com estatísticas reais e colunas constantes.

Esta versão não inclui modelos, atributos avançados, análise exploratória,
dashboard, infraestrutura de cloud ou hardware edge.

## [0.1.0] - 2026-09-07

### Adicionado

- Fundação local Python 3.11 com layout `src` e metadados de empacotamento.
- Diretórios de dados, configuração, modelos, notebooks, relatórios e documentação.
- Sete contratos internos: ingestão, atributos, risco, anomalia, fusão, filtragem e avaliação.
- Registros comuns de telemetria, atributos, alvos, risco e anomalia.
- Saída de risco padronizada, campos opcionais e validação dos escores em [0, 1].
- Testes mínimos de importação, contratos, registros e versão do projeto.
- Documentação de arquitetura, decisões, progresso e preparação do ambiente.

Esta versão contém somente a estrutura e os contratos. Não inclui ingestão,
modelos concretos, API, dashboard, edge ou infraestrutura de cloud.
