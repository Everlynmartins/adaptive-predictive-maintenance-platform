# Temporal Convolutional Network causal no FD001

## Escopo

A TCN usa somente histórico da mesma unidade até o ciclo atual. As sequências têm comprimento fixo, com padding à esquerda e máscara explícita. O final da trajetória, RUL, normalized_life e rótulos não entram nas features.

A arquitetura é pequena e local. H15 e H30 são produzidos em uma única cabeça monotônica, portanto o risco H30 não pode ficar abaixo do H15 para a mesma origem.

## Seleção e treinamento

A seleção de época usou somente um subconjunto de unidades do treino. A época escolhida foi 3. O modelo final foi reajustado nos 70 motores de treino por esse número fixo de épocas. Validation não foi usada para early stopping.

Parâmetros treináveis: 3570. Tempo de seleção: 9.987 s. Tempo de ajuste final: 5.144 s. Inferência de validation: 0.313 s, ou 0.1028 ms por origem neste ambiente.

Execução oficial: Python 3.11.16, PyTorch 2.14.0+cpu, NumPy 2.4.6,
pandas 3.0.5, scikit-learn 1.9.1 e pyarrow 25.0.1. O modo de fonte foi
`processed_parquet`, com 70 unidades de treino e 15 de validation. O provenance
registra hashes da configuração, manifesto, Parquets de treino/validation e
manifesto de features. `test_internal`, teste oficial NASA e RUL oficial não
foram lidos.

## Comparação em validation

As métricas probabilísticas são diretamente comparáveis. Recall depende do threshold registrado por cada etapa e deve ser lido com essa ressalva.

| H | Modelo | Brier | Log loss | ROC AUC | PR AUC | Recall | Threshold |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 15 | tcn | 0.034437 | 0.110368 | 0.994336 | 0.931467 | 1.000000 | 0.500000 |
| 15 | xgboost | 0.010510 | 0.034221 | 0.997762 | 0.975207 | 0.911111 | 0.500000 |
| 15 | discrete_hazard | 0.015063 | 0.047818 | 0.996331 | 0.953002 | n/a | n/a |
| 15 | fusion_stacking | 0.012694 | 0.043651 | 0.997760 | 0.973083 | 0.902222 | 0.201375 |
| 30 | tcn | 0.039308 | 0.128502 | 0.984551 | 0.929680 | 0.893333 | 0.500000 |
| 30 | xgboost | 0.022978 | 0.078590 | 0.994328 | 0.969911 | 0.864444 | 0.500000 |
| 30 | discrete_hazard | 0.027172 | 0.111344 | 0.991002 | 0.956559 | n/a | n/a |
| 30 | fusion_stacking | 0.025415 | 0.097943 | 0.988694 | 0.960961 | 0.897778 | 0.158112 |

## Métricas temporais da TCN

Threshold exploratório da TCN: 0.500. Persistência: 3 ciclos. Estes valores não são limites de manutenção reais.

| H | Unidades com alerta | Lead time mediano | Falsos alertas por unidade | Persistência média | Fração média da vida sob alerta |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 15 | 15 | 18.00 | 1.3333 | 0.8389 | 0.1199 |
| 30 | 15 | 30.00 | 1.2000 | 0.7278 | 0.1685 |

## Coerência entre horizontes

Violações H15 maior que H30: 0 em 3045 origens. A propriedade é imposta pela cabeça probabilística conjunta.

## Participação na fusão

OOF TCN gerado: False. A TCN não foi adicionada à fusão atual. Motivo: TCN remains outside the current fusion in this stage; grouped OOF training is deferred because it would multiply local CPU training cost.

## Modos de falha específicos

A FMEA do demonstrador foi estendida com sequência curta, padding incorreto, máscara incorreta, checkpoint incorreto, não determinismo residual, saída inválida e latência excessiva.

## Dependências comuns

A TCN compartilha telemetria, definição de alvo, partições de unidades, runtime Python e parte da preparação dos dados com os demais modelos. Sua arquitetura temporal diferente constitui diversidade analítica, sem evidência de independência funcional, física, de desenvolvimento ou estatística.

## Justificativa experimental

A TCN não supera o XGBoost nas métricas principais deste experimento. Ela pode ser mantida somente como comparador temporal para testar se o Transformer acrescenta informação suficiente para justificar modelos sequenciais mais caros.

Resultados limitados ao NASA C MAPSS FD001. Nenhuma evidência desta etapa constitui demonstração de segurança operacional, certificação ou generalização industrial.

Os CSV preliminares do pacote não foram incorporados. As tabelas finais são
Parquet e seus hashes, junto ao do checkpoint, constam no model card.
