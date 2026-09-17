# Decisões arquiteturais

## D070 — Encerramento local e baseline de assurance (0.16.0)

A fase local é encerrada com auditoria executável, índice de configuração,
problem reports e assurance case. Como o checkout não possui commit Git, a
identidade usa versão e hashes de dados, configurações e artefatos; criar o
primeiro commit permanece ação futura de configuration management.

## D071 — Consumidor revalida o contrato

O serviço local revalida risco persistido: valor não finito ou fora de [0,1]
produz `unavailable` e validade inválida. RUL e endpoint terminal só são
calculados em modo retrospectivo explícito.

## D065 — Serviço único para Streamlit e CLI (0.15.0)

Status: aceito. Seleção, leitura de artefatos, composição dos scores, status e
assurance ficam em `LocalApplicationService`. Streamlit contém somente
apresentação e a CLI usa a mesma fronteira.

## D066 — Aplicação reproduz artefatos congelados de validation

Status: aceito. A aplicação 0.15.0 não ajusta modelos, calibradores ou
thresholds. Ela lê previsões e estados receiver-aware das etapas anteriores.
`test_internal` e o teste oficial NASA não integram o fluxo.

## D067 — Ausência e incompatibilidade são estados explícitos

Status: aceito. Um modelo sem artefato para a política selecionada não é
substituído. Telemetria velha, cadência sem inferência e artefato incompatível
geram `unavailable`; hold-last-value ainda válido gera `degraded`. Score ausente
permanece ausente.

## D068 — RUL somente em modo retrospectivo

Status: aceito. RUL e lead time verdadeiros são informação de avaliação. Ficam
fora do resultado padrão e só aparecem após seleção explícita do modo
retrospectivo, acompanhados de aviso visível.

## D069 — Assurance visual sem claim de certificação

Status: aceito. A interface resume versões, manifesto, requisitos, hipóteses,
limitações e telemetria, mas declara que isso não é certificado de segurança,
aeronavegabilidade ou conformidade ARP.

## D047 — Filtro recebe uma observação por vez (0.10.0)

Aceito em 2026-09-14. `process` é a fronteira primária e rejeita ciclos não
crescentes por unidade. O método batch apenas reinicia e percorre a sequência.
Isso torna o estado causal inspecionável e testável por invariância de prefixo.

## D048 — HLV preserva proveniência temporal

Aceito em 2026-09-14. O receptor guarda somente valores transmitidos, ciclo de
origem, idade, flag corrente e validade. Idade acima do limite produz stale;
valor mantido nunca recebe um novo ciclo de observação.

## D049 — Quatro políticas sob o mesmo contrato

Aceito em 2026-09-14. Full, intervalo fixo, subset do treino e adaptive geram o
mesmo pacote/estado. Adaptive usa somente mudanças causais e anomaly score
auxiliar opcional; RUL e alvos são proibidos em execução.

## D050 — Bytes são estimativa por tipo e overhead

Aceito em 2026-09-14. A fórmula local soma overhead configurado e bytes por
valor. Ela é adequada para comparação interna futura, sem representar protocolo
ou hardware aeronáutico real.

## D051 — Nenhum desempenho preditivo recalculado

Aceito em 2026-09-14. Esta versão verifica mecanismo, fluxo e instrumentação.
Modelos, calibração, thresholds, `test_internal` e teste oficial NASA não são
abertos ou regenerados. A análise de impacto define o próximo gate.

## D041 — Stacking somente sobre previsões OOF (0.9.0)

Aceito em 2026-09-14. RF, XGBoost, hazard discreto e Isolation Forest usam seus
artefatos OOF agrupados; a Weibull é reajustada em cada fold. O meta-modelo
logístico nunca recebe previsão in-sample da unidade usada como alvo.

## D042 — Anomalia permanece semanticamente separada

Aceito em 2026-09-14. A média simples contém apenas as quatro probabilidades. O
`anomaly_score` pode ser covariável do stacking, mas não participa do
`disagreement` e não é reinterpretado como probabilidade de falha.

## D043 — Platt selecionado por cross-fitting agrupado

Aceito em 2026-09-14. Platt e isotonic foram comparados por log loss
cross-fitted, com Brier como desempate. Platt venceu nos dois horizontes e nas
duas fusões; isotonic produziu extremos 0/1 e log loss pior, apesar de pequenos
ganhos de Brier em alguns casos.

## D044 — Política inicial escolhida somente em validation

Aceito em 2026-09-14. Atenção busca recall mínimo 0,98 em H30; alerta maximiza
F1 sob precision mínima 0,85 em H30; crítico usa o maior threshold acima do
alerta com recall mínimo 0,90 em H15. Persistência exige três ciclos
consecutivos. Todos são parâmetros experimentais versionados.

## D045 — Freeze antes da única avaliação interna

Aceito em 2026-09-14. Modelos, calibradores, thresholds, configuração e hashes
foram congelados antes da primeira leitura de `test_internal`. O recibo registra
uma leitura, ausência de reajuste e nenhum uso do teste oficial NASA.

## D046 — Coerência entre horizontes observada, sem reparo silencioso

Aceito em 2026-09-14. Como stacking e calibradores são separados por horizonte,
p15≤p30 não é garantido. Violações são reportadas por partição e nenhum score
foi alterado depois da avaliação congelada.

## D038 — Isolation Forest como detector analítico (0.8.0)

Aceito em 2026-09-14. Ajustar Isolation Forest local em features causais de
linhas RUL>60 do treino; o limite é hipótese experimental versionada, não
threshold de manutenção e não é escolhido em validation. A referência saudável
e o scaler são reajustados dentro de cada fold por unidade. Nenhum RUL/alvo ou
informação terminal chega ao detector como feature.

## D039 — Escala de anomalia separada de risco

Aceito. Publicar `F_healthy(-score_samples)` em [0,1], onde a CDF empírica é
estimada apenas nos scores saudáveis de fitting. Maior significa mais isolamento
relativo, não maior probabilidade de falha/anomalia. A referência de 95% usada
na análise é diagnóstica, sem política operacional. Estado indisponível mantém
score None e explicação.

## D040 — Diversidade sem independência

Aceito. Isolation Forest compartilha dados, sensores, preprocessing, folds,
runtime e avaliação com modelos de risco. A diferença de algoritmo não permite
alegar monitor independente ou redundância de safety. O monitor é somente sinal
analítico auxiliar, com dependências registradas em monitoring_architecture.md.

## D035 — Landmark logístico com origem congelada (0.7.0)

Aceito em 2026-09-13. Um modelo para k=1..30 recebe features causais em t,
idade t e k/30. Scaler usa somente origens elegíveis do treino do fold.
Logit aditivo com L2=1, sem interações/tuning. L-BFGS-B registra convergência;
falha interrompe ajuste. Perda/gradiente fatorados são testados contra expansão.
SciPy/joblib/threadpoolctl passam a dependências diretas declaradas.

## D036 — Censura e ponderação

Evento inclusivo; passos após evento/censura fora da perda. Endpoints são alvos
separados; nenhuma censura fabricada. Peso igual por passo e sem class balancing
preservam a frequência da likelihood. Motores longos contribuem mais passos;
dependência entre landmarks impede intervalos iid. SRQ025 descreve o ajuste
clássico, cujo balanceamento não é imposto ao hazard.

## D037 — Coerência e avaliação

Prefixos do mesmo ajuste produzem H15/30 por produto. Sem calibração posterior
ou thresholds. Folds seed4302 reajustam preprocessing e scaler; comparação
reutiliza previsões anteriores alinhadas por chave/horizonte. Calibração por
faixas fixas de idade é descritiva. Testes reservados não são utilizados.

## D001 — Python 3.11 e layout src

Status: aceito em 2026-09-07. Usar `>=3.11,<3.12` nesta etapa. O layout `src`
exige instalar o pacote para testar importações e reduz dependência acidental
do diretório atual. A versão é 0.6.0 em `pyproject.toml`, acompanhada pelo
changelog. pandas/pyarrow suportam tabelas e Parquet;
NumPy/Matplotlib, análise; scikit-learn/XGBoost, modelos clássicos locais.

## D002 — Classes abstratas pequenas

Status: aceito. Sete interfaces com `ABC` e `abstractmethod`, distribuídas pelos
módulos responsáveis. Não criar hierarquia genérica de pipelines, registro
automático, barramento de eventos ou contêiner de dependências. As interfaces
declaram o contrato; os adaptadores futuros terão testes de comportamento.

## D003 — Uma interface de risco para todas as famílias

Status: aceito. `RiskModel` usa `fit/predict_risk/save/load`. As famílias ficam
em diretórios separados, mas a aplicação consumirá o mesmo tipo de saída.
O carregamento é um método de classe do modelo concreto; não existe descoberta
automática de modelos ou formato universal de serialização nesta versão.

## D004 — Registros independentes de bibliotecas de ML

Status: aceito. Dataclasses e mapeamentos nomeados evitam vincular o núcleo a
pandas, NumPy ou um estimador específico. É uma escolha adequada a contratos
locais iniciais, sem promessa de eficiência para grandes volumes.
`TargetRecord` separado permite aprendizado supervisionado e avaliação sem
misturar alvos com os atributos de entrada.

## D005 — Risco, saúde e anomalia têm significados distintos

Status: substituído por D017 em 0.4.0. A definição original aceitava risco e
saúde independentes em [0,1] e adiava horizonte. O novo contrato probabilístico
exige horizonte explícito e saúde derivada em [0,100]. A separação da anomalia
continua válida; limites numéricos não comprovam calibração.

## D006 — Separar dados originais, intermediários e preparados

Status: aceito. Os conteúdos de `raw/interim/processed` são ignorados pelo Git,
preservando apenas `.gitkeep`. Os arquivos oficiais continuam imutáveis em
`raw`. A preparação registra o SHA-256 do treino no manifesto e escreve somente
em `processed/fd001`. Nenhum dado foi baixado nesta etapa.

## D007 — Execução exclusivamente local

Status: aceito. `application` compõe comandos locais de ingestão, EDA e modelos.
Edge e cloud aparecem somente no desenho conceitual. Nenhuma API, dashboard ou
infraestrutura foi implementada.

## D008 — Separação temporal e por unidade antes do ajuste

Status: aceito. A divisão interna do treino oficial é feita exclusivamente por
`unit_id` antes de qualquer transformação aprendida. Seed 42 e proporções
70/15/15 ficam em configuração. Operações causais não poderão observar ciclos
futuros. Fusão e avaliação alinharão registros por `(unit_id, cycle, horizon)`
no contrato de previsão 0.4.0.

## D009 — Parsing estrito, sem reparo silencioso

Status: aceito em 2026-09-07. O carregador exige exatamente 26 campos e converte
`unit_id` e `cycle` para inteiros, com 24 valores em ponto flutuante. Erros são
agregados quando seguro. Linhas, ausências, duplicidades, ordem e lacunas
temporais não são corrigidas automaticamente.

## D010 — Ciclos consecutivos por unidade

Status: aceito. Cada motor deve aparecer em ordem crescente com ciclos `1..N`,
sem repetição ou lacunas. Essa regra torna truncamentos e perdas de linhas
visíveis antes do processamento. Uma fonte futura com outra convenção deverá
usar outro adaptador ou tornar sua política explícita.

## D011 — Divisão interna por unidade e teste oficial reservado

Status: aceito. A lista ordenada de unidades do treino é embaralhada com um
gerador local determinístico. O método dos maiores restos determina as
quantidades e mantém três partições não vazias. O conjunto oficial de teste e
o arquivo de RUL não são lidos nem usados para ajustar decisões nesta etapa.

## D012 — Parquet mais manifesto e relatório

Status: aceito. Cada partição interna é salva em Parquet. O manifesto registra
hash do treino, seed, proporções, unidades e linhas. O relatório JSON registra
as estatísticas estruturais solicitadas e sinaliza colunas constantes, sem
removê-las. A ausência dos arquivos impede a criação desses artefatos.

## D013 — EDA no treino; desenvolvimento = treino + validação

Status: aceito. Estatísticas, correlações e triagem recebem somente treino.
Validação é lida apenas para chaves e alvos separados. Testes não são abertos.
Nenhum sensor removido. Candidatos por constância e tendência são provisórios.

## D014 — Alvos retrospectivos separados da telemetria

Status: aceito. RUL sem truncamento por unidade em trajetórias completas.
Eventos RUL <= H. Máscara RUL > 0 para excluir o terminal das métricas de
antecipação. A função exige declaração de trajetória completa, sem censura.

## D015 — Horizontes experimentais e níveis apenas conceituais

Status: aceito. H=30 e H_critical=15 são configuráveis, não regras industriais.
Normal, atenção, alerta e crítico ainda não recebem thresholds. Métricas e
objetivo em [problem_definition.md](problem_definition.md).

## D016 — Peso por unidade e normalização retrospectiva

Status: aceito. Correlações de idade são calculadas dentro de cada motor.
Curvas de vida normalizada têm peso igual por motor e faixa P10–P90
descritiva. Não são atributos nem intervalos de confiança.

## Questões ainda adiadas

As decisões D017–D021 abaixo acrescentam o contrato e a organização de assurance.

- Seleção definitiva de atributos, validação de horizontes e calibração.
- Algoritmos de confiabilidade, ML, anomalia, séries temporais e fusão.
- Formato de artefatos de modelos, métricas preditivas e rastreamento de experimentos.
- Adaptação eficiente para timestamps, lotes grandes e execução remota.

Adiar essas decisões evita fixar tecnologias sem evidência do primeiro caso.

## D017 — Probabilidade condicionada e migração de escores

Status: aceito; substitui D005. `risk_score=P(T_i<=t+H | F_i,t,T_i>t)`;
horizonte, status e validade são obrigatórios. Saúde mantém o nome, agora
em [0,100] e derivada de sobrevivência. Não há compatibilidade semântica com
a pontuação independente anterior; construção nomeada torna a migração explícita.
Não existem modelos ou previsões persistidas anteriores. O registro verifica
consistência, não calibração, qualidade real da entrada ou atualidade.

## D018 — RUL retrospectivo e população operacional

Status: aceito. Explicitar `max(T_i-t,0)`, equivalente ao cálculo anterior
nos dados completos válidos. Preservar alvos terminais e artefatos 0.3.0.
`build_operational_targets` seleciona RUL>0 para futuro treinamento/calibração
e avaliação do risco condicional. Censura declarada permanece rejeitada;
tratamento genérico futuro está especificado no contrato, sem implementação.

## D019 — Causalidade: auditoria e proteção limitada

Status: aceito. Não foi encontrado uso de variáveis retrospectivas em features.
O novo bloqueio de nomes em FeatureRecord protege erros conhecidos e mutações
posteriores do mapeamento. Não detecta aliases arbitrários ou prova causalidade.
Transformações futuras exigem proveniência e invariância ao sufixo posterior a t.
Nenhuma feature avançada foi criada ou sensor removido.

## D020 — Assurance proporcional ao demonstrador

Status: aceito. Capturar 18 requisitos, hipóteses justificadas, oito estados
indesejados e rastreabilidade. Validação avalia correção/completude do requisito;
verificação avalia satisfação pela implementação. Evidência parcial deve continuar
identificada como tal. Não há aprovação independente ou validação operacional.
SAE ARP4754B/ARP4761A são apenas referências conceituais, conforme arp_mapping.md.

## D021 — Mudanças e evidências preservadas

Status: aceito. Versão 0.4.0 e changelog registram a mudança do contrato.
Mudanças relevantes exigem análise de impacto e evidência aplicável antes de
uso. Manifestos/relatórios 0.3.0 conservam sua proveniência original; não alterar
versões antigas para aparentar regeneração. Dados/partições e configurações
30/15, seed 42 permanecem intactos. Teste oficial não utilizado nesta etapa.

## D022 — Weibull 2P como baseline populacional por idade

Status: aceito em 2026-09-07. Ajustar beta e eta por máxima verossimilhança,
com localização fixa em zero, a um T_i por cada unidade de treino. A entrada
de inferência contém somente unidade e cycle; values não pode conter sensores
ou features. A idade conhecida t é informação causal. T_i é desfecho de treino,
nunca feature de inferência. O modelo é estatístico e não representa
automaticamente a física da degradação.

A likelihood aceita indicador de evento para futura censura à direita. Nesta
execução as 70 unidades são eventos observados; não se criou censura. Weibull
3P, Crow-AMSAA e ML permanecem fora do escopo.

## D023 — Incerteza e aderência por reamostragem de unidades

Status: aceito. ICs percentis de 95% para beta/eta usam bootstrap não
paramétrico de 2.000 amostras, reamostrando 70 tempos de vida completos.
Ciclos de uma unidade não são vidas independentes. Aderência usa Cramér–von
Mises com 2.000 réplicas paramétricas, arredondamento à resolução de ciclo e
reajuste dos parâmetros em cada réplica. Sementes e réplicas são configuração.

O teste rejeitou a Weibull 2P no treino. Ela permanece baseline misspecified
útil para comparação; não será apresentada como distribuição validada.

## D024 — Validation operacional, métricas globais e por unidade

Status: aceito. Avaliar H=15 e H=30 em 3.045 ciclos de validation com T_i>t.
Reportar Brier, ROC AUC, PR AUC por average precision, log loss, curva de
confiabilidade e risco médio versus frequência, além de resultados por unidade.
Métricas globais por linha retêm dependência intraunidade; a visão por motor
torna essa estrutura explícita. AUC/AP igual a 1 dentro de cada motor é efeito
da ordenação monotônica por idade e não valida calibração ou heterogeneidade.
Nenhum threshold é selecionado.

## D025 — Artefato JSON estrito e model card

Status: aceito. Persistir sem pickle, com esquema, beta/eta, contagens,
verossimilhança, nome/versão e manifesto. `load` rejeita esquema, localização,
parâmetros ou contagens incompatíveis. Model card registra configuração,
contratos, hipóteses, limitações, métricas, proveniência e SHA-256 do modelo.

## D026 — Holdouts e dados anteriores preservados

Status: aceito. A aplicação lê apenas colunas unit_id/cycle de train e
validation. Não abre sensores, test_internal, teste oficial ou RUL oficial.
Os dados processados e relatórios anteriores permanecem imutáveis; novos
resultados ficam em reports/weibull. Não se usa validation para reajustar beta,
eta ou escolher threshold.

## D027 — Features por prefixo causal e seleção dentro do treino

Status: aceito em 2026-09-12. Gerar valor atual, delta, diferença relativa,
variação absoluta acumulada e estatísticas/inclinação em janelas 5/10/20
alinhadas à direita. Reiniciar por `unit_id`; `age_cycle` é causal e explícita.
Constantes e medianas são ajustadas apenas nas linhas operacionais do treino do
fold. Testes por prefixo são evidência direta contra uso de sufixos futuros.

## D028 — Constantes exatas e sensor quase constante

Status: aceito. Remover por ajuste no treino `setting_3`, `sensor_1`, `sensor_5`,
`sensor_10`, `sensor_16`, `sensor_18` e `sensor_19`. A primeira execução usou
apenas variância e reteve três constantes por resíduo numérico; a regra foi
corrigida para exigir também mais de um valor único. `sensor_6` permanece porque
quase constância não comprova irrelevância e sua variação acumulada teve elevada
importância por permutação OOF.

## D029 — OOF agrupado e preprocessing reajustado por fold

Status: aceito. Cinco folds determinísticos embaralham unidades com seed 4302.
Cada unidade aparece uma vez como holdout e nunca no ajuste da própria previsão.
Seleção, imputação e estimador são reajustados em cada fold. OOF é artefato para
fusão futura; validation não participa dessa geração.

## D030 — Modelos separados por horizonte e configuração moderada

Status: aceito. Ajustar RF e XGBoost separados para H=15/30, sem busca extensa.
Pesos multiplicam contribuição inversa por duração da unidade e frequência da
classe, normalizados para média um. Um modelo final por algoritmo/horizonte usa
o treino completo; validation apenas mede resultados.

## D031 — Importâncias sem seleção por validation

Status: aceito. Gain do XGBoost descreve o ajuste final no treino. Permutation
importance mede aumento de Brier nos holdouts OOF, uma permutação por fold e
agregação de cinco folds. Ambas são diagnósticos preditivos sensíveis a
correlação, não efeitos causais e não autorizam seleção automática.

## D032 — Threshold fixo apenas exploratório

Status: aceito. Precision, recall e F1 usam 0,5 explícito para diagnóstico.
Não otimizar threshold em validation nem transformar esse valor em política de
alerta. Custos, persistência, antecedência e critérios de aceitação seguem
pendentes em SRQ012/ASM005.

## D033 — Coerência de horizontes medida, não corrigida

Status: aceito. Modelos separados podem violar p15≤p30. Em validation ocorreram
11 violações RF e 38 XGBoost em 3.045 chaves; magnitudes máximas 0,006115 e
0,000331. Registrar o desvio sem pós-processamento silencioso; futura calibração
ou modelagem conjunta deverá tratá-lo antes de níveis combinados.

## D034 — Diversidade algorítmica não implica independência

Status: aceito. RF e XGBoost compartilham dados, alvo, features, preprocessing,
folds, runtime e avaliação. Model cards e análise específica registram causas
comuns. Nenhuma fusão ou alegação de redundância independente é feita nesta etapa.

## D052 — Features receiver-aware para HLV (0.11.0)

Status: aceito. O fluxo filtrado recalcula features no estado do receptor. Uma
observação mantida conserva o estado derivado anterior, idade e validade; ela
não é anexada novamente às janelas, deltas, inclinação ou variação. Com todas
as transmissões, o fast path reproduz a rota de telemetria completa.

## D053 — Grade e critérios pré-especificados (0.11.0)

Status: aceito. A grade pequena, seeds, critérios e regras de seleção ficam em
`configs/telemetry_reduction_experiment.toml`. Os limites são critérios
experimentais do FD001, não objetivos regulatórios e não autorizam inferência
de uma porcentagem segura universal.

## D054 — Dois regimes de comparação (0.11.0)

Status: aceito. Primeiro são usados modelos treinados com fluxo completo e
inferência reconstruída; depois candidatas selecionadas em train/validation
refazem filtro, features, preprocessing, modelos, OOF, calibração e fusão por
unidade. A avaliação final abre somente candidatos congelados.

## D055 — Holdout específico com exposição histórica declarada (0.11.0)

Status: aceito. `test_internal` só é lido depois de `freeze_manifest.json` e
possui recibo one-shot próprio. O projeto já o abriu na fase 0.9.0, portanto o
recibo desta fase não é apresentado como holdout historicamente virgem.

## D056 — TCN causal pequena como comparador temporal (0.12.0)

Status: aceito. Usar janela 30, blocos 16/16, kernel 3 e 3.570 parâmetros.
Padding é somente à esquerda com máscara. Entradas são os 17 canais não
constantes definidos no treino e `age_cycle`; alvos e futuro são proibidos.

## D057 — Cabeça conjunta monotônica para H15 e H30 (0.12.0)

Status: aceito. `p15=sigmoid(a)` e `p30=p15+(1-p15)*sigmoid(b)`. A coerência
decorre da parametrização, sem pós-processamento. Validation teve zero
violações em 3.045 origens.

## D058 — Seleção de época somente dentro do treino (0.12.0)

Status: aceito. Early stopping usa 14 unidades agrupadas, separado das 56 de
ajuste. A época 3 foi escolhida; um modelo novo foi ajustado nas 70 unidades,
sem validation.

## D059 — TCN fora da fusão atual sem OOF neural (0.12.0)

Status: aceito. `[oof].generate=false`. O stacking 0.9.0 não mudou. Inclusão
futura exige previsões OOF por `unit_id` compatíveis com SRQ039 e SRQ077.

## D060 — TCN permanece comparador (0.12.0)

Status: aceito. A TCN teve métricas probabilísticas inferiores a XGBoost,
hazard discreto e fusão em H15/H30. Recall no threshold exploratório não
justifica promoção nem mudança na política atual.

## D061 — Transformer pequeno e comparável à TCN (0.13.0)

Status: aceito. Usar janela 30, d=32, quatro heads, duas camadas e feedforward
64, sem busca extensa. Features, unidades, horizontes e cabeça probabilística
são os mesmos da TCN.

## D062 — Máscara causal combinada com padding (0.13.0)

Status: aceito. Cada consulta válida bloqueia padding e futuro. Consultas de
padding mantêm apenas a diagonal finita para evitar softmax sem chave; continuam
mascaradas como chaves para posições válidas.

## D063 — Transformer como melhor comparador local, fora da fusão (0.13.0)

Status: aceito. O Transformer liderou Brier, log loss, ROC AUC e PR AUC em
validation, mas custa cerca de 5 vezes os parâmetros e 1,68 vez a latência da
TCN. Sem OOF neural, não entra no stacking.

## D064 — Candidato edge permanece XGBoost (0.13.0)

Status: aceito como recomendação conceitual. XGBoost mantém desempenho próximo,
artefatos compactos e runtime sem atenção/PyTorch; sua engenharia de 324
features continua um custo relevante. A decisão exige benchmark no hardware
real, ausente nesta etapa.
