# Configurações

`telemetry_filtering.toml` define custo de metadata/tipos, staleness, cadência
de inferência, K, subset documentado pelo treino e critérios adaptive. Os
valores adaptive são pontos iniciais sem comparação preditiva nesta versão.

`fusion.toml` define folds, seeds, stacking, candidatos de calibração e critérios
de thresholds. `fusion_alert_policy.toml` é gerado somente de validation e
versiona atenção=0,006568, alerta=0,158112, crítico=0,201375 e persistência de
três ciclos. Esses valores são experimentais do demonstrador FD001.

`discrete_hazard.toml` define Hmax=30, avaliações H=15/30, janelas 5/10/20,
cinco folds seed4302, L2=1 e limite/tolerância do otimizador. Logit determinístico,
sem class balancing. Faixas de idade de 50 ciclos servem somente ao diagnóstico
de calibração. Não são thresholds ou parâmetros industriais validados.

`fd001.toml` define os nomes dos arquivos oficiais e a divisão interna por
unidades. A seed e as três proporções são versionadas para que a divisão seja
reprodutível. O conjunto oficial de teste não participa dessa divisão.

`fd001_eda.toml` define horizontes experimentais, a grade de vida normalizada
e heurísticas de triagem aplicadas apenas ao treino. Não são thresholds
operacionais de alerta.

`weibull.toml` identifica o baseline Weibull 2P, horizontes 15/30, intervalos
de confiança, bootstrap de aderência, bins de calibração e idades da análise de
sensibilidade. Seeds e números de réplicas tornam a execução reproduzível.

`classical_ml.toml` contém janelas causais, folds por unidade, horizontes,
configurações moderadas de Random Forest/XGBoost, threshold exploratório e
repetições da importância por permutação OOF.

`anomaly_detection.toml` define Isolation Forest, seed, região saudável
experimental RUL>60, janelas, folds e uma referência diagnóstica de percentil.
Nenhum desses números é threshold operacional ou regra industrial.

`tcn.toml` define horizontes 15/30, sequência 30, canais 16/16, kernel 3,
dropout 0,10, batch 256, seed 4701, early stopping agrupado dentro do treino e
execução local CPU/GPU. `[oof].generate=false` mantém a TCN fora da fusão.

`transformer.toml` mantém sequência 30 e H15/H30, com d=32, quatro heads, duas
camadas, feedforward 64, dropout 0,10 e seed 4701. O modelo é pequeno, causal,
sem LLM e permanece fora da fusão com OOF desativado.

`explainability_uncertainty.toml` define dez bins de calibração, top-5 features,
top-3 sensores, amostra de 256 origens para ablação e 1.000 bootstraps por
`unit_id` com seed 4801. Os thresholds são cópia rastreada da política congelada
e só se aplicam às métricas de alerta da fusão; esta etapa proíbe retreinamento
e leitura dos conjuntos de teste.
