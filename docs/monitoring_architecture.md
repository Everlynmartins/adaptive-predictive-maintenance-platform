# Arquitetura de monitoramento analítico — Isolation Forest

## Função monitorada

O monitor calcula desvio multivariado das features causais em relação à região
saudável experimental do treino FD001. Ele fornece `anomaly_score`, não estima
RUL, `risk_score`, probabilidade de falha ou uma decisão de manutenção.

## Sinais e meio de detecção

As entradas são as 324 features causais dos sensores/configurações, incluindo
idade observável, deltas, variação acumulada e janelas retrospectivas 5/10/20.
RUL, alvos, vida normalizada, ciclo terminal e informação futura não entram no
vetor. RUL é usado apenas offline para selecionar RUL>60 no treino como região
saudável experimental e para análise retrospectiva dos scores.

`IsolationForest.score_samples` é invertido para que maior valor bruto indique
maior isolamento. O score publicado é a CDF empírica dessa quantidade nas linhas
saudáveis de ajuste. Assim, valores perto de 1 são mais incomuns contra a
referência saudável; não são probabilidade. O limite de percentil 0,95 usado no
relatório é referência diagnóstica para estudar antecedência/falsos positivos,
não threshold operacional.

## Falhas observáveis e limites

O monitor pode tornar visíveis mudanças de distribuição multivariada, valores
fora da referência saudável, deriva gradual nas features e entrada incompatível
com o schema/finitude do artefato. Pode contribuir como evidência auxiliar para
investigar degradação simulada, sem fazer conversão automática para risco.

Ele provavelmente não detecta falha cujo padrão permaneça dentro da distribuição
de features, rótulo incorreto, evento terminal mal definido, telemetria antiga
sem timestamps/recebimento, falha de sensor que pareça normal, ou uma falha
comum no carregamento/preprocessing/runtime. A ausência de score alto não é
evidência de ausência de risco.

## Latência

No lote local, há um score por observação depois de gerar as janelas causais.
O cálculo não espera dados futuros. A latência de detecção em serviço dependerá
de frequência, chegada e atualidade da telemetria. O experimento 0.11.0 mediu
políticas locais e a aplicação 0.15.0 expõe staleness e disponibilidade, mas
nenhum SLA, relógio físico ou protocolo de transporte foi implementado.

## Dependências compartilhadas e independência

Isolation Forest adiciona diversidade de algoritmo, mas é **diversidade
analítica, não monitor independente**. Ele compartilha com os modelos de risco:

- os mesmos dados de treino e divisão por unidade, criando dependência estatística;
- os mesmos sensores e configurações, criando dependência de medição;
- `CausalTelemetryFeatures`, seleção de constantes e imputação, criando causa
  comum de preprocessing;
- Python, NumPy, pandas, scikit-learn/joblib, máquina local e avaliação,
  criando dependências de runtime e implementação.

Portanto, concordância entre score anômalo e risco não confirma correção, e
silêncio simultâneo não estabelece cobertura. O monitor não reduz requisitos de
validação, rastreabilidade, disponibilidade ou controle de mudanças.

## Integração com a fusão 0.9.0

O `anomaly_score` pode entrar como covariável do stacking logístico porque foi
gerado OOF por unidade no treino. Ele é excluído da média simples das
probabilidades e do cálculo de `disagreement`. A regressão logística aprende
uma associação estatística; essa associação não transforma o score em
probabilidade de falha nem demonstra independência do monitor. Se a covariável
estiver ausente, o stacking fica `unavailable`; o ensemble simples pode operar
como `degraded` quando houver ao menos duas probabilidades válidas.

## Efeito da filtragem 0.10.0

Uma política de filtragem pode reduzir ou atrasar os sinais usados pelo
Isolation Forest. Se detector e modelos receberem o mesmo estado HLV, a
filtragem torna-se outra dependência comum. O score auxiliar não deve acionar
frequência adaptativa sem registrar sua disponibilidade e o motivo da ativação.
