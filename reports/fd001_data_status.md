# Relatório de ingestão e validação — FD001

Data da execução: 2026-09-07.

Status: **aprovado**.

## Arquivos oficiais

| Arquivo | Linhas | Colunas | Unidades | SHA-256 |
| --- | ---: | ---: | ---: | --- |
| `train_FD001.txt` | 20.631 | 26 | 100 | `963b5e22825b34d8b21c69e1aeb4af3e647050eb672ee8834ba4b5d91d2de0f8` |
| `test_FD001.txt` | 13.096 | 26 | 100 | `3cda7109ce17bafb5443f2ac926cfcf88154b941b8c4cf95eb55d1ddd6f52851` |
| `RUL_FD001.txt` | 100 | 1 | 100 valores | `a19c8ec94931949d0485bdc35118206e9c81c4547b422efb9cf86f4ceddbceca` |

O treino e o teste oficial foram carregados com o esquema ordenado:
`unit_id`, `cycle`, `setting_1` a `setting_3` e `sensor_1` a `sensor_21`.
O RUL contém 100 valores numéricos, finitos, inteiros e positivos; sua
quantidade coincide com as 100 unidades do teste oficial.

## Qualidade estrutural

| Verificação | Treino original | Teste oficial |
| --- | ---: | ---: |
| Valores ausentes | 0 | 0 |
| Valores infinitos | 0 | 0 |
| Linhas exatamente duplicadas | 0 | 0 |
| Chaves `(unit_id, cycle)` duplicadas | 0 | 0 |
| Unidades com sequência temporal inválida | 0 | 0 |

Todos os motores possuem ciclos consecutivos em ordem crescente, começando
em 1. Nenhuma linha foi preenchida, removida, corrigida ou reordenada.

## Estatísticas do treino original

| Métrica | Valor |
| --- | ---: |
| Motores | 100 |
| Ciclos totais | 20.631 |
| Mínimo de ciclos por motor | 128 |
| Máximo de ciclos por motor | 362 |
| Mediana de ciclos por motor | 199 |
| Sensores | 21 |
| Configurações operacionais | 3 |

## Divisão interna por unidade

Configuração: seed 42 e proporções 70%/15%/15%.

| Partição | Unidades | Linhas |
| --- | ---: | ---: |
| Treino | 70 | 14.634 |
| Validação | 15 | 3.060 |
| Teste interno | 15 | 2.937 |

As três interseções de `unit_id` possuem tamanho zero. A união contém as 100
unidades e os três Parquets, reunidos e ordenados por `unit_id, cycle`,
reconstroem exatamente o treino original.

O teste oficial permaneceu separado: `test_FD001.txt` não entrou na divisão,
o manifesto registra `official_evaluation.used = false` e não existe
`official_test.parquet`. Os identificadores numéricos 1 a 100 são reutilizados
pela NASA nos arquivos de treino e teste; eles designam populações distintas e
não significam que o teste oficial foi misturado às partições internas.

## Arquivos processados

| Arquivo | Tamanho |
| --- | ---: |
| `data/processed/fd001/train.parquet` | 405.330 bytes |
| `data/processed/fd001/validation.parquet` | 133.361 bytes |
| `data/processed/fd001/test_internal.parquet` | 133.027 bytes |
| `data/processed/fd001/split_manifest.json` | 1.717 bytes |
| `data/processed/fd001/validation_report.json` | 627 bytes |

Todos os três Parquets foram reabertos com sucesso, possuem 26 colunas e
preservam os tipos de `unit_id`, `cycle`, configurações e sensores.

## Comportamentos observados

Não foram encontrados erros estruturais. A validação sinalizou sete colunas
constantes no treino: `setting_3`, `sensor_1`, `sensor_5`, `sensor_10`,
`sensor_16`, `sensor_18` e `sensor_19`. Elas foram preservadas. A decisão sobre
seu uso pertence a uma etapa posterior de análise ou engenharia de atributos.

