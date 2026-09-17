# Contrato de previsão — versão vigente 0.16.0

## Estado de telemetria filtrada (0.10.0)

A informação disponível em t inclui somente valores efetivamente recebidos até
t. Hold-last-value pode transportar um valor passado para o estado corrente,
mas preserva `last_observed_cycle`, `sensor_age_cycles` e
`was_transmitted_this_cycle=False`. Ele não cria nova observação.

Cada sensor recebido é `valid_observed`; um valor mantido dentro do limite é
`valid_held`; acima do limite é `stale`; sem transmissão anterior é
`unavailable`. `telemetry_stale` é verdadeiro se qualquer sensor requerido
estiver stale ou unavailable. A regra usa idade lógica em ciclos do benchmark;
outras fontes precisarão definir timestamps e limites próprios.

A inferência pode ocorrer em cada ciclo com o estado conhecido ou somente
quando chega pacote, conforme configuração. Uma futura adaptação para os
modelos deverá propagar staleness e não poderá tratar valor mantido como amostra
independente nas features temporais.

## Fusão, calibração e alerta (0.9.0)

A fusão recebe probabilidades alinhadas por `(unit_id, cycle, horizon)`, com o
mesmo evento e população operacional. A média simples usa somente Weibull,
Random Forest, XGBoost e hazard discreto. O stacking logístico pode receber
`anomaly_score` como covariável separada; isso não muda sua semântica nem o
transforma em probabilidade.

O meta-modelo aprende exclusivamente de previsões OOF de treino. A Weibull é
reajustada dentro de cada fold. Calibradores aprendem de scores cross-fitted;
validation seleciona os thresholds e `test_internal` só mede a configuração
congelada. `disagreement=max(p_m)-min(p_m)` mede divergência entre as quatro
probabilidades comparáveis. Não é intervalo de confiança nem evidência de
independência.

`FusionPrediction` usa os estados `valid`, `degraded` e `unavailable`. O
stacking exige as cinco covariáveis previstas; a média simples pode operar
degradada com pelo menos duas probabilidades válidas. Falta de componente,
entrada inválida ou telemetria declarada antiga permanece explícita e nunca
gera risco zero. Quando há risco válido,
`survival_score=1-risk_score` e `health_score=100*survival_score`.

Os níveis normal, atenção, alerta e crítico decorrem de thresholds versionados
e três ciclos consecutivos de persistência. São parâmetros experimentais
selecionados em validation para o demonstrador FD001, sem significado de limite
aeronáutico real.

## Hazard discreto landmark (0.7.0)

`h_i,t,k = P(T_i=t+k | T_i>=t+k, F_i,t)`, para k=1..H.
Como os ciclos são inteiros, `T_i>=t+k` é sobrevivência até o início do passo;
em k=1 equivale a `T_i>t`. Não se condiciona nos sensores futuros.
`S_i,t(H)=produto_{k=1..H}(1-h_i,t,k)` e `risk_score=1-S_i,t(H)`.
O produto aplica a regra da cadeia, não supõe independência entre passos.
`survival_score` representa esse S condicional.

Features e idade t ficam congeladas para todos os k. O logit é aditivo em
features padronizadas e k/Hmax, com intercepto; não usa sensores em t+k.
O modelo ajustado até Hmax usa prefixos iguais na inferência; horizontes
maiores são indisponíveis. Coerência em H não comprova calibração.

TargetRecord contém `observed_end` e `event_observed`, separado de FeatureRecord.
Evento em T: incluir k≤T−t, positivo somente k=T−t. Censura em C: incluir
k≤C−t como não eventos e excluir os demais da perda. Origem no terminal é
rejeitada; no fim censurado tem zero passos conhecidos e não ajusta scaler ou
likelihood. Endpoints de uma unidade precisam concordar. Completude/proveniência
continuam responsabilidade do adaptador. No FD001 todos os endpoints são eventos.

Censura é verificada somente em testes sintéticos; avaliação censurada/IPCW não
implementada. ASM011 continua aberta. As funções antigas de alvos completos
continuam rejeitando censura. Landmarks sobrepostos são dependentes: a perda
soma contribuições observadas com peso igual por passo e L2, sem balancear
classes. É uma verossimilhança composta; não se calculam intervalos iid.

Contrato interno comum a todas as famílias de modelos. A versão 0.9.0 inclui
Weibull 2P, Random Forest, XGBoost, hazard discreto e fusão calibrada. A política
inicial de alertas é apenas uma decisão simulada do demonstrador. Fonte dos requisitos: objetivo do demonstrador
definido pelo projeto; não são requisitos regulatórios.

## População, evento e histórico causal

Para a unidade i, T_i é o ciclo do evento terminal do benchmark e t é o ciclo
da observação. H é um inteiro positivo, em ciclos do benchmark. Não representa
horas, calendário, taxa de falha instantânea nem vida útil física universal.

Definimos F_i,t = sigma({x_i,s, condições_i,s, observações de disponibilidade_i,s:
s <= t e informação efetivamente recebida até t}, estado de processamento
aprendido exclusivamente no treino). A telemetria deve pertencer à unidade i.
Um registro com timestamp passado, mas recebido depois de t, não pertence a
F_i,t. Parâmetros aprendidos nas unidades de treino podem ser compartilhados;
o histórico de inferência não pode incluir o futuro da unidade avaliada.

Uma feature em t deve ser função mensurável desse histórico e de configuração
versionada disponível em t. Janelas são retrospectivas, nunca centradas;
estatísticas de toda a trajetória, suavização bidirecional e preenchimento
usando amostras futuras são proibidos na inferência.

## RUL e alvo por horizonte

`RUL_i,t = max(T_i - t, 0)`.

RUL é uma variável retrospectiva de avaliação, em ciclos, sem teto superior
artificial. O último ciclo tem RUL=0. Dentro de trajetórias consecutivas
completas, RUL diminui uma unidade por ciclo, independentemente dos outros motores.

Para instantes elegíveis, **T_i > t**:

`Y_i,t^(H) = 1[T_i <= t + H] = 1[RUL_i,t <= H]`.

RUL=H é positivo; RUL>H é negativo. O dataset retrospectivo existente mantém
o ciclo terminal com rótulo positivo, o que continua matematicamente válido
como descrição do evento. Entretanto, esse ciclo **não pertence à população
de treinamento, calibração ou avaliação da previsão condicionada**. Aplicar
`is_operational = (RUL > 0)`; `build_operational_targets` executa essa seleção
e acrescenta `horizon` e `critical_horizon`, sem escrever arquivos.
O uso de RUL para selecionar a população offline não autoriza usá-lo como feature.
Online, a condição operacional deverá vir de informação causal de estado do ativo.

H=30 e H_critical=15 continuam em `configs/fd001_eda.toml`. São experimentais,
configuráveis e não são regras industriais, thresholds ou objetivos de segurança.
Os dois alvos são distintos; o horizonte de cada probabilidade é explícito.

## Probabilidade principal e escores auxiliares

`risk_score_i,t^(H) = P(T_i <= t + H | F_i,t, T_i > t)`.

Essa é a semântica exigida de uma estimativa futura. Estar em [0,1] é necessário,
mas não comprova calibração ou exatidão. Um escore arbitrário normalizado ou uma
regressão de RUL não satisfaz automaticamente o contrato; sua conversão deverá
ser explicitamente justificada e avaliada usando validação.

`survival_score_i,t^(H) = 1 - risk_score_i,t^(H)` significa probabilidade de
permanecer além de t+H, condicionada a F_i,t e T_i>t. Não é S(t) incondicional.

`health_score_i,t^(H) = 100 * survival_score_i,t^(H)` pertence a [0,100].
É apenas uma transformação visual dependente do horizonte, sem significado de
percentual de vida física restante. Não é independente do risco.

`anomaly_score` mede desvio segundo detector, escala e referência documentados.
Não é probabilidade de falha e não substitui `risk_score`. Ausência é `None`,
não ausência de anomalia. A implementação Isolation Forest 0.8.0 usa escala
[0,1]: `F_healthy(-score_samples)`, a CDF empírica dos scores saudáveis de
treino. Maior é mais isolado relativamente àquela referência; o valor não é
probabilidade de anomalia nem de falha, e não é fundido automaticamente.

`AnomalyPrediction` preserva unit_id/cycle, nome/versão e tem
`prediction_status` (`available`/`unavailable`) e `input_validity`. Entrada
inválida produz score None, status unavailable e explicação. Esses estados não
são os estados da previsão de risco e não tornam o detector uma fonte de risco.

`disagreement`, quando definido, é a amplitude `max(p_m)-min(p_m)`
entre pelo menos duas probabilidades disponíveis para a mesma unidade, ciclo,
horizonte, evento e população. Pertence a [0,1]; participantes e regra de exclusão
devem constar dos metadados. Não é intervalo de confiança, independência ou
incerteza total. Sem conjunto compatível, usar `None`.

`uncertainty` é opcional; método, cobertura, escala e hipóteses precisarão ser
declarados. Campo ausente não significa incerteza nula. Para horizontes H1<H2,
probabilidades coerentes devem satisfazer p(H1)<=p(H2). A fusão mede essa
propriedade entre H=15/30; modelos/calibradores separados apresentaram violações
que permanecem visíveis, sem correção silenciosa. Um registro isolado não pode
verificar coerência entre horizontes.

## Estrutura e estados de saída

| Campo | Semântica e verificação atual |
| --- | --- |
| unit_id | String não vazia; identidade do ativo dentro da fonte. |
| cycle | Inteiro positivo; último ciclo disponível para a previsão. |
| horizon | Inteiro positivo obrigatório; unidade: ciclos. |
| risk_score | Real finito em [0,1] se available; caso contrário None. |
| model_name, model_version | Strings não vazias; identificam produtor/artefato. |
| prediction_status | available, unavailable ou not_operational. |
| input_validity | valid, invalid, stale ou unknown. |
| survival_score, health_score | Derivados do risco; None quando indisponível. |
| uncertainty, anomaly_score, explanation, disagreement | Extensões opcionais; explanation obrigatório sem probabilidade. |

`available`: probabilidade fornecida e entrada declarada `valid`.
`unavailable`: não há probabilidade utilizável (erro, insuficiência de histórico,
incompatibilidade de horizonte/artefato ou entrada sem validade).
`not_operational`: evento terminal já conhecido; a condição T_i>t não vale.
O produtor não deve inventar 0 ou 1 para representar indisponibilidade.

`valid`: passou pelas regras de esquema, qualidade, causalidade e atualidade
aplicáveis à fonte; `invalid`: regra violada; `stale`: excedeu a política de
atualidade; `unknown`: não há evidência suficiente. O registro verifica a
consistência declarada dos estados, **não inspeciona telemetria nem comprova
sua atualidade**. O validador FD001 existente verifica estrutura e sequência;
não implementa monitoramento online. Sem política/evidência, usar `unknown`.

Um resultado indisponível preserva a chave e horizonte solicitado, indica a
causa em `explanation` e mantém os três escores principais como `None`.
Métricas futuras informarão cobertura/indisponibilidade separadamente das
métricas de qualidade nas saídas disponíveis. Não descartar silenciosamente.

`RiskModel.predict_risk(features, *, horizon=H)` exige o horizonte. Adaptadores
deverão rejeitar ou marcar explicitamente horizontes não suportados; jamais
substituí-los. Fusão alinha `(unit_id, cycle, horizon)` e verifica semântica,
estados e proveniência. Não existe API separada por modelo.

### Compatibilidade e migração de 0.3.0

`health_score` permanece acessível e serializado com o mesmo nome. Na 0.4.0,
passa a ser calculado em [0,100]; se fornecido ao construtor, deve concordar
com a fórmula. Não é possível preservar simultaneamente a antiga semântica
independente [0,1] e a nova definição. Construtores passam a usar argumentos
nomeados e os três campos obrigatórios adicionais. Não há previsões persistidas
ou modelos anteriores a migrar; os testes de esquema foram atualizados.

```python
from predictive_maintenance.core.records import RiskPrediction

example = RiskPrediction(
    unit_id="1", cycle=10, horizon=30, risk_score=0.2,
    model_name="schema-example", model_version="example-only",
    prediction_status="available", input_validity="valid",
)
assert example.survival_score == 0.8
assert example.health_score == 80.0
```

O valor acima é apenas exemplo de contrato, não resultado de modelo.

## Variáveis proibidas e auditoria de data leakage

Proibidos como features: RUL, normalized_life, T_i, tempo final/terminal da
unidade, máximo de ciclo da trajetória completa, duração total, quaisquer
`failure_within_*`, `is_operational` retrospectivo e qualquer valor calculado
com informação posterior a t. `unit_id` é chave, não variável preditora.
O ciclo atual t pode ser causal; o máximo observado calculado **só no prefixo
até t** não é o máximo final da trajetória, mas também não justifica um campo
ambíguo chamado `max_cycle`.

A auditoria 0.4.0 encontrou essas grandezas em `data/targets.py` e em
`analysis`, com alvos separados da telemetria. Os modelos acrescentados depois
mantêm esses desfechos fora das features. `FeatureRecord` bloqueia nomes conhecidos
em `core/causality.py` e copia/protege seu mapeamento contra mutação posterior.
O bloqueio não detecta aliases arbitrários nem prova a origem causal de um valor.
Cada futura feature exige revisão de proveniência e teste de invariância de
prefixo: alterar/adicionar ciclos após t não pode mudar a feature em t.
Desde 0.6.0 há testes de prefixo do gerador causal concreto; em 0.7.0 o bloqueio
também ocorre antes de gerar sufixos. Isso não detecta aliases arbitrários.

Normalized life e estatísticas da trajetória completa permanecem exclusivamente
na EDA retrospectiva. Pré-processamento aprendido usa apenas treino; validação
orientará escolhas/calibração/thresholds; test_internal só após congelamento.
Nenhum dos testes serve para selecionar variáveis. Teste oficial reservado.

## Trajetórias completas e censura futura

Nas partições derivadas do treino original FD001, T_i é conhecido como o ciclo
terminal simulado. A função de alvos exige `complete_run_to_failure=True`,
chaves únicas e sequência completa `1..N`. Isso é uma declaração de proveniência,
não uma prova de completude: uma trajetória censurada também pode começar em 1.
O manifesto e o papel do arquivo de origem justificam o uso no desenvolvimento.

No teste oficial NASA, C_i (último ciclo observado) é menor que T_i. Futuramente,
o deslocamento r_i em RUL_FD001.txt permitirá avaliação com T_i=C_i+r_i, mantendo
esse deslocamento fora da inferência. Nenhum desses arquivos foi usado nesta etapa.

Para censura genérica, preservar C_i e indicador de evento observado; não
substituir T_i por C_i. Um evento observado em (t,t+H] é positivo; acompanhamento
sem evento até t+H permite negativo. Censura antes de t+H sem evento deixa o
alvo desconhecido, nunca negativo presumido. Métodos para censura, suas hipóteses
e métricas serão escolhidos e verificados futuramente; a função atual rejeita
censura declarada e não implementa esse processamento.

## Limitações e alertas

FD001 é um benchmark simulado com ciclos discretos e população limitada.
Seu evento terminal não é uma failure condition aeronáutica real. A constância
observada de sensores, regime operacional e tendências não prova transferência
para ativos reais. Rótulos retrospectivos não fornecem custos, disponibilidade
em serviço, políticas de manutenção nem validade industrial dos horizontes.

Normal, atenção, alerta e crítico possuem uma primeira política experimental
versionada. Thresholds e persistência foram escolhidos somente em validation
com métricas de calibração, precisão/recall, falsos alertas e antecedência.
Eles não são limites industriais definitivos; custos, histerese e critérios de
aceitação operacional continuam em aberto.

## Implementação de referência age-only

O baseline `Weibull2Parameter` condiciona somente na idade observável t, um
subconjunto de F_i,t: `P(T_i<=t+H | t,T_i>t)`. Não usa sensores, RUL ou ciclo
terminal na inferência. Seu treinamento recebe T_i como desfecho, uma vez por
unidade completa, e não como feature. `values` deve ser vazio; entrada fora
desse contrato é rejeitada. Resultados e limitações estão em
[weibull_report.md](../reports/weibull_report.md). A rejeição da forma Weibull
no teste de aderência impede tratá-la como lei validada, sem impedir seu papel
de baseline comparativo simples.

## Implementações clássicas com histórico causal

Random Forest e XGBoost estimam o mesmo evento e são ajustados separadamente
para H=15 e H=30. Seu conjunto de informação contém `cycle` e transformações
dos sensores/configurações cujo suporte termina em t. Janelas são alinhadas à
direita e reiniciam por `unit_id`; estatísticas globais aprendidas são ajustadas
somente no conjunto de treino correspondente.

Os alvos RUL≤H e a máscara RUL>0 são construídos em caminho separado e nunca
entram no `FeatureRecord`. Previsões OOF reajustam preprocessing e modelo sem a
unidade prevista. Como modelos separados não garantem monotonicidade em H, a
avaliação registra violações de `risk(H=15) <= risk(H=30)` sem corrigi-las
silenciosamente. As saídas ainda não receberam calibração posterior.
