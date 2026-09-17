# Progresso do projeto

## Versão 0.16.0 — encerramento da fase local e assurance

Data: 2026-09-16.

- Auditoria estrutural de requisitos, matriz, hipóteses, modelos, OOF, leakage,
  partições, dependências, caches e notebooks.
- Corrigido acesso nominal desnecessário ao endpoint retrospectivo, validação de
  risco persistido e seleção/versionamento hardcoded da aplicação.
- Criados `configuration_index.md`, `problem_reports.md`, `assurance_case.md` e
  `final_assurance_report.md`; FMEA, árvore, hazard log, escopo e dependências
  foram alinhados às evidências reais.
- Criada auditoria executável e simulação de três unidades até a fronteira do
  evento. Dados brutos e partições foram preservados; teste oficial não foi lido.
- A ausência de commit Git e o pacote histórico `predmain.zip` permanecem
  explicitamente controlados. Os 17 diretórios de cache temporário foram
  removidos de forma restrita ao workspace.

Estado: concluído, sujeito às limitações e hipóteses abertas registradas.

### Auditoria localizada da Etapa 2

- Validado o fluxo Simulator → FastAPI → `LocalApplicationService` →
  artefatos congelados → persistência → cliente Streamlit com uma unidade e
  três ciclos consecutivos.
- Confirmado que risco, health visual, alerta e staleness continuam definidos
  somente no serviço local; os adaptadores apenas validam, transportam,
  persistem ou exibem esses campos.
- Corrigidos o backend HTTP efetivo do dashboard, o health check do banco e o
  limite de ciclos para smoke tests do simulador.
- Testes localizados: 21 aprovados e dois warnings externos de depreciação.
- Validação do Compose e smoke PostgreSQL ficaram pendentes porque o executável
  Docker não está disponível neste host.

Verificação final: **165 testes e 226 subtests aprovados em 47,46 s**, três
warnings internos do SHAP, `pip check` aprovado e auditoria com todos os checks
verdadeiros.

## Versão 0.15.0 — aplicação local integrada

Data: 2026-09-15.

- Criado `LocalApplicationService`, fachada somente leitura sobre artefatos
  congelados de `validation`, com seletores de unidade, H15/H30, modelo,
  política de telemetria e cadência de inferência.
- Criadas interface Streamlit e CLI sobre o mesmo serviço. A lógica científica,
  os status e a validação de contratos não ficam no código visual.
- A trajetória apresenta risco, sobrevivência, health visual, alerta,
  componentes, anomalia, disagreement, validade, staleness, idade dos dados,
  reason codes, transmissão e bytes. RUL fica restrito ao modo retrospectivo.
- Implementados estados explícitos `valid`, `degraded` e `unavailable`, sem
  imputar risco plausível quando falta dado ou artefato compatível.
- A seção Engineering assurance resume configuração, manifesto, requisitos,
  hipóteses e limitações com negação explícita de certificação/compliance.
- Streamlit 1.64 foi adicionado ao ambiente Python 3.11 e o pacote foi instalado
  como versão 0.15.0.
- Testes específicos: 11 testes e 5 subtests aprovados, incluindo smoke test
  real via `streamlit.testing`.
- Regressão completa final: **160 testes e 223 subtests aprovados em 34,16 s**, com
  três warnings de depreciação internos do SHAP já conhecidos. `pip check` não
  encontrou dependências quebradas. CLI instalada e servidor Streamlit headless
  foram inicializados com sucesso.

## Versão 0.14.0 — explicabilidade, calibração e incerteza empírica

Data: 2026-09-15.

- Auditados sete modelos probabilísticos congelados em 15 unidades de
  validation. Nenhum modelo foi criado/reajustado e nenhum threshold mudou.
- Geradas 30.450 contribuições locais top-5 por TreeSHAP e 18.270 agregações
  top-3 por sensor para XGBoost H15/H30. O score recarregado coincidiu com o
  artefato histórico com diferença máxima zero.
- Persistidas calibração, curvas de confiabilidade, coeficientes globais do
  hazard e ablação de TCN/Transformer em 256 origens determinísticas.
- Executadas 1.000 reamostragens de `unit_id` por horizonte. Todas as réplicas
  da fusão foram calculáveis; intervalos registram contagens válidas/inválidas.
- Criadas explicações integradas e exemplos reais de alerta correto e falso
  alerta, sem transformar `anomaly_score` ou `disagreement` em incerteza.
- Criados relatórios separados de validação e verificação; 77 requisitos têm
  evidência verificada, 17 permanecem parciais e um permanece planejado.
- Adicionados SRQ090–SRQ095 e ASM048–ASM052; matriz preserva a ordem exata dos
  95 requisitos.
- `test_internal`, `test_FD001.txt` e `RUL_FD001.txt` não foram lidos.
- **149 testes e 218 subtests aprovados** em 54,47 s; três warnings de
  depreciação internos do SHAP. `pip check` sem conflitos; pacote editável
  instalado como versão 0.14.0.

## Versão 0.10.0 — filtragem local de telemetria

Data: 2026-09-14.

- Criada interface sequencial `process`, preservando `filter` como conveniência
  causal sobre uma sequência já ordenada. Ciclos não crescentes são rejeitados.
- Implementados Full, intervalo fixo, subset com origem obrigatória no treino e
  adaptive com mudança absoluta/relativa, média móvel causal, variação e
  `anomaly_score` auxiliar configurável.
- Implementado receptor hold-last-value com ciclo da última observação, idade,
  flag de transmissão, validade por sensor, staleness geral e duas cadências de
  inferência. Valor mantido não é marcado como observação nova.
- Pacotes registram identidade, timestamp lógico, valores, bytes, motivo e
  política. Métricas registram transmissão, redução, frequência, tempo e modo
  de alta frequência. Bytes são estimativa local por tipo e overhead.
- Criados `telemetry_filter_engine.md` e `telemetry_change_impact.md`; FMEA,
  árvore lógica, dependências, contrato, SRQ052–SRQ060 e ASM027–ASM029 foram
  atualizados.
- Nenhum modelo, calibrador, threshold ou artefato preditivo foi reajustado.
  `test_internal` e teste oficial NASA não foram lidos.
- **103 testes aprovados** em Python 3.11 em 22,299 s; `pip check` sem conflitos.

## Versão 0.11.0 — experimento de redução de telemetria

Data: 2026-09-15.

- Criado `filtering/experiment.py` para executar políticas causais, reconstruir
  o estado no receptor e registrar pacotes, bytes, frequência, idade,
  staleness e estados de saída.
- Estendida `CausalTelemetryFeatures` com `fit_receiver_frame` e
  `transform_receiver_frame`: histórico temporal só avança em transmissões e
  a rota Full reproduz a implementação anterior.
- Congelada a grade Full, K=2/3/5, `subset_train17` e Adaptive q95/q99, com
  critérios experimentais pré-especificados em configuração. A validation
  comparou XGBoost, hazard discreto e fusão, por linha e por unidade, incluindo
  bytes, cobertura, calibração, alertas, lead time, latência e falsos alertas.
- Selecionadas deterministicamente `subset_train17` e `fixed_k3` para o
  retraining pareado. Cada fold reexecuta filtro, preprocessing, modelos base,
  detector, Weibull OOF, stacking e calibração por `unit_id`.
- `test_internal` permanece fechado até `freeze_manifest.json`; sua exposição
  anterior na fase 0.9.0 é declarada e não é tratada como holdout histórico
  virgem. O teste oficial NASA continua fora do escopo.
- Relatórios e artefatos: `reports/telemetry_filtering_report.md`,
  `reports/telemetry_change_impact.md`, `development_results.json`, métricas
  por unidade, previsões OOF/validation, manifesto e recibo de holdout.
  Exemplo sintético confirmou 224/96/168/128 bytes para Full/Fixed/Subset/Adaptive.

## Versão 0.9.0 — fusão probabilística e política inicial de alertas

Data: 2026-09-14.

- Auditadas e alinhadas 14.564 origens OOF de 70 unidades por horizonte. RF,
  XGBoost, hazard e Isolation Forest vieram dos artefatos OOF; a Weibull foi
  reajustada em cada fold de `unit_id`.
- Implementados média simples das quatro probabilidades e stacking logístico
  com `anomaly_score` apenas como covariável separada. A saída explicita
  `valid`, `degraded` e `unavailable`, além de survival, health e disagreement.
- Platt foi selecionado contra isotonic por log loss cross-fitted agrupado em
  H=15 e H=30. A rota final de inferência reproduziu exatamente as entradas de
  validation antes do congelamento.
- Thresholds escolhidos somente em validation: atenção=0,006568 (H30),
  alerta=0,158112 (H30) e crítico=0,201375 (H15), com persistência de três ciclos.
  São parâmetros experimentais do demonstrador.
- Validation stacking: H15 Brier=0,012694, log loss=0,043651, PR AUC=0,973083,
  F1=0,896247; H30 Brier=0,025415, log loss=0,097943, PR AUC=0,960961,
  F1=0,909910.
- A configuração foi congelada e `test_internal` foi lido uma única vez. H15:
  Brier=0,010178, log loss=0,033190, ROC AUC=0,998148, PR AUC=0,979309,
  F1=0,883534. H30: 0,013538, 0,049782, 0,998065, 0,989777 e 0,925342.
- Em `test_internal`, a antecedência mediana foi 17 ciclos em H15 e 32 em H30;
  houve 13/15 episódios falsos, com durações totais 53/61 ciclos. As violações
  p15>p30 foram 160 de 2.922 origens e permanecem explícitas.
- Criados análise de dependências comuns, árvore lógica conceitual, relatório,
  artefatos de fusão, política versionada, SRQ039–SRQ051 e ASM022–ASM026.
  `test_evaluation_receipt.json` registra uma leitura e nenhum uso do teste NASA.
- **92 testes aprovados** em Python 3.11 em 21,182 s; `pip check` sem conflitos.

## Versão 0.8.0 — monitor analítico Isolation Forest

Data: 2026-09-14.

### Implementação e isolamento

- Criado detector Isolation Forest local com `AnomalyPrediction` contendo score,
  identidade, versão, disponibilidade, validade e causa explícita quando
  indisponível. O score nunca é convertido em `risk_score`.
- O detector usa 324 features causais, scaler ajustado no fitting e referência
  saudável experimental `RUL>60` definida somente em `configs/anomaly_detection.toml`.
  RUL seleciona linhas offline; não integra o vetor de entrada.
- A transformação é `F_healthy(-score_samples)`: CDF empírica dos raw scores
  da região saudável de fitting. Score alto significa maior isolamento relativo,
  não probabilidade de falha/anomalia. `contamination='auto'`; não foi ajustado
  threshold operacional.
- Cinco folds com seed 4402 reajustam feature engineer e detector em unidades
  de fitting e geram 14.564 scores OOF. O detector final usa os 70 motores de
  treino e aplica nos 3.045 ciclos operacionais de validation. Teste interno,
  teste oficial NASA e RUL oficial não foram lidos.

### Comportamento em validation

- Região saudável retrospectiva RUL>60: 2.145 linhas, média 0,527380,
  mediana 0,521903 e P95 0,953975.
- Região próxima ao evento RUL≤30: 450 linhas, média 0,973334,
  mediana 0,989242 e P95 0,998992. Há mudança de distribuição no benchmark,
  mas isso não demonstra previsão de falha.
- Referência diagnóstica de percentil saudável 0,95 identificou 120 linhas
  saudáveis (5,59%). Várias primeiras marcações aparecem já no ciclo 1, por
  exemplo unidade 96 com RUL=335 e score 0,995851; elas são casos aparentes de
  antecedência que também revelam heterogeneidade entre unidades/falsos positivos
  analíticos, não detecção antecipada comprovada.
- Exemplos de scores altos ainda saudáveis: unidade 78/ciclo 2/RUL 229/score
  0,999904 e unidade 54/ciclo 2/RUL 255/score 0,998167. A referência 0,95 não
  é política de alerta ou recomendação de manutenção.

### Assurance e verificação

- Criados `monitoring_architecture.md`, model card, relatório, artefatos,
  SRQ035–SRQ038 e ASM019–ASM021. FMEA cobre indisponibilidade, silêncio,
  sensibilidade excessiva/insuficiente, score inválido e causas comuns.
- O monitor é diversidade analítica, não independência de safety: compartilha
  treino, sensores, features, seleção/imputação, folds, runtime e avaliação com
  os modelos de risco.
- Save/load do detector final reproduziu exatamente as 3.045 pontuações de
  validation; OOF tem 70 unidades e nenhuma chave `(unit_id, cycle)` duplicada.
- **77 testes aprovados** em Python 3.11.16 em 11,497 s; `pip check` sem
  conflitos. Dados, partições e artefatos dos modelos anteriores foram preservados.

## Versão 0.7.0 — hazard discreto landmark

Data: 2026-09-13.

Concluído:

- Implementado `DiscreteHazardRiskModel` com regressão logística discreta,
  features causais congeladas na origem, idade e passo relativo até Hmax=30.
- Landmark e alvo relativo separam evento observado de censura; passos após o
  fim do acompanhamento são excluídos da perda. Nenhuma censura foi fabricada
  no FD001 real.
- Perda/gradiente fatorados foram comparados à expansão explícita. Cinco folds
  determinísticos por `unit_id` reajustam preprocessing e modelo; OOF tem uma
  saída por origem e horizonte, sem sobreposição entre ajuste e holdout.
- Ajuste final nos 70 motores de treino e avaliação em 3.045 origens
  operacionais de validation. H=15/30 usam prefixos do mesmo hazard, com zero
  violações de coerência nos conjuntos OOF e validation.
- Validation: hazard H15 Brier 0,015063, log loss 0,047818, ROC AUC 0,996331,
  PR AUC 0,953002; H30 Brier 0,027172, log loss 0,111344, ROC AUC 0,991002,
  PR AUC 0,956559. O modelo fica atrás do XGBoost em Brier/log loss e PR AUC,
  próximo em discriminação; Weibull permanece significativamente inferior nos
  indicadores de desenvolvimento.
- Model card, métricas por unidade, calibração por idade, curvas, OOF,
  validation, artefatos de fold/final e hashes foram salvos em
  `reports/discrete_hazard`.
- SRQ031–SRQ034 e ASM016–ASM018 foram registrados; FMEA, contrato,
  dependências comuns, arquitetura, README, plano e changelog atualizados.
- Auditoria adicional passou a bloquear nomes retrospectivos antes da geração
  de sufixos de features. Nenhum Parquet, dado bruto, partição ou artefato
  histórico foi alterado; hashes anteriores conferidos.

Verificação: **73 testes aprovados** em Python 3.11; `pip check` sem conflitos.
Os testes incluem limites de hazard/sobrevivência/risco, prefixos, unidade,
evento, censura sintética, convergência, entrada inválida, save/load e cobertura
OOF. Testes internos e teste oficial NASA permaneceram fora da execução.

Estado atual: **0.6.0 — features causais, Random Forest e XGBoost concluídos**.
As seções anteriores registram o histórico; os resultados desta etapa estão
na seção 0.6.0 ao fim do documento.

Data: 2026-09-07.

## Concluído

- Inspeção completa dos arquivos existentes antes da primeira alteração:
  apenas a pasta Git, sem commits, código ou changelog.
- Plano de implementação registrado antes de criar a fundação.
- Estrutura Python 3.11 com layout `src`, sem dependências de execução.
- Diretórios de dados brutos, intermediários e processados, todos vazios.
- Sete interfaces abstratas independentes; nenhuma implementação de ingestão
  ou modelo concreto.
- Contrato comum `RiskModel` com `fit`, `predict_risk`, `save` e `load`.
- Saída comum com identidade do ativo/ciclo, risco, saúde e nome/versão do
  modelo; extensões opcionais de incerteza, anomalia e explicação.
- Documentação de responsabilidades, fluxo, semântica, decisões, extensões
  futuras e preparação do ambiente.
- Changelog criado e alinhado à versão 0.1.0 de `pyproject.toml`.

## Validação local realizada

- Python **3.11.16** preparado em `.tools/python`; ambiente `.venv` criado
  a partir desse runtime. O Python global 3.13.9 não foi alterado.
- Instalação editável concluída com
  `.venv/Scripts/python.exe -m pip install -e .`, usando o backend declarado.
- `.venv/Scripts/python.exe -m unittest discover -s tests -v`:
  **6 testes aprovados**, incluindo importação das sete interfaces, abstração,
  método de classe `load`, saída padrão, campos opcionais, limites dos escores
  e coerência da versão com o changelog.
- `.venv/Scripts/python.exe -m pip check`: nenhum requisito quebrado.
- Importação de `RiskModel` e `RiskPrediction` executada a partir de
  `reports`, fora da raiz; metadados instalados retornaram versão 0.1.0.
- Diretórios `data/raw`, `data/interim` e `data/processed` conferidos:
  somente seus arquivos `.gitkeep`.

As ferramentas de preparação foram baixadas para uso local. Isso não adiciona
serviços ou dependências de execução ao projeto. `.tools`, `.venv`, caches
e metadados gerados de instalação são ignorados pelo Git.

Os testes validam somente a estrutura e os contratos disponíveis.
Não houve avaliação preditiva, ingestão, treinamento ou execução de pipeline.
As regras de comportamento documentadas para implementações futuras ainda
precisarão de testes próprios quando essas implementações existirem.

## Arquivos criados

Todos os 37 arquivos abaixo foram criados nesta etapa; não havia arquivos
de projeto preexistentes a modificar.

- `.gitignore`
- `.python-version`
- `CHANGELOG.md`
- `IMPLEMENTATION_PLAN.md`
- `README.md`
- `configs/README.md`
- `data/interim/.gitkeep`
- `data/processed/.gitkeep`
- `data/raw/.gitkeep`
- `docs/architecture.md`
- `docs/decisions.md`
- `docs/progress.md`
- `notebooks/README.md`
- `pyproject.toml`
- `reports/README.md`
- `src/predictive_maintenance/__init__.py`
- `src/predictive_maintenance/application/__init__.py`
- `src/predictive_maintenance/core/__init__.py`
- `src/predictive_maintenance/core/records.py`
- `src/predictive_maintenance/data/__init__.py`
- `src/predictive_maintenance/data/interfaces.py`
- `src/predictive_maintenance/evaluation/__init__.py`
- `src/predictive_maintenance/evaluation/interfaces.py`
- `src/predictive_maintenance/features/__init__.py`
- `src/predictive_maintenance/features/interfaces.py`
- `src/predictive_maintenance/filtering/__init__.py`
- `src/predictive_maintenance/filtering/interfaces.py`
- `src/predictive_maintenance/models/__init__.py`
- `src/predictive_maintenance/models/anomaly/__init__.py`
- `src/predictive_maintenance/models/anomaly/interfaces.py`
- `src/predictive_maintenance/models/fusion/__init__.py`
- `src/predictive_maintenance/models/fusion/interfaces.py`
- `src/predictive_maintenance/models/interfaces.py`
- `src/predictive_maintenance/models/ml/__init__.py`
- `src/predictive_maintenance/models/reliability/__init__.py`
- `src/predictive_maintenance/models/temporal/__init__.py`
- `tests/test_contracts.py`

## Próxima etapa

Aguardar nova instrução. O primeiro caso de dados será exclusivamente FD001,
mas sua ingestão ainda não começou. Modelos, API, dashboard, Docker, AWS, Azure,
Kubernetes, Kafka, infraestrutura de cloud e hardware edge não foram implementados.

---

## Versão 0.2.0 — ingestão e validação FD001

Data: 2026-09-07.

### Concluído

- Os três documentos obrigatórios e toda a estrutura do código foram
  inspecionados antes das alterações.
- Esquema explícito com `unit_id`, `cycle`, três configurações e 21 sensores.
- Carregador reutilizável com conversão para tipos inteiros e de ponto flutuante.
- Validações de 26 colunas, valores numéricos, ausências, infinitos,
  identificadores, linhas duplicadas, ciclos duplicados, ordem crescente e
  sequência consecutiva `1..N` por unidade.
- Divisão 70/15/15 feita somente por unidades completas, com seed 42 em
  `configs/fd001.toml` e manifestação explícita das unidades de cada partição.
- Persistência local em três Parquets, com manifesto SHA-256 e relatório JSON.
- O conjunto oficial de teste e o arquivo RUL foram excluídos da preparação
  interna; o teste automatizado inclui um `test_FD001.txt` inválido para
  comprovar que ele não é lido.
- README, arquitetura, decisões e changelog atualizados para 0.2.0.

### Estado e resultados dos dados reais

`data/raw` contém somente `.gitkeep`. Nenhum dado foi fabricado, nenhum Parquet
de produção foi criado e a validação real não foi executada. Assim, número de
motores, ciclos totais, mínimo, máximo, mediana e comportamentos estranhos nos
valores permanecem indisponíveis. O status completo está em
`reports/fd001_data_status.md`.

Para a próxima execução, o usuário deverá colocar `train_FD001.txt`,
`test_FD001.txt` e `RUL_FD001.txt` em `data/raw`. Apenas o primeiro será lido
nesta fase.

### Validação do código

- Python 3.11.16.
- `python -m unittest discover -s tests -v`: **20 testes aprovados**.
- A escrita e leitura dos três Parquets foi validada em diretório temporário.
- Divisão de 20 unidades da fixture: 14 treino, 3 validação e 3 teste interno,
  sem interseções e com todas as linhas de cada motor preservadas.
- `python -m pip check`: nenhum requisito quebrado.
- Execução sem os arquivos oficiais: falha clara antes de criar conteúdo em
  `data/processed`.

### Arquivos criados nesta etapa

- `configs/fd001.toml`
- `reports/fd001_data_status.md`
- `src/predictive_maintenance/application/prepare_fd001.py`
- `src/predictive_maintenance/data/cmapss.py`
- `src/predictive_maintenance/data/cmapss_schema.py`
- `src/predictive_maintenance/data/reporting.py`
- `src/predictive_maintenance/data/splitting.py`
- `src/predictive_maintenance/data/validation.py`
- `tests/test_fd001_ingestion.py`

### Arquivos modificados nesta etapa

- `CHANGELOG.md`
- `IMPLEMENTATION_PLAN.md`
- `README.md`
- `configs/README.md`
- `docs/architecture.md`
- `docs/decisions.md`
- `docs/progress.md`
- `pyproject.toml`
- `reports/README.md`
- `src/predictive_maintenance/application/__init__.py`
- `src/predictive_maintenance/__init__.py`
- `src/predictive_maintenance/data/__init__.py`
- `src/predictive_maintenance/data/interfaces.py`

### Limite da etapa

O trabalho para aqui. Não foram criados modelos, atributos avançados, análise
exploratória, dashboard, Docker, cloud ou integração com hardware edge.

---

## Execução da pipeline FD001 com dados oficiais

Data: 2026-09-07.

- Os três arquivos oficiais foram encontrados e tiveram seus hashes SHA-256
  registrados em `reports/fd001_data_status.md`.
- `train_FD001.txt`: 20.631 linhas, 100 motores e 26 colunas validadas.
- `test_FD001.txt`: 13.096 linhas, 100 motores e 26 colunas validadas
  separadamente, sem participar da divisão interna.
- `RUL_FD001.txt`: 100 linhas e uma coluna; todos os valores são numéricos,
  finitos, inteiros e positivos, em quantidade compatível com o teste oficial.
- Treino e teste oficial possuem zero valores ausentes ou infinitos, zero
  linhas duplicadas, zero chaves `(unit_id, cycle)` duplicadas e sequências
  temporais consecutivas válidas para todas as unidades.
- Estatísticas do treino: mínimo 128, máximo 362 e mediana 199 ciclos por motor.
- Divisão interna com seed 42: 70 unidades e 14.634 linhas em treino;
  15 unidades e 3.060 linhas em validação; 15 unidades e 2.937 linhas em teste
  interno.
- Todas as três interseções entre conjuntos de unidades têm tamanho zero. A
  união contém 100 unidades e 20.631 linhas.
- Os três Parquets foram gerados, reabertos e reconstroem exatamente o treino
  original. Manifesto e relatório JSON também foram gerados.
- O teste oficial permaneceu separado: `official_evaluation.used = false` e
  nenhum `official_test.parquet` foi criado.
- Comportamento registrado: `setting_3` e os sensores 1, 5, 10, 16, 18 e 19
  são constantes no treino. Nenhuma coluna foi removida.
- Suíte final: 20 testes aprovados em Python 3.11.16; `pip check` sem
  requisitos quebrados.

Arquivos modificados nesta execução: `CHANGELOG.md`, `README.md`,
`docs/architecture.md`, `docs/progress.md`, `reports/README.md` e
`reports/fd001_data_status.md`. Os cinco artefatos gerados em
`data/processed/fd001` são dados locais ignorados pelo Git.

Nenhuma análise exploratória ou modelagem foi iniciada.

---

## Versão 0.3.0 — EDA e definição do problema

Data: 2026-09-07.

### Escopo e dados

- Arquitetura, decisões e progresso lidos integralmente antes das alterações.
- Somente arquivos processados utilizados. Nenhuma leitura de dados brutos,
  teste interno ou teste oficial na execução EDA.
- Desenvolvimento definido como treino + validação: 85 motores, 17.694 linhas.
- Estatísticas e gráficos recebem exclusivamente o treino: 70 motores e
  14.634 observações. A validação é usada apenas para chaves e alvos.
- Parquets de telemetria preservados com 26 colunas e hashes inalterados.

### Principais resultados

- Duração no treino: 128 a 362 ciclos, média 209,06 e mediana 200,5.
- Sensores constantes: 1, 5, 10, 16, 18 e 19. Sensor 6 quase constante,
  com dois valores e 98,15% das observações no valor dominante.
- Candidatos com tendências consistentes por unidade: 2, 3, 4, 7, 8, 11,
  12, 13, 15, 17, 20 e 21. Destaques: 11, 12, 4, 7 e 8.
- Sensores 9 e 14 apresentam heterogeneidade de direção entre motores;
  correlação agregada entre ambos de aproximadamente 0,964.
- `setting_3` é constante. Diferenças de escala são grandes e variância
  absoluta não mede importância. Nenhum sensor ou configuração foi removido.
- Curvas normalizadas são retrospectivas, com igual peso por motor e faixa
  P10–P90 descritiva; não são atributos ou intervalos de confiança.

### Alvos e definição

- `RUL = T_i - cycle`, sem truncamento; preservado como variável de avaliação.
- `failure_within_horizon = (RUL <= H)`, com H=30 ciclos configurável.
- Segundo horizonte configurável de 15 ciclos, estritamente menor que H.
- Horizontes são parâmetros experimentais, não regras industriais.
- Fronteiras inclusivas; RUL=0 é positivo e preservado. `is_operational`
  identifica linhas RUL>0 para métricas futuras de antecipação.
- Alvos gerados para todas as 14.634 linhas de treino e 3.060 de validação,
  em tabelas separadas da telemetria. Nenhum alvo de teste foi criado.
- Objetivo principal: estimar probabilidade de falha em horizonte futuro
  condicionada ao histórico disponível e ao ativo ainda operacional.
- Níveis normal, atenção, alerta e crítico definidos apenas conceitualmente.
  Thresholds serão definidos posteriormente com métricas de validação.

### Entregas e reprodução

- `reports/eda_report.md`: relatório completo e figuras incorporadas.
- `reports/eda/summary.json`: estatísticas, configurações, versões e hashes.
- Oito PNGs em `reports/eda/figures`: duração, RUL, trajetórias, variância,
  correlações, vida normalizada, configurações e diferenças entre motores.
- `data/processed/fd001/evaluation_targets/train_targets.parquet`.
- `data/processed/fd001/evaluation_targets/validation_targets.parquet`.
- `data/processed/fd001/evaluation_targets/metadata.json`.
- Código novo: `analysis/__init__.py`, `analysis/fd001.py`, `analysis/plots.py`,
  `analysis/report.py`, `data/targets.py` e `application/eda_fd001.py` dentro
  de `src/predictive_maintenance`.
- Configuração: `configs/fd001_eda.toml`; testes: `tests/test_fd001_eda.py`.
- Documento novo: `docs/problem_definition.md`.
- Atualizados README, pyproject, changelog, plano, arquitetura, decisões,
  progresso e READMEs de configurações/relatórios.

Executar: `.venv/Scripts/python.exe -m predictive_maintenance.application.eda_fd001`.

### Verificação

- Python 3.11.16; pacote 0.3.0 instalado e comando `eda-fd001` executado.
- **28 testes aprovados**; `pip check` sem conflitos.
- Teste de isolamento altera fortemente sensores da validação e verifica
  que estatísticas e candidatos do treino permanecem iguais.
- Teste de acesso confirma leitura apenas de treino e validação, mesmo com
  um arquivo de teste deliberadamente ilegível em diretório temporário.
- Alvos reais reabertos e comparados com a fórmula em todas as linhas,
  mantendo chaves e ordem.
- Oito PNGs verificados estruturalmente e inspecionados visualmente; links
  das figuras no Markdown conferidos.
- Nenhum modelo treinado, nenhum threshold definitivo ou seleção final.

## Versão 0.4.0 — contrato e engenharia de assurance

### Inspeção e escopo

- Lidos integralmente, antes de qualquer alteração: architecture.md, decisions.md,
  progress.md, eda_report.md, fd001_data_status.md e README.md.
- Inspecionados configs, código e testes. Consultadas somente descrições públicas
  oficiais SAE para delimitar referências conceituais, sem alegar leitura integral
  das práticas licenciadas ou conformidade.
- Não refeitas ingestão/EDA reais; não lidos teste oficial NASA nem seu RUL.
  Teste interno apenas conferido por hash, sem análise de sua tabela.

### Auditoria e correções

- RUL anterior correto para trajetórias completas; fórmula explicita agora
  max(T_i-t,0). Nenhuma divergência nas 17.694 linhas de alvos de treino/validação.
- População operacional: 14.564 linhas de treino e 3.045 de validação. As 85
  linhas terminais continuam nos arquivos retrospectivos. Nova função seleciona
  RUL>0 e acrescenta horizontes para futuro treinamento/calibração/avaliação.
- Risco definido como P(T_i<=t+H | F_i,t,T_i>t). Horizonte, status e validade
  obrigatórios; sobrevivência complementar e saúde derivada em [0,100].
  Ausência é None com causa, nunca risco zero presumido.
- Construção de previsões passa a argumentos nomeados; health_score preserva
  o nome, com mudança explícita de semântica/escala. Nenhum modelo ou previsão
  persistida anterior exigiu migração.
- Nenhum uso de variáveis retrospectivas em features foi encontrado. Bloqueio
  de nomes proibidos e proteção do mapeamento adicionados; teste causal de cada
  futura transformação e proveniência continuam necessários.
- Fusão declara chave com horizonte; avaliação declara população operacional
  e reporte separado de indisponibilidade. Permanecem interfaces abstratas.

### Requisitos, hipóteses e evidências

- SRQ001–SRQ018 capturados com origem, motivo, método de validação, método de
  verificação e status. Matriz com 18 linhas e referências de testes verificadas.
- Seis hipóteses: ASM001/002 confirmadas no escopo atual; ASM003–006 abertas
  (horizontes, disponibilidade temporal/operacional, critérios de decisão e
  utilidade probabilística nas unidades reservadas).
- HAZ001–HAZ008 registrados como estados indesejados internos, todos open;
  documentação não equivale a mitigar desempenho de modelos inexistentes.
- Template de impacto criado e avaliação CHG-0.4.0 preenchida no relatório de
  auditoria. Validação de requisitos e verificação da implementação distinguidas.
- SAE ARP4754B/ARP4761A apenas conceituais: sem certificação, compliance claim,
  AFHA/PASA/SFHA/PSSA/SSA/ASA formais, severidade regulatória, FDAL/IDAL,
  CMR/MMEL/TLD, safety objectives regulatórios ou probability budgets.

### Arquivos desta etapa

Criados:

- docs/prediction_contract.md
- docs/arp_mapping.md
- docs/safety_reliability_scope.md
- docs/safety_requirements.md
- docs/safety_assumptions.md
- docs/hazard_log.md
- docs/traceability_matrix.csv
- docs/change_impact_template.md
- reports/prediction_contract_audit.md
- src/predictive_maintenance/core/causality.py
- tests/test_prediction_contract.py
- tests/test_assurance_traceability.py

Modificados:

- src/predictive_maintenance/core/records.py
- src/predictive_maintenance/data/targets.py
- src/predictive_maintenance/models/interfaces.py
- src/predictive_maintenance/models/fusion/interfaces.py
- src/predictive_maintenance/evaluation/interfaces.py
- tests/test_contracts.py
- docs/architecture.md, docs/decisions.md, docs/progress.md
- docs/problem_definition.md
- README.md, CHANGELOG.md, IMPLEMENTATION_PLAN.md, pyproject.toml

### Verificação final

- Python 3.11.16; instalação editável 0.4.0 sem baixar novas dependências.
- **38 testes aprovados**; `pip check`: sem conflitos.
- Suíte inclui RUL zero/não negativo/decrescente/por unidade, fronteiras dos
  alvos, população operacional, horizonte obrigatório, limites de probabilidade,
  status/validade, saúde complementar, proteção de features e rastreabilidade.
- Os 21 arquivos preexistentes de data/processed e reports mantiveram SHA-256
  idêntico. Dados brutos não alterados; partições e configurações preservadas.
- Evidência numérica e impacto: [auditoria](../reports/prediction_contract_audit.md).
- Execução: `.venv/Scripts/python.exe -m unittest discover -s tests -v`.
- Etapa encerrada. Nenhum modelo treinado, sensor removido, threshold definido,
  dashboard, API ou infraestrutura implementada.

## Versão 0.5.0 — baseline populacional Weibull 2P

### Implementação e isolamento

- Weibull 2P com localização zero, beta/eta por MLE, densidade, CDF,
  sobrevivência, hazard, hazard acumulado e risco condicional estável.
- Ajuste com uma duração T_i por cada um dos 70 motores de treino; todos são
  eventos observados. A likelihood aceita censura futura, mas nenhuma censura
  foi criada ou usada no FD001 interno.
- Inferência aceita somente FeatureRecord com unit_id, cycle positivo e values
  vazio. Sensores/features são rejeitados; ciclo é idade causal do benchmark.
- Aplicação leu somente unit_id/cycle de train e validation. Não leu sensores,
  test_internal, teste oficial NASA nem RUL oficial. Nenhum dado/partição mudou.
- Save/load em JSON estrito e previsão idêntica após round-trip. Model card
  contém manifesto, configuração, parâmetros, contratos, hipóteses, limitações,
  métricas e SHA-256 do artefato.

### Ajuste, incerteza e aderência

- beta=4,4284658363 e eta=227,9879737770 ciclos.
- IC percentil 95% por 2.000 bootstraps não paramétricos de unidades: beta
  [3,8601072445; 5,6704664562], eta [215,2523702270; 241,1779702589].
- Cramér–von Mises com 2.000 réplicas paramétricas, ciclo inteiro reproduzido e
  MLE reajustada por réplica: W²=0,3457776841, crítico 5%=0,1227994407,
  p=0,0004997501; forma Weibull 2P rejeitada no treino.
- Maior desvio absoluto de sobrevivência: 0,155092 na região 202–231 ciclos;
  o baseline permanece referência simples e explicitamente misspecified.
- Sensibilidade avalia cada parâmetro em seus ICs e os quatro cantos do
  retângulo marginal, sem interpretar a faixa como intervalo de previsão.

### Validation operacional

- 15 unidades e 3.045 ciclos com RUL>0, avaliados sem reajustar o modelo.
- H=15: 225 positivos; risco médio 0,068597 versus observado 0,073892;
  Brier 0,060652; ROC AUC 0,876394; PR AUC/AP 0,309878; log loss 0,197435.
- H=30: 450 positivos; risco médio 0,135551 versus observado 0,147783;
  Brier 0,098197; ROC AUC 0,882405; PR AUC/AP 0,484177; log loss 0,293576.
- Métricas por unidade salvas em Parquet. ROC AUC/AP por unidade iguais a 1
  decorrem da monotonicidade por idade e do alvo terminal, não de calibração
  perfeita ou capacidade de distinguir motores.
- Nenhum threshold selecionado. Diferenças de prevalência impedem usar Brier
  ou log loss isoladamente para declarar um horizonte superior.

### Assurance, artefatos e verificação

- ASM007 invalidada pela aderência; ASM009 confirmada no escopo do benchmark;
  ASM003, ASM004, ASM005, ASM006, ASM008, ASM010 e ASM011 permanecem abertas.
  ASM001/ASM002 continuam confirmadas.
- SRQ019–SRQ022 adicionados e verificados. Matriz atualizada também para ligar
  a Weibull aos SRQ003–SRQ006, SRQ009–SRQ011 e SRQ015.
- Novos códigos: models/reliability/weibull.py, analysis/weibull.py,
  evaluation/probability.py e application/weibull_fd001.py.
- Nova configuração configs/weibull.toml; testes test_weibull.py e
  test_weibull_pipeline.py; relatório reports/weibull_report.md e artefatos em
  reports/weibull (cinco figuras, três JSON, dois Parquets e modelo JSON).
- Documentação, matriz, README, changelog, plano e versão atualizados.
- Pacote 0.5.0 instalado em Python 3.11.16. **48 testes aprovados** e
  `pip check` sem conflitos. Os 21 arquivos preexistentes de dados e resultados
  analíticos mantiveram SHA-256; reports/README.md foi atualizado como documentação.

Etapa encerrada sem Weibull 3P, Crow-AMSAA, Machine Learning, threshold,
dashboard, API, cloud ou edge.

---

## Versão 0.6.0 — features causais, Random Forest e XGBoost

Data: 2026-09-12.

### Implementação e isolamento

- Documentação metodológica/assurance e relatórios EDA/Weibull lidos antes das
  alterações. Changelog encontrado e atualizado para a versão vigente.
- `CausalTelemetryFeatures` gera idade, valor atual, delta, diferença relativa,
  variação absoluta acumulada, média, DP, mínimo, máximo e slope causal nas
  janelas 5/10/20, sempre reiniciando por `unit_id`.
- Seleção de constantes e imputação mediana ajustadas nas linhas operacionais
  do treino. Em OOF, ambas são reajustadas dentro de cada fold.
- Schema final: 324 features de 17 variáveis. Removidos `setting_3`, `sensor_1`,
  `sensor_5`, `sensor_10`, `sensor_16`, `sensor_18`, `sensor_19`. `sensor_6`
  permanece apesar da quase constância.
- Cinco folds determinísticos por unidade, seed 4302, cobrem os 70 motores uma
  vez como holdout. Não há unidade compartilhada entre fit/holdout do fold.
- RF e XGBoost separados para H=15/30, sem tuning extenso. Pesos combinam
  inverso do número de linhas da unidade e inverso da frequência de classe.
- 58.256 previsões OOF e 12.180 previsões de validation; quatro modelos finais
  e preprocessor salvos. Test_internal, teste oficial e RUL oficial não lidos.

### Resultados de validation

| H | Modelo | Brier | Log loss | ROC AUC | PR AUC | Precision | Recall | F1 |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 15 | Weibull | 0,060652 | 0,197435 | 0,876394 | 0,309878 | 0,300000 | 0,066667 | 0,109091 |
| 15 | Random Forest | 0,013750 | 0,043473 | 0,995992 | 0,955479 | 0,865471 | 0,857778 | 0,861607 |
| 15 | XGBoost | 0,010510 | 0,034221 | 0,997762 | 0,975207 | 0,903084 | 0,911111 | 0,907080 |
| 30 | Weibull | 0,098197 | 0,293576 | 0,882405 | 0,484177 | 0,527473 | 0,213333 | 0,303797 |
| 30 | Random Forest | 0,026506 | 0,098489 | 0,989627 | 0,954507 | 0,924390 | 0,842222 | 0,881395 |
| 30 | XGBoost | 0,022978 | 0,078590 | 0,994328 | 0,969911 | 0,923990 | 0,864444 | 0,893226 |

Precision/recall/F1 usam threshold fixo 0,5 exclusivamente exploratório.
Não houve calibração posterior ou política de alerta. Modelos separados
produziram 11 violações RF e 38 XGBoost de p15≤p30 em 3.045 chaves; o desvio
foi registrado sem correção silenciosa.

### Importância e leakage

- XGBoost gain salvo para o modelo final; permutation importance usa somente
  holdouts OOF, uma permutação por fold e agregação de cinco folds.
- Gain destacou médias móveis de sensores 15/3/21 em H15 e 4/15/17 em H30.
  Permutação destacou `sensor_6__cumulative_abs_change` nos dois horizontes;
  isso pode representar um proxy acumulativo de idade e exige ablação futura.
- Nenhum campo proibido entrou no schema. Testes por prefixo confirmam que
  alterar/anexar futuro não muda o passado e que janelas não cruzam unidade.
- Inconsistência corrigida: seleção inicial por variância reteve três colunas
  exatamente constantes por resíduo numérico. A regra passou a exigir também
  mais de um valor único e todos os artefatos foram regenerados.

### Assurance e evidência

- Criados `predictive_function_fmea.md` e `model_common_dependencies.md`, sem
  severidade regulatória, RPN ou alegação de independência/redundância.
- SRQ023–SRQ030 adicionados e verificados; ASM012–ASM014 abertas, ASM015
  confirmada no FD001. Hazard log, arquitetura, contrato, decisões, README,
  matriz, plano e changelog atualizados.
- Artefatos em `reports/classical_ml`: dois model cards, métricas JSON, três
  figuras, feature/fold manifests, importâncias, modelos e Parquets de previsão.
- Os 37 arquivos protegidos em raw/processed e relatórios EDA/Weibull mantiveram
  seus hashes SHA-256 após as duas execuções.
- Python 3.11.16, scikit-learn 1.9.1 e XGBoost 3.2.0. **61 testes aprovados em
  13,939 s** na verificação final; `pip check` sem requisitos quebrados.

Etapa encerrada sem test_internal, teste oficial, tuning extenso, calibração,
SHAP, fusão, threshold operacional, dashboard, API, cloud ou edge.

---

## Versão 0.11.0 — experimento de redução de telemetria

Data: 2026-09-15.

- O fluxo foi reconstruído causalmente no receptor para FullTelemetryFilter,
  FixedIntervalFilter (K=2, 3, 5), SensorSubsetFilter (`subset_train17`) e
  AdaptiveTelemetryFilter (q95 e q99). Features foram recalculadas somente com
  valores observados ou mantidos pelo passado; hold-last-value não avançou o
  histórico nem foi contado como observação nova.
- A referência Full reproduziu os artefatos anteriores com diferenças máximas
  0,0 (XGBoost), 4,66e-15 (hazard) e 2,66e-15 (fusão). A primeira fase usou
  modelos treinados com telemetria completa; a segunda refez o treinamento por
  fold de `unit_id` para `subset_train17` e `fixed_k3`.
- Os critérios de aceitação foram pré-declarados em
  `configs/telemetry_reduction_experiment.toml`. Validation selecionou somente
  `subset_train17`: redução de 25% nos bytes estimados, sem staleness,
  `degraded` ou `unavailable` e sem perda material nos modelos/horizontes.
  `fixed_k3` foi mantido como comparador, mas rejeitado por degradação,
  staleness lógico e perda de antecedência/desempenho.
- A avaliação congelada leu `test_internal` uma única vez depois do manifesto
  de freeze, para Full e `subset_train17`. No teste, a redução aprovada foi
  25%; PR AUC mudou entre -0,00062 e +0,00021 e Brier no máximo 0,00034,
  sem falha antecipada perdida. O recibo registra a exposição histórica do
  projeto ao `test_internal` na fase 0.9; não houve leitura do teste oficial
  NASA.
- Criados `reports/telemetry_filtering_report.md`, seis curvas em
  `reports/telemetry_filtering/figures/`, resultados por linha/unidade,
  manifests, hashes, previsões e recibo em `reports/telemetry_filtering`.
  Impacto, FMEA, árvore de falhas, requisitos SRQ061–069, hipóteses ASM030–035
  e traceability matrix foram atualizados. SRQ069 passou a verificação por
  manifesto/recibo; SRQ065/SRQ068 permanecem parciais porque a reexecução
  independente ainda não foi feita.

Esta etapa terminou sem declarar redução universalmente segura, sem alterar
dados brutos/partições, sem usar o teste oficial, sem dashboard, API, cloud,
edge ou novo modelo preditivo.

---

## Versão 0.12.0 — validação e integração da TCN causal

Data: 2026-09-15.

- O patch foi extraído fora do repositório. Seus 13 arquivos novos e 17
  modificados foram comparados antes da integração; documentação posterior da
  etapa 0.11.0 foi preservada por merge manual.
- A auditoria confirmou agrupamento por `unit_id`, prefixos até t, padding
  somente à esquerda, máscara binária e convolução causal. Foi removido o
  clipping silencioso e reforçada a rejeição de aliases de alvo/futuro,
  máscaras inválidas, overlap de unidades e checkpoint incompatível.
- A cabeça implementa `p15=sigmoid(a)` e
  `p30=p15+(1-p15)*sigmoid(b)`. Houve zero violações em 3.045 origens.
- Python 3.11.16, PyTorch 2.14.0+cpu, pyarrow 25.0.1, NumPy 2.4.6, pandas
  3.0.5 e scikit-learn 1.9.1. A época 3 foi escolhida em holdout agrupado
  somente do treino; o modelo limpo final usou todas as 70 unidades.
- H15: Brier 0,034437, log loss 0,110368, ROC AUC 0,994336, PR AUC 0,931467,
  precision 0,614754, recall 1,0, F1 0,761421 e lead time mediano 18 ciclos.
  H30: Brier 0,039308, log loss 0,128502, ROC AUC 0,984551, PR AUC 0,929680,
  precision 0,770115, recall 0,893333, F1 0,827160 e lead time 30 ciclos.
- A TCN tem 3.570 parâmetros. Seleção levou 9,987 s, ajuste final 5,144 s e
  inferência 0,313 s (0,1028 ms/origem), exclusivamente em CPU.
- Parquets, checkpoint, métricas, model card e relatório foram regenerados.
  O provenance registra hashes e `test_internal_read=false`,
  `official_test_read=false` e `official_rul_read=false`. Nenhum CSV preliminar
  foi mantido.
- Requisitos SRQ070–079, hipóteses ASM036–041, HAZ012, FMEA e dependências
  comuns foram incorporados. SRQ075 permanece parcial pela variação potencial
  entre plataformas; os demais SRQ070–079 estão verificados.
- Gates: 12 testes TCN + 11 subtests; 19 testes de contratos/assurance/TCN +
  112 subtests; regressão total de 131 testes + 194 subtests em 25,88 s, sem
  warnings. `pip check` não encontrou dependências quebradas.
- Comparação SHA-256 confirmou 204/204 arquivos históricos inalterados. A TCN
  permanece fora da fusão e nenhum threshold existente foi alterado.

---

## Versão 0.13.0 — Transformer Encoder causal pequeno

Data: 2026-09-15.

- Implementados dataset temporal, projeção 18→32, posição senoidal, quatro
  heads, duas camadas, feedforward 64, máscaras causal/padding e cabeça
  monotônica H15/H30. O modelo não usa linguagem nem arquitetura grande.
- Uma máscara combinada evita tanto atenção ao futuro/padding quanto softmax
  sem chave em consultas de padding. Testes alteram o sufixo e os valores
  mascarados para demonstrar invariância do prefixo e da saída.
- O mesmo split, as mesmas 18 entradas, janela 30 e alvos da TCN foram usados.
  Early stopping nas mesmas 14 unidades internas selecionou época 7; validation
  não participou do ajuste e o modelo final foi recriado nas 70 unidades.
- H15: Brier 0,007844, log loss 0,027611, ROC AUC 0,998966, PR AUC 0,987997,
  precision 0,886179, recall 0,968889, F1 0,925690 e lead time 15 ciclos.
  H30: Brier 0,017680, log loss 0,059983, ROC AUC 0,997069, PR AUC 0,983398,
  precision 0,878788, recall 0,966667, F1 0,920635 e lead time 31 ciclos.
- Em CPU: 17.762 parâmetros, seleção 64,855 s, ajuste final 50,554 s e
  inferência 0,513 s (0,1684 ms/origem). Parâmetros float32 ocupam 0,0678 MiB;
  working set analítico batch=1 0,0421 MiB; checkpoint 86.826 bytes.
- Contra TCN: 4,98× parâmetros, 1,64× latência e 4,19× checkpoint. Contra
  XGBoost, Brier caiu 25,37% em H15 e 23,06% em H30; PR AUC cresceu 0,012790
  e 0,013487.
- O Transformer foi o melhor comparador para execução local nesta validation.
  XGBoost permanece candidato conceitual mais equilibrado para edge por
  desempenho próximo e runtime mais simples; hardware real não foi testado.
- Criados checkpoint, Parquets, metrics, model card e relatório com hashes e
  provenance. `test_internal`, teste oficial e RUL oficial não foram lidos; o
  Transformer não foi adicionado à fusão e OOF continua desativado.
- FMEA, dependências, HAZ013, SRQ080–089, ASM042–047 e matriz foram atualizados.
  Regressão final: 142 testes e 212 subtests em 27,08 s, sem warnings;
  rastreabilidade isolada 1 teste e 89 subtests; `pip check` aprovado.
