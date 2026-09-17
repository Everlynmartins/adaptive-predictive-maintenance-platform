# Arquitetura local — versão 0.16.0

## Assurance da fase local

A arquitetura inclui uma camada de assurance que indexa configuração,
requisitos, hipóteses, problemas, evidências e hashes sem misturar essa
organização com a lógica científica. `final-assurance-local` executa auditorias
estruturais e simulações offline; a aplicação continua consumindo somente
artefatos congelados e propaga `valid`, `degraded` e `unavailable`.

## Aplicação local integrada

```text
artefatos congelados de validation ─┐
manifestos, requisitos e hipóteses ─┼─> LocalApplicationService
pacotes e estados do receptor HLV ──┘            │
                                      ┌──────────┴──────────┐
                                      │                     │
                                  Streamlit                CLI
                                  visualização       execução/exportação
```

`application/local_service.py` é a fronteira de negócio. Ele valida seleção e
compatibilidade dos artefatos, recompõe os componentes congelados, aplica
contratos de status, calcula scores complementares e expõe comparações e
assurance. Não ajusta modelos ou thresholds.

`ui/streamlit_app.py` somente seleciona cenário e renderiza tabelas, métricas e
gráficos. `application/local_cli.py` chama o mesmo serviço e pode exportar a
trajetória. Assim, o comportamento do contrato não depende do framework visual.

Cada cenário usa uma unidade de `validation`, H15/H30, um modelo, uma política
de telemetria e uma cadência. O serviço lê apenas o fluxo disponível no receptor.
Quando a política não possui artefato compatível para o modelo, a saída é
`unavailable`; não há substituição automática. Valor mantido causalmente produz
`degraded` enquanto válido, e staleness acima do contrato produz `unavailable`
com score ausente.

RUL e lead time reais ficam protegidos pelo modo retrospectivo. A página
Engineering assurance agrega evidências existentes sem atuar como certificação
ou auditoria final.

## Filtragem sequencial de telemetria

`filtering/policies.py` implementa quatro políticas locais por observação e o
receptor causal hold-last-value. A nova fronteira é:

`telemetria gerada -> decisão de transmissão -> pacote opcional -> receptor -> features/inferência`.

O receptor preserva o ciclo da última transmissão de cada sensor, idade,
validade e marca de observação corrente. Um valor mantido não é uma nova
medição. `telemetry_stale` e `inference_due` permitem que consumidores futuros
distingam estado atual, antigo, ausente e cadência de execução. A camada não
altera nem executa modelos nesta versão.

## Fusão probabilística e política inicial

`models/fusion/probabilistic.py` implementa a média simples das quatro
probabilidades comparáveis, stacking logístico por horizonte, calibração e a
política temporal de alertas. `application/fusion_fd001.py` separa a execução
em desenvolvimento e avaliação congelada: modelos base e meta-modelo aprendem
somente de previsões OOF por `unit_id`; validation seleciona thresholds; o
`test_internal` é aberto uma única vez depois do manifesto de congelamento.

O `anomaly_score` do Isolation Forest pode ser covariável do stacking, mas
permanece indicador de anormalidade e não entra na média probabilística.
`FusionPrediction` explicita `valid`, `degraded` ou `unavailable`; ausência de
componente ou entrada inválida nunca é convertida em risco zero. Thresholds e
persistência ficam em configuração versionada e representam somente uma
política experimental do demonstrador FD001.

## Extensão de anomalia

`models/anomaly/isolation_forest.py` implementa o contrato `AnomalyDetector`
com Isolation Forest, scaler, referência empírica saudável e persistência local.
`application/anomaly_detection_fd001.py` gera scores OOF por unidade e scores
de validation usando somente treino para ajuste. A seleção RUL>60 existe apenas
no caminho offline de seleção saudável; RUL nunca entra no vetor de features.
`anomaly_score` é evidência auxiliar e não é convertido para `risk_score`.
Detalhes de monitoramento, latência e dependências estão em
`monitoring_architecture.md`. O detector é diversidade analítica, não monitor
independente. Na fusão 0.9.0, ele é apenas uma covariável auxiliar
explicitamente separada das probabilidades.

## Extensão landmark

`models/temporal/discrete_hazard.py` implementa RiskModel com logit landmark,
scaler persistido, máscara de acompanhamento, produto de sobrevivência e save/load.
`application/discrete_hazard_fd001.py` compõe features existentes, folds e avaliação;
`configs/discrete_hazard.toml` controla horizontes, regularização e convergência.
A perda usa matrizes origem × passo sem duplicar as covariáveis. Endpoints só
constroem máscara/alvo. Modelos/preprocessors de fold e final, OOF e validation
ficam em `reports/discrete_hazard`. SRQ031–SRQ034 cobrem a extensão. Não há API,
infraestrutura, política de alerta ou reajuste dos modelos anteriores.

## Objetivo e limites

Separar os contratos de manutenção preditiva das fontes de dados, bibliotecas
de aprendizado e ambientes de execução. O primeiro caso é NASA C-MAPSS FD001.
Seu adaptador específico permanece isolado no módulo de dados; os contratos
centrais continuam genéricos.

Esta entrega preserva preparação local, EDA no treino e alvos de avaliação FD001,
acrescenta contrato probabilístico, requisitos e rastreabilidade do demonstrador,
e implementa o baseline Weibull, atributos temporais causais, Random Forest,
XGBoost, hazard discreto e fusão calibrada para H=15/30.
Inclui uma política inicial de alertas do demonstrador. Não inclui SHAP, API
web, dashboard, Docker,
AWS, Azure, Kubernetes, Kafka, infraestrutura de cloud ou hardware edge.

## Fluxo dos dados previsto

1. `CMAPSSFD001Loader` lê `train_FD001.txt`, atribui o esquema de 26 colunas,
   converte tipos e executa as validações. Os originais ficam em `data/raw`.
2. A aplicação divide unidades completas com seed configurada em treino,
   validação e teste interno. O teste oficial não entra nessa divisão.
3. As três partições são salvas em Parquet, acompanhadas de manifesto e
   relatório em `data/processed/fd001`.
4. Um `TelemetryFilter` processa cada observação causalmente, gera pacote
   opcional e atualiza o receptor sem interpolação futura.
5. Um `FeatureEngineer` ajustará seu estado apenas no treino e transformará
   observações em `FeatureRecord`. Atributos e partições poderão ser salvos em
   `data/processed`.
6. Um `RiskModel` produzirá `RiskPrediction` por ativo, ciclo e horizonte. Um
   `AnomalyDetector` opcional produzirá `AnomalyPrediction` separadamente.
7. Uma `ModelFusion` combina saídas de risco compatíveis e mantém anomalia
   separada; calibração e thresholds seguem o protocolo OOF-validation-freeze.
8. Um `Evaluator` comparará saídas com `TargetRecord` e retornará métricas
   nomeadas. Relatórios futuros pertencerão a `reports`.

As etapas 1 a 3, EDA/alvos, baselines, detector e fusão estão implementadas.
O teste interno não entra em ajuste ou decisões e foi usado uma única vez na
avaliação congelada 0.9.0. O teste oficial NASA continua sem uso.

## Responsabilidades e dependências

| Módulo | Responsabilidade |
| --- | --- |
| `core` | Registros, consistência de escores/estados e bloqueio de nomes retrospectivos. |
| `data` | Contrato genérico, esquema, carregador, validação, divisão e relatório FD001. |
| `data/targets.py` | RUL, eventos por horizonte e seleção da população operacional offline. |
| `analysis` | Estatísticas e figuras retrospectivas calculadas apenas no treino. |
| `features` | Contrato e implementação de atributos temporais causais, seleção e imputação. |
| `models/interfaces.py` | Contrato `RiskModel`, compartilhado por todas as famílias. |
| `models/reliability` | Weibull 2P populacional age-only e futuras referências estatísticas. |
| `models/ml` | Adaptadores Random Forest e XGBoost por horizonte sob o contrato comum. |
| `models/anomaly` | Contrato e Isolation Forest com score de anomalia separado do risco. |
| `models/temporal` | Hazard discreto landmark com features congeladas na origem. |
| `models/fusion` | Média simples, stacking logístico, calibração, estados degradados e política temporal. |
| `filtering` | Políticas sequenciais, pacote, HLV, idade/staleness, cadência e contabilidade. |
| `evaluation` | Contrato de avaliação, sem ajustar modelos. |
| `application` | Comandos locais de preparação, análise, modelos, monitor e fusão FD001. |
| `configs` | Seed, proporções e nomes dos arquivos FD001. |
| `notebooks` | Exploração e visualização importando funções do pacote. |
| `tests` | Verificação dos contratos, sem baixar dados. |
| `reports` | Resultados e relatórios futuros. |
| `docs` | Contrato, requisitos, hipóteses, estados indesejados, rastreabilidade e mudanças. |

`core` não importa os demais módulos. O adaptador FD001 usa pandas para a tabela
validada e pyarrow para Parquet. A aplicação futura receberá as instâncias
dos contratos explicitamente; não é necessário um framework de injeção,
registro de plugins ou fábrica nesta etapa.

## Registros e semântica

Desde a versão 0.3.0, `eda-fd001` consome os Parquets de treino e validação.
A análise recebe somente treino; validação recebe apenas alvos. Os testes
não são abertos. Alvos ficam em `data/processed/fd001/evaluation_targets`;
figuras e sumário, em `reports/eda`; o relatório é `reports/eda_report.md`.
A definição canônica está em [prediction_contract.md](prediction_contract.md).
Os artefatos EDA 0.3.0 permanecem válidos e não foram regenerados em 0.4.0.

`TelemetryRecord`, `FeatureRecord` e `TargetRecord` usam `unit_id: str`,
`cycle: int` e `values: Mapping[str, float]`. Sensores, condições operacionais,
atributos e alvos recebem nomes no respectivo mapeamento. A aplicação não
assume quantidade de sensores ou unidades. Um adaptador futuro normalizará
os identificadores numéricos do FD001 em strings.

A chave é `(unit_id, cycle)`. Dentro de cada fonte, ela deve ser única.
`cycle` representa um índice discreto de observação ordenado por ativo, não
uma duração física universal. Uma fonte baseada em timestamps poderá mapear
observações para esse índice e preservar timestamps e unidades em seus
metadados; sincronização em tempo contínuo não foi implementada.

`RiskPrediction` possui:

| Campo | Contrato |
| --- | --- |
| `unit_id`, `cycle` | Identidade da observação prevista. |
| `horizon` | Inteiro positivo obrigatório, em ciclos. |
| `risk_score` | Probabilidade condicional finita em [0,1] se disponível; senão None. |
| `survival_score` | 1 - risk_score, no mesmo horizonte; senão None. |
| `health_score` | 100 * survival_score; transformação visual em [0,100], ou None. |
| `model_name`, `model_version` | Identificação da implementação/artefato produtor. |
| `prediction_status` | available, unavailable ou not_operational; obrigatório. |
| `input_validity` | valid, invalid, stale ou unknown; obrigatório. |
| `uncertainty` | Mapeamento opcional de medidas nomeadas de incerteza. |
| `anomaly_score` | Escore opcional cuja escala deve ser documentada. |
| `explanation` | Texto explicativo; obrigatório se não houver probabilidade. |
| `disagreement` | Amplitude opcional entre probabilidades compatíveis, futura. |

O registro verifica tipos/limites, identidade não vazia, horizonte, estados e
complementaridade. Uma saída available exige input_validity=valid. Sem
probabilidade, risco/sobrevivência/saúde são None, nunca zero presumido.
O registro não verifica telemetria original, atualidade, calibração ou
completude do histórico. Alinhamento de lotes e compatibilidade estatística
continuam obrigações futuras das implementações.

A definição é `P(T_i <= t+H | F_i,t, T_i>t)`. Estar em [0,1] não basta para
estabelecer calibração. Uma regressão de RUL exige conversão justificada e
avaliada; anomalia é separada. Ausência de incerteza é None, não zero.

Dataclasses permanecem congeladas. FeatureRecord copia e protege o mapeamento
e rejeita nomes retrospectivos conhecidos; isso não prova causalidade de aliases
ou transformações futuras. Os demais mapeamentos devem ser tratados como somente
leitura. A migração 0.4.0 preserva o campo health_score, corrige sua escala e usa
construção por argumentos nomeados; detalhes no contrato canônico.

## Interfaces internas

| Interface | Operações | Saída |
| --- | --- | --- |
| `TelemetryIngestor` | `ingest` | Iterável de telemetria. |
| `FeatureEngineer` | `fit`, `transform` | Estado ajustado / lista de atributos. |
| `RiskModel` | `fit`, `predict_risk`, `save`, `load` | Modelo / lista de riscos / persistência local. |
| `AnomalyDetector` | `fit`, `detect` | Detector / lista de anomalias. |
| `ModelFusion` | `fuse` | Lista de riscos com identidade da fusão. |
| `TelemetryFilter` | `process`, `filter`, `reset`, `metrics` | Pacote opcional, estado causal do receptor e métricas. |
| `Evaluator` | `evaluate` | Mapeamento de nomes de métricas para floats. |

A ingestão genérica pode fornecer um iterável, enquanto o carregador FD001
também oferece um DataFrame validado. Os demais contratos usam lotes em
memória. Isso facilita inspeção local; não promete streaming, grandes volumes
ou processamento distribuído. Um lote vazio deverá produzir uma lista
vazia nas operações de predição e transformação; ajuste e avaliação sem dados
deverão rejeitar a entrada com `ValueError`. Implementações com estado ajustável
deverão rejeitar predição anterior ao ajuste/carregamento com `RuntimeError`.

Modelos supervisionados receberão alvos alinhados por chave; modelos sem
supervisão poderão aceitar `targets=None`. Engenharia de atributos temporal
poderá omitir ciclos iniciais sem histórico suficiente, mas deverá preservar
as chaves e a ordem das observações restantes e documentar sua janela.

`predict_risk(features, *, horizon=H)` exige horizonte explícito. Preditores
preservam uma saída por chave de entrada, inclusive quando indisponível.
Filtros preservam as
chaves e a ordem. Fusão alinha por chave, rejeita duplicidades, chaves faltantes,
lotes vazios e semânticas de risco incompatíveis, e preserva a ordem do primeiro
lote. A chave da fusão é `(unit_id, cycle, horizon)`; estados, evento e população
devem ser compatíveis. Não se deve combinar escores somente porque estão em [0, 1].
Um detector só participará dessa fusão por um adaptador de risco explícito;
escore de anomalia não será convertido implicitamente.

Avaliação verifica chaves e significado dos alvos antes de calcular métricas:
por exemplo, não compara diretamente RUL em ciclos com escore de risco.
A política de divisão por ativo/tempo e o horizonte deverão acompanhar os
relatórios futuros para evitar vazamento de informação.
Treinamento/calibração e métricas do risco condicional usam apenas T_i>t;
`build_operational_targets` fornece essa população offline. Alvos terminais
continuam preservados na tabela retrospectiva. Avaliadores futuros reportarão
indisponibilidade/cobertura separadamente, sem tratá-la como previsão zero.

## Camada de requisitos e evidências

[safety_requirements.md](safety_requirements.md) contém SRQ001–SRQ060;
[safety_assumptions.md](safety_assumptions.md) registra premissas e pendências;
[hazard_log.md](hazard_log.md) registra estados indesejados internos.
[traceability_matrix.csv](traceability_matrix.csv) liga requisito, implementação
e evidência. [change_impact_template.md](change_impact_template.md) orienta a
revisão de mudanças. Essa camada documental não cria serviços ou novas APIs.

Validação determina se o requisito é correto e suficientemente completo para
o objetivo. Verificação determina se a implementação satisfaz o requisito.
Requisitos planned/partial não são apresentados como garantias implementadas.
O [escopo](safety_reliability_scope.md) e o [mapeamento SAE](arp_mapping.md)
explicitam referências conceituais sem conformidade ou avaliação formal.

## Preparação FD001 implementada

O esquema é `unit_id`, `cycle`, três configurações e 21 sensores. O parser
exige 26 campos por linha. O validador rejeita valores ausentes, textuais ou
infinitos; identificadores não inteiros ou não positivos; linhas ou chaves
repetidas; ordem temporal decrescente; e sequências diferentes de `1..N` por
unidade. O carregador não corrige, preenche ou reordena dados silenciosamente.

A divisão embaralha a lista ordenada de unidades com `random.Random(seed)`,
nunca as linhas. As quantidades são obtidas pelo método dos maiores restos e
cada uma das três partições recebe ao menos uma unidade. O resultado preserva
a ordem das linhas do arquivo de treino.

O comando grava `train.parquet`, `validation.parquet`,
`test_internal.parquet`, `split_manifest.json` e `validation_report.json`.
O manifesto vincula o resultado ao SHA-256 do treino e enumera as unidades.
`test_FD001.txt` e `RUL_FD001.txt` são apenas verificados quanto à presença e
nunca lidos pelo comando atual.

## Adicionar um modelo futuramente

1. Criar uma classe concreta na família adequada, herdando de `RiskModel`.
2. Implementar `fit`, `predict_risk`, `save` e o método de classe `load`.
3. Retornar os registros padronizados e identificar a versão do artefato.
4. Salvar estado aprendido e metadados: nome/versão, esquema e ordem de
   atributos, configuração, pré-processamento necessário, semântica dos
   escores e compatibilidade. O formato de persistência será escolhido por
   implementação. `load` deverá rejeitar artefatos incompatíveis.
5. Testar contrato, alinhamento e equivalência antes/depois de salvar e carregar.
6. Passar a nova instância à aplicação. O consumidor continuará chamando
   `predict_risk` e lendo os mesmos campos, sem API específica por modelo.

`model_version` identifica o artefato do modelo, não necessariamente a versão
do pacote. Para trocar famílias de modelos, o esquema de atributos e a
semântica de risco também precisam ser compatíveis; a interface comum resolve
a integração de software, não garante equivalência estatística.

## Baseline Weibull 2P implementado

`Weibull2Parameter` herda de `RiskModel` e implementa densidade, CDF,
sobrevivência, hazard, hazard acumulado e risco condicional. O ajuste usa máxima
verossimilhança com localização fixa em zero e uma duração T_i por unidade.
Indicadores de censura à direita são aceitos pela likelihood para futura
extensão; no FD001 interno foram passados 70 eventos e zero censuras.

Na inferência, FeatureRecord fornece somente identidade e ciclo-idade; values
deve ser vazio e sensores são rejeitados. `predict_risk` devolve o contrato
comum. A pipeline `weibull-fd001` ajusta no treino, calcula bootstrap por unidade,
avalia aderência no treino e avalia H=15/30 somente nas linhas T_i>t de validation.
Artefatos ficam em `reports/weibull`, sem modificar dados processados.

O artefato JSON contém parâmetros, identidade, contagens, likelihood e manifesto;
`save/load` usa esquema explícito, sem pickle. O model card registra configuração,
hashes, hipóteses, limitações e métricas. A Weibull é baseline estatístico
populacional por idade, não modelo físico automático de degradação.

## Atributos causais e modelos clássicos

`CausalTelemetryFeatures` mantém `unit_id`/`cycle` como chaves e produz, para
cada configuração ou sensor variável, valor atual, delta, diferença relativa,
variação absoluta acumulada e média, desvio padrão, mínimo, máximo e inclinação
em janelas 5/10/20 alinhadas à direita. `age_cycle` é uma feature causal
explícita. Operações reiniciam por unidade; testes por prefixo confirmam que
ciclos futuros não alteram features já emitidas.

Seleção remove constantes e a imputação mediana trata valores estruturalmente
indefinidos. Ambos são ajustados no treino; em OOF, são reajustados dentro de
cada fold. O schema final possui 324 features derivadas de 17 variáveis, após
remover `setting_3`, `sensor_1`, `sensor_5`, `sensor_10`, `sensor_16`,
`sensor_18` e `sensor_19`. `sensor_6`, quase constante, permanece para avaliar
sua utilidade sem remoção heurística definitiva.

`RandomForestRiskModel` e `XGBoostRiskModel` implementam `RiskModel` e são
ajustados separadamente para H=15 e H=30. Pesos combinam contribuição igual
por unidade e balanceamento inverso de classe. Cinco folds determinísticos por
`unit_id` produzem previsões OOF; o modelo final usa o treino completo e
validation somente para métricas. Save/load usa artefatos joblib locais com
schema, configuração e hashes nos model cards.

Os modelos compartilham dados, alvo, features, preprocessing, runtime e
avaliação. A diversidade do algoritmo não é independência; detalhes estão em
[model_common_dependencies.md](model_common_dependencies.md). A análise de
modos de falha está em
[predictive_function_fmea.md](predictive_function_fmea.md).

## Edge e cloud, apenas conceitualmente

Um futuro adaptador de entrada poderá traduzir arquivos ou mensagens de
telemetria para os mesmos registros. Um futuro executor em edge poderá
compor filtragem, atributos e modelos compatíveis com seus recursos.
Um futuro executor em cloud poderá organizar lotes e armazenar artefatos,
reutilizando os casos de uso internos.

Esses executores e adaptadores ficariam fora do núcleo. Transporte,
agendamento, armazenamento remoto e observabilidade não entram nos contratos
de risco. Não foram criados SDKs, serviços, endpoints, containers ou código
de hardware para antecipar essas possibilidades.
# Arquitetura do experimento de redução de telemetria (0.11.0)

O experimento acrescenta uma fronteira explícita de fluxo de informação:

```text
telemetria validada → política causal → pacote → receptor HLV →
features receiver-aware → modelo/calibrador/fusão → métricas de serviço
```

O receptor nunca consulta o frame completo depois da filtragem. Features de
delta, janela, inclinação e variação só atualizam quando o sensor é realmente
transmitido; em um hold, o estado derivado anterior é carregado com idade e
validade. FullTelemetryFilter funciona como teste de equivalência da nova
rota. A grade de políticas, thresholds derivados, seeds e critérios fica em
`configs/telemetry_reduction_experiment.toml`.

O experimento mantém dois regimes. O primeiro aplica os modelos congelados da
telemetria completa ao estado reconstruído. O segundo refaz por folds de
`unit_id` o filtro, preprocessing, seleção/imputação, modelos base, detector,
Weibull OOF, stacking e calibração para poucas candidatas. Assim uma política
filtrada não recebe uma feature calculada previamente com sensores omitidos.

Bytes e latência são proxies locais. `telemetry_stale`, `degraded` e
`unavailable` permanecem no denominador das métricas de serviço; uma saída
indisponível nunca é convertida em risco zero. A seleção ocorre somente em
train/validation. Um manifesto próprio congela candidatos, artefatos,
thresholds e critérios antes de uma leitura única de `test_internal`, cuja
exposição anterior na fase 0.9.0 é declarada.

## TCN temporal causal — 0.12.0

`TCNRiskModel` recebe, para cada `(unit_id, cycle)`, somente o prefixo da mesma
unidade até t. Sequências de até 30 ciclos usam padding à esquerda, máscara
binária e normalização ajustada no treino. Convoluções causais e a cabeça
`p15=sigmoid(a)` e `p30=p15+(1-p15)*sigmoid(b)` preservam a ordem dos eventos.

O fluxo separa holdout agrupado interno do treino para escolher a época,
recriação do modelo, ajuste nas 70 unidades e avaliação nas 15 unidades de
validation. A TCN fica fora da fusão sem previsões OOF neurais agrupadas.
Telemetria, evento, alvo, partições, preparação e runtime são compartilhados.

## Transformer Encoder causal — 0.13.0

O Transformer reutiliza o mesmo contrato de sequência, features, unidades e
alvos da TCN. Uma projeção 18→32 é somada à posição senoidal; dois blocos com
quatro heads e feedforward 64 aplicam máscara causal e de padding combinadas.
A origem permanece no último token válido e alimenta a mesma cabeça monotônica
H15/H30. Early stopping ocorre somente dentro do treino e o modelo final é
recriado nas 70 unidades.

O modelo permanece fora da fusão sem OOF agrupado. Métricas de tempo, parâmetros,
checkpoint e memória analítica são tratadas como evidência local comparativa.
