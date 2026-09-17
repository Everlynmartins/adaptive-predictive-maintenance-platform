# Dependências compartilhadas dos modelos clássicos

O hazard discreto (0.7.0) compartilha com RF/XGBoost as partições, features
causais, imputação, folds por unidade, bibliotecas básicas e avaliação. Acrescenta
scaler, máscara landmark e otimizador SciPy; utiliza perda sem balanceamento de
classe. Isso diversifica a formulação, mas não constitui redundância independente.
Falhas de origem, schema, preprocessing ou rótulos podem afetar os três modelos.

Isolation Forest (0.8.0) também compartilha esses dados, sensores, features,
imputação, folds, scikit-learn/joblib e avaliação. Embora não compartilhe o
mesmo objetivo supervisionado nem os pesos dos classificadores, a seleção RUL>60
e a referência saudável ainda dependem da mesma trajetória retrospectiva. É
diversidade analítica; não é monitor independente ou redundância de safety.

Random Forest e XGBoost usam algoritmos diferentes, mas **não constituem
redundância independente**. Eles compartilham componentes capazes de introduzir
falhas correlacionadas.

| Dependência comum | Possível efeito comum | Controle/evidência atual |
| --- | --- | --- |
| `train.parquet` e `validation.parquet` | Erro de origem, schema ou partição afeta ambos. | Hashes, manifesto e validação estrita; holdouts preservados. |
| Definição RUL≤H e população RUL>0 | Erro de alvo desloca simultaneamente treinamento e avaliação. | Função única de alvo, testes de fronteira e horizonte explícito. |
| `CausalTelemetryFeatures` | Vazamento, janela errada ou mistura de unidade contamina ambos. | Testes por prefixo e unit_id; preprocessor versionado. |
| Seleção de constantes e imputação | Feature omitida ou valor estrutural incorreto é comum. | Ajuste no treino de cada fold; schema e medianas persistidos. |
| Folds por `unit_id` | Sobreposição tornaria OOF otimista para ambos. | Manifesto completo, folds disjuntos e teste automatizado. |
| Peso por unidade e classe | Escolha inadequada altera as duas funções de perda. | Fórmula documentada e sumário de pesos por artefato. |
| Python, NumPy, pandas, scikit-learn/joblib | Falha de runtime ou serialização pode atingir ambos. | Versões nos model cards; round-trip testado. |
| Código de avaliação | Erro de métrica pode favorecer ou prejudicar ambos. | Métricas unitárias conhecidas e definições explícitas. |
| Validation usada no mesmo ciclo de desenvolvimento | Decisões repetidas podem sobreajustar ambos ao mesmo holdout. | Nenhum tuning extenso; test_internal e teste oficial ainda reservados. |

O XGBoost adiciona sua biblioteca e formato interno; Random Forest depende da
implementação de ensemble do scikit-learn. Essas diferenças fornecem diversidade
de algoritmo, não independência dos dados, objetivos ou evidências. Concordância
entre escores e pequena `disagreement` futura não demonstrarão correção.

Qualquer fusão futura deverá usar as previsões OOF, declarar essas dependências,
evitar treinar e avaliar o meta-modelo nas mesmas unidades e medir o impacto de
falhas comuns. Não se multiplicarão probabilidades assumindo independência.

## TCN temporal — 0.12.0

A TCN compartilha telemetria, evento terminal, alvos H15/H30, população FD001,
partições por unidade, preparação e runtime Python. Sua arquitetura oferece
diversidade analítica, sem evidência de independência. Ela não integra a fusão
porque OOF neural agrupado não foi gerado.

## Transformer Encoder — 0.13.0

O Transformer compartilha dados, alvos, unidades, canais, normalização,
lookback, PyTorch e protocolo de avaliação com a TCN. A atenção causal é uma
forma analítica diferente, não um canal independente. O modelo permanece fora
da fusão enquanto não houver OOF por `unit_id`.
