# Análise de dependências comuns da fusão

Esta análise organiza causas capazes de afetar vários componentes do
demonstrador FD001 ao mesmo tempo. Ela não demonstra independência entre
membros do ensemble. Algoritmos diferentes continuam sujeitos a entradas,
objetivos, software e decisões compartilhadas.

| Dependência comum | Componentes potencialmente afetados simultaneamente | Efeito possível | Controle atual | Limite do controle |
| --- | --- | --- | --- | --- |
| Telemetria comum | RF, XGBoost, hazard discreto, Isolation Forest, stacking e política | Ausência, corrupção ou viés de sensores propaga scores incorretos ou indisponibilidade. | Esquema FD001, finitude, chaves e `input_validity`. | O lote offline não prova atualidade nem correção física do sensor. |
| Preprocessing comum | RF, XGBoost, hazard, Isolation Forest e stacking indireto | Erro de janela, imputação ou ordenação afeta os modelos de sensores juntos. | Features causais testadas, estado persistido e comparação exata da rota final em validation. | Implementações compartilham `CausalTelemetryFeatures` e runtime. |
| Features comuns | RF, XGBoost, hazard e Isolation Forest | Proxy espúrio ou feature defeituosa pode produzir concordância falsa. | Bloqueio de nomes retrospectivos e testes por prefixo/unidade. | Não existe fonte de features independente. |
| Mesmo conjunto de treino | Todos os modelos base, calibradores e meta-modelo | Viés amostral e relações específicas do FD001 tornam-se dependência estatística. | OOF por unidade e holdouts separados. | OOF reduz reutilização de unidade; não cria outra população. |
| Mesma definição de alvo | Weibull, RF, XGBoost, hazard, stacking, calibração e thresholds | Evento ou horizonte mal definido afeta todos os riscos e métricas. | Contrato versionado de `risk_score` e alvos inclusivos. | Não há evento operacional externo ao benchmark. |
| Mesmo runtime Python | Todos os componentes locais | Falha de NumPy, pandas, scikit-learn, XGBoost, joblib ou do processo interrompe várias funções. | Versões e hashes no model card/freeze. | Não há runtime diverso ou execução segregada. |
| Mesma configuração de horizonte | Modelos base, stacking, calibradores e política | Troca ou desalinhamento H15/H30 invalida probabilidades e níveis conjuntamente. | Horizonte em cada chave, artefato e configuração; alinhamento por chave. | Modelos separados ainda podem violar p15≤p30. |
| Mesma política de threshold | Stacking e apresentação dos quatro níveis | Threshold inadequado atrasa ou multiplica avisos mesmo com risco correto. | Configuração gerada apenas de validation e hash no freeze. | Custos e critério industrial não estão disponíveis. |
| Mesmo código de serialização | RF, XGBoost, hazard, Isolation Forest, stacking e calibradores | Incompatibilidade de `joblib` ou schema pode indisponibilizar vários artefatos. | Schema por classe, round-trip e hashes. | Vários artefatos ainda usam a mesma biblioteca e máquina. |

O baseline Weibull evita sensores e preprocessing causal, mas compartilha treino,
evento, horizonte, runtime, avaliação, calibração e política. O Isolation Forest
adiciona diversidade analítica; sensores, features, preprocessing, treino e
runtime comuns impedem classificá-lo como monitor independente.

O ensemble simples aceita degradação explícita com ao menos duas probabilidades
comparáveis. O stacking desta versão exige os quatro riscos e o score de
anomalia; uma covariável ausente torna essa rota indisponível. Fallback não
elimina a causa comum: ele apenas evita converter ausência em risco zero.

## Filtragem como nova dependência compartilhada

Se uma política filtrada alimentar todos os modelos, omissão, atraso, HLV,
staleness ou erro adaptativo poderá afetar RF, XGBoost, hazard, Isolation Forest
e fusão simultaneamente. Uma única política de transmissão não cria fontes de
informação independentes. O experimento 0.11.0 tratou política, receptor,
feature engineering e calibradores como uma cadeia comum versionada. O resultado
reduz incerteza sobre a grade FD001, mas não cria fontes independentes.

## TCN temporal como diversidade analítica — 0.12.0

| Dependência comum | Componentes afetados simultaneamente | Consequência possível |
| --- | --- | --- |
| Telemetria FD001 | TCN, RF, XGBoost, hazard, Isolation Forest e fusão | Corrupção, ausência ou viés pode propagar scores incorretos. |
| Evento terminal e alvos H15/H30 | TCN e modelos probabilísticos | Erro semântico afeta todos os riscos. |
| Partições e população FD001 | TCN e baselines | Viés amostral continua compartilhado. |
| Preparação e seleção de canais no treino | TCN e modelos de sensores | Erro anterior à ramificação atinge várias famílias. |
| Runtime Python | Pipeline local | Falha do processo ou dependência pode afetar componentes juntos. |

A arquitetura neural adiciona diversidade analítica, sem demonstrar
independência funcional, física, de desenvolvimento ou estatística. A TCN
permanece fora do stacking até existir OOF agrupado compatível com SRQ077.

## Transformer Encoder — 0.13.0

O Transformer compartilha com TCN e demais modelos a telemetria FD001, evento
terminal, alvos H15/H30, partições, seleção de sensores, normalização, janela
de 30 ciclos, runtime Python/PyTorch e validation. Com a TCN, compartilha ainda
dataset temporal, política de padding, early stopping agrupado e cabeça
monotônica. Erros anteriores à ramificação podem afetar ambos simultaneamente.

Atenção e posição senoidal oferecem diversidade de arquitetura, sem evidência
de independência física, funcional, estatística ou de desenvolvimento. O
Transformer permanece fora da fusão sem previsões OOF agrupadas.

## Aplicação local e assurance — 0.16.0

CLI e Streamlit compartilham `LocalApplicationService`, configuração, Parquets,
model cards e runtime. Uma falha nessa fachada pode afetar ambas as
apresentações. O consumidor revalida probabilidades e artefatos e publica
`degraded`/`unavailable`; essa detecção não torna a aplicação independente dos
produtores. A auditoria final usa os mesmos arquivos locais e fornece
verificação reproduzível, não um canal operacional separado.
