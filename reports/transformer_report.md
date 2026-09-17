# Transformer Encoder causal no FD001

## Escopo

Transformer pequeno, sem modelo de linguagem, treinado somente com prefixos da mesma unidade até t. Usa projeção linear, posição senoidal, máscara causal, máscara de padding e cabeça monotônica H15/H30.

## Treinamento e custo

Época selecionada: 7. Dispositivo: cpu. Parâmetros: 17762.
Seleção: 64.855 s; ajuste final: 50.554 s; inferência: 0.513 s (0.1684 ms/origem).
Memória de parâmetros float32: 0.0678 MiB; working set analítico batch=1: 0.0421 MiB.

Contra a TCN, o Transformer usa 4,98 vezes os parâmetros, 1,64 vez a latência
medida e 4,19 vezes o tamanho de checkpoint. O ajuste final levou 9,83 vezes o
tempo da TCN. A estimativa de memória exclui overhead do runtime PyTorch.

| Família | Artefatos centrais considerados | Bytes | Observação de custo |
| --- | ---: | ---: | --- |
| Hazard discreto | modelo + feature engineer | 42.458 | Modelo pequeno; preprocessing causal amplo. |
| XGBoost | H15 + H30 + feature engineer | 186.744 | Dois modelos e 324 features; sem runtime PyTorch. |
| TCN | checkpoint conjunto | 20.707 | Menor checkpoint; 0,1028 ms/origem medidos. |
| Transformer | checkpoint conjunto | 86.826 | Atenção quadrática; 0,1684 ms/origem medidos. |

Os tempos históricos de XGBoost e hazard não foram registrados com o mesmo
protocolo e, portanto, não são inventados nem comparados numericamente aqui.

## Comparação em validation

| H | Modelo | Brier | Log loss | ROC AUC | PR AUC | Recall |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 15 | transformer | 0.007844 | 0.027611 | 0.998966 | 0.987997 | 0.968889 |
| 15 | tcn | 0.034437 | 0.110368 | 0.994336 | 0.931467 | 1.000000 |
| 15 | xgboost | 0.010510 | 0.034221 | 0.997762 | 0.975207 | 0.911111 |
| 15 | discrete_hazard | 0.015063 | 0.047818 | 0.996331 | 0.953002 | n/a |
| 30 | transformer | 0.017680 | 0.059983 | 0.997069 | 0.983398 | 0.966667 |
| 30 | tcn | 0.039308 | 0.128502 | 0.984551 | 0.929680 | 0.893333 |
| 30 | xgboost | 0.022978 | 0.078590 | 0.994328 | 0.969911 | 0.864444 |
| 30 | discrete_hazard | 0.027172 | 0.111344 | 0.991002 | 0.956559 | n/a |

## Métricas temporais

| H | Lead time mediano | Falsos alertas/unidade | Persistência média |
| ---: | ---: | ---: | ---: |
| 15 | 15.00 | 0.7333 | 0.9500 |
| 30 | 31.00 | 1.0667 | 0.8178 |

## Ganho relativo

- H15: Brier 25,37% menor que XGBoost e 77,22% menor que TCN; PR AUC aumentou
  0,012790 e 0,056530, respectivamente.
- H30: Brier 23,06% menor que XGBoost e 55,02% menor que TCN; PR AUC aumentou
  0,013487 e 0,053718, respectivamente.

Para execução local nesta configuração, o Transformer é o melhor modelo
preditivo. Para futura execução edge, XGBoost é o candidato inicial de melhor
equilíbrio entre desempenho, artefato compacto e runtime mais simples; essa
escolha exige medir latência e memória no hardware real. A TCN tem checkpoint
menor e latência neural medida mais baixa, mas perdeu desempenho material.

## Coerência e limites

Violações H15>H30: 0 em 3045 origens.

A arquitetura fornece diversidade analítica, não independência. Resultados limitados ao FD001; test_internal e teste oficial NASA não foram usados.
