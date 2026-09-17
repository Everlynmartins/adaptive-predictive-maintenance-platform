# Auditoria do contrato de previsão — 0.4.0

Data: 2026-09-07. Ambiente local Python 3.11.16. Nenhum modelo treinado.

## Escopo e método

Leitura integral prévia de arquitetura, decisões, progresso, relatório EDA,
relatório de dados e README; inspeção de configs, src e tests. Busca dos campos
RUL, normalized_life, final_cycle, health_score, FeatureRecord e predict_risk.

Auditoria numérica somente das chaves de `train.parquet`, `validation.parquet`
e dos respectivos alvos existentes. Comparação linha a linha, tipos, chaves e
ordem por `pandas.testing.assert_frame_equal` contra `build_evaluation_targets`
com a configuração existente. Conferidos RUL terminal zero, não negativo,
decrescente por unidade e fronteiras inclusivas. Seleção operacional calculada
somente em memória, sem regenerar dados, ingestão, EDA ou figuras.

Teste interno não foi aberto como tabela/analisado; sua integridade foi apenas
conferida por hash junto aos demais artefatos processados. Teste oficial NASA
e RUL_FD001.txt não foram lidos. Dados brutos e partições não foram alterados.

## Resultados nos alvos existentes

| Partição | Unidades | Linhas | Operacionais | Terminais | Positivos operacionais H=30 | Positivos operacionais H=15 | RUL min/max |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| train | 70 | 14634 | 14564 | 70 | 2100 | 1050 | 0 / 361 |
| validation | 15 | 3060 | 3045 | 15 | 450 | 225 | 0 / 335 |

Todas as 17.694 linhas coincidem exatamente com o contrato retrospectivo;
17.609 são elegíveis à população T_i>t. Não houve correção de dados ou rótulos.
As 85 linhas terminais permanecem nos arquivos; não podem treinar/calibrar
ou avaliar a probabilidade de evento futuro condicionada à operação.

Hashes SHA-256 das entradas de alvos auditadas:

| Artefato em data/processed/fd001 | SHA-256 |
| --- | --- |
| train.parquet | 73167cca2c7899c84e286abf8ce5d7362b9f075d3782b5f3e53020fd8604fff1 |
| validation.parquet | d3f200b2e9832374b10fa961d968bbb3c3393d179ac973e4e087e1801c971a9e |
| evaluation_targets/train_targets.parquet | b5fcb56e75c08697711e0f011815b8cb42694e137ded052e5ae277eb7e94a234 |
| evaluation_targets/validation_targets.parquet | a25d99c8fa1d172f6d351dd76d3f4e6ef00c427704ed3230e2cb041298878fe9 |

Os 21 arquivos preexistentes em data/processed e reports, incluindo marcadores,
foram comparados por SHA-256 antes/depois das alterações e testes: zero diferenças.
Este relatório é novo e não substitui fd001_data_status.md ou eda_report.md.

## Inconsistências e correções

1. RiskPrediction não exigia horizonte, status ou validade; risco era descrito
   apenas como normalizado. Agora exige os três campos e probabilidade condicional.
2. Health_score era independente em [0,1]. Campo preservado, semântica corrigida
   para 100*(1-risk_score), com survival_score complementar. Migração explícita
   por argumentos nomeados; não se reinterpretam silenciosamente valores antigos.
3. RUL já estava correto nas trajetórias completas; limite inferior zero agora
   explícito. Antes havia máscara, mas não uma função para a população operacional;
   agora build_operational_targets oferece essa seleção para consumo futuro.
4. Não foi encontrado uso de RUL/vida normalizada como features. Havia somente
   contratos abstratos e separação de alvos, sem bloqueio na construção do registro.
   Adicionado bloqueio de nomes conhecidos e proteção de mutação do mapeamento.
   Causalidade de futuros cálculos/aliases ainda exige testes e revisão.
5. Fusão não declarava horizonte no alinhamento; agora a interface exige
   compatibilidade de unidade/ciclo/horizonte, estado e semântica.

## Impacto da mudança CHG-0.4.0

Motivo: formalizar o contrato antes de implementar modelos. Categorias:
contrato de saída/alvos, proteção de features e documentação; dependências
e configurações não mudaram. Revisão interna pelo mesmo fluxo de desenvolvimento.

| Item do template | Avaliação |
| --- | --- |
| Requisitos afetados | SRQ001–SRQ018 foram capturados nesta versão; implementação direta de SRQ003/004/007/014/016 e controles parciais dos demais. |
| Hipóteses afetadas | ASM001/002 sustentam uso dos dados; ASM003–006 continuam abertas. Nenhuma foi invalidada. |
| Estados indesejados | HAZ001–008 registrados; correções de contrato não encerram problemas de desempenho futuros. |
| Métricas afetadas | Futuras métricas prospectivas excluem terminais e reportam disponibilidade; health muda de escala. Não há métrica preditiva anterior a recalcular. |
| Regressão necessária | Contratos, escores, estados, RUL/alvos, isolamento por unidade, preservação e referências da matriz. Suíte completa executada. |
| Artefatos a regenerar | Metadados instalados do pacote e documentação 0.4.0. Nenhum Parquet/figura/relatório EDA antigo precisa ser regenerado: resultados completos permanecem iguais. |
| Interpretação dos resultados | Alvos terminais continuam retrospectivos; risco exige sobrevivência e horizonte; saúde é transformação visual [0,100]. |
| Compatibilidade | Construtores de previsões requerem campos novos e argumentos nomeados; adaptadores futuros devem aceitar horizon. Não há modelos/consumidores concretos persistidos a migrar. |
| Evidência anterior | Dados/EDA 0.3.0 mantêm versão/proveniência; testes antigos de saúde independente foram substituídos por testes do contrato novo. |
| Critério de aceitação | Consistência do contrato, nenhum alvo anterior divergente, suíte aprovada e artefatos protegidos intactos: atendido. Adequação operacional/calibração não avaliada. |
| Reversão | Uma reversão deve restaurar conjuntamente interface e semântica de escores da versão correspondente; dados preservados não exigem reversão. |

Validação de requisitos: revisão interna de coerência com o objetivo e definição
matemática; adequação dos horizontes, decisão simulada e desempenho ainda abertos.
Verificação: implementação confrontada com requisitos especificados através
dos testes abaixo. Nenhuma dessas evidências é certificação ou revisão independente.

## Verificação executada

```powershell
.\.venv\Scripts\python.exe -m pip install -e . --no-deps --no-build-isolation
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

Resultado final: **38 testes aprovados**, pacote 0.4.0 instalado, sem conflitos
de dependências. Uma execução intermediária identificou o changelog ainda sem
a entrada da versão nova; após atualização, a suíte completa passou.
Testes de ingestão/EDA executam apenas fixtures temporárias e não refazem
essas etapas com o FD001 real. Nenhum modelo, threshold ou filtro implementado.
