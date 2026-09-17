"""Markdown report generated exclusively from training summary statistics."""

from pathlib import Path

from predictive_maintenance.data.cmapss_schema import SENSOR_COLUMNS, SETTING_COLUMNS
from predictive_maintenance.data.targets import HorizonConfig


def _number(value) -> str:
    return "indefinido" if value is None else f"{value:.5g}"


def write_eda_report(path: Path, summary: dict, horizons: HorizonConfig,
                     eda: dict, figures: list[str]) -> None:
    h, critical = horizons.failure_horizon, horizons.critical_horizon
    lifetime = summary["lifetime"]
    column_stats = summary["columns"]
    table = [
        "| Sensor | Mínimo | Máximo | Variância | Valores únicos | Valor dominante | ρ mediano por motor | Direção concordante |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for sensor in SENSOR_COLUMNS:
        s = column_stats[sensor]
        table.append(
            f"| {sensor} | {s['min']:.5g} | {s['max']:.5g} | {s['variance']:.5g} "
            f"| {s['unique_values']} | {s['dominant_fraction']:.2%} "
            f"| {_number(s['median_unit_spearman_age'])} "
            f"| {_number(s['direction_agreement'])} |"
        )
    settings = [
        "| Configuração | Mínimo | Máximo | Desvio padrão | Valores únicos |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name in SETTING_COLUMNS:
        s = column_stats[name]
        settings.append(f"| {name} | {s['min']:.6g} | {s['max']:.6g} | {s['std']:.6g} | {s['unique_values']} |")
    correlations = [
        "| Par | Pearson agregado | Pearson centralizado por motor |",
        "| --- | ---: | ---: |",
    ]
    for pair in summary["strongest_correlation_pairs"][:6]:
        correlations.append(
            f"| {pair['left']} / {pair['right']} | {pair['pearson']:.3f} | "
            f"{pair['within_centered_pearson']:.3f} |"
        )
    motor_table = [
        "| Sensor | DP das médias dos motores | Mediana do DP dentro do motor |",
        "| --- | ---: | ---: |",
    ]
    for name in ("sensor_11", "sensor_14", "sensor_6"):
        s = column_stats[name]
        motor_table.append(
            f"| {name} | {s['std_between_unit_means']:.5g} | {s['median_within_unit_std']:.5g} |"
        )
    t = summary["training_targets"]
    strongest = sorted(summary["trend_candidates"],
                       key=lambda name: -abs(column_stats[name]["median_unit_spearman_age"]))[:5]
    candidates = summary["constant_sensors"] + summary["near_constant_sensors"]
    content = f"""# EDA do C-MAPSS FD001 e definição do problema

## Escopo e origem dos dados

Análise descritiva exclusivamente de `train.parquet`: **{summary['engines']} motores
e {summary['rows']} observações**. Não confundir esse treino interno com os 100
motores do treino original da NASA. Desenvolvimento significa treino + validação;
ambos recebem alvos separados, mas somente o treino entra em estatísticas,
figuras, heurísticas e candidatos de sensores.

Entradas: `data/processed/fd001/train.parquet`, `validation.parquet` (somente
validação de chaves e criação de alvos), `split_manifest.json` e
`configs/fd001_eda.toml`. Nenhum arquivo em `data/raw`, nenhum Parquet de teste
interno e nenhum teste oficial foi lido nesta execução. Os hashes de entradas,
versões e configuração estão em [summary.json](eda/summary.json).

Os Parquets originais são preservados. Os alvos ficam em
`data/processed/fd001/evaluation_targets/train_targets.parquet` e
`validation_targets.parquet`, acompanhados de `metadata.json`.

## Distribuição da duração

| Medida no treino interno | Ciclos |
| --- | ---: |
| Mínimo | {lifetime['min']:g} |
| Quartil 25% | {lifetime['25%']:g} |
| Mediana | {lifetime['50%']:g} |
| Média | {lifetime['mean']:.2f} |
| Quartil 75% | {lifetime['75%']:g} |
| Máximo | {lifetime['max']:g} |
| Desvio padrão | {lifetime['std']:.2f} |

Há durações heterogêneas entre motores. Observações de um mesmo motor são
dependentes; juntar todas as linhas dá mais peso a motores de vida longa.
A distribuição acima atribui uma observação a cada motor.

## Variância, sensores informativos e candidatos à remoção

{chr(10).join(table)}

Exatamente constantes: **{', '.join(summary['constant_sensors'])}**.
Quase constantes pela heurística exploratória: **{', '.join(summary['near_constant_sensors']) or 'nenhum'}**.
Critério de quase constância: até {eda['near_constant_max_unique']} valores e
fração dominante de pelo menos {eda['near_constant_dominant_fraction']:.0%}.
Esses critérios são configuráveis, escolhidos para triagem e não comprovam
irrelevância preditiva. Uma constante é identificada por um único valor;
variâncias residuais de arredondamento numérico são exibidas como zero.

Candidatos à remoção futura, **sem remoção nesta etapa**:
{', '.join(candidates)}. O `sensor_6` merece revisão separada: baixa amplitude e
concentração não excluem um evento raro informativo. A perda de desempenho
deverá ser investigada depois por ablação em partições por unidade internas
ao treino. Decisões de seleção continuam restritas ao treino; validação externa
fica reservada para avaliação e definição dos alertas.

Tendências associadas ao envelhecimento: {', '.join(summary['trend_candidates'])}.
Os cinco maiores valores absolutos de ρ mediano nesse grupo são:
{', '.join(strongest)}. São candidatos descritivos, não variáveis selecionadas
por desempenho. Nenhum modelo ou teste de significância foi ajustado.

Para cada sensor, calculou-se a correlação de Spearman entre valor e ciclo
**dentro de cada motor**, seguida de mediana e concordância de sinal entre
motores (peso igual por unidade). ρ é Pearson dos ranks. A triagem de tendência
usa |ρ mediano| ≥ {eda['trend_min_absolute_median_rho']:g} e concordância
≥ {eda['trend_min_direction_agreement']:.0%}. Correlação indefinida em unidades
constantes é excluída dessa mediana; a quantidade de unidades válidas está no JSON.
Sinal positivo indica crescimento com idade, sinal negativo queda.

Os sensores 9 e 14 têm tendências menos consistentes entre motores:
concordâncias de sinal de {column_stats['sensor_9']['direction_agreement']:.1%} e
{column_stats['sensor_14']['direction_agreement']:.1%}, respectivamente.
Ambos continuam disponíveis e não são candidatos à remoção por esse critério.
A média normalizada pode esconder unidades com trajetórias em sentido oposto.

## Configurações operacionais e escalas

{chr(10).join(settings)}

`setting_3` é constante nesta amostra de treino; as outras configurações têm
variação em torno dos valores registrados acima. Elas não foram removidas.
Não se infere capacidade de generalização para outros regimes operacionais
apenas deste subconjunto.

Os sensores têm escalas muito diferentes. Variância absoluta não mede
importância: um sensor na escala de milhares pode dominar distâncias, perdas
ou penalizações quando combinado com sensores de pequena amplitude.
Qualquer normalizador futuro deverá ser ajustado apenas no treino. A
padronização exibida nas curvas normalizadas é apenas visual e usa média e
desvio padrão do treino; não foi exportada como engenharia de atributos.

## Correlações e diferenças entre motores

{chr(10).join(correlations)}

Correlações altas sugerem redundância, mas podem refletir envelhecimento
compartilhado ou níveis diferentes entre motores; não estabelecem causalidade.
A segunda coluna de coeficientes retira a média de cada motor para mostrar
essa sensibilidade. Essa centralização usa toda a trajetória e é exclusivamente
retrospectiva. Sensores constantes são excluídos apenas das matrizes, pois sua
correlação é indefinida. As duas figuras abrangem todos os sensores variáveis.

{chr(10).join(motor_table)}

As diferenças de nível e dispersão entre motores coexistem com diferenças
de duração e estágio de degradação. Desvio entre médias não isola um efeito
causal do motor. Os gráficos brutos mostram motores de vida curta, mediana e
longa escolhidos deterministicamente no treino, sem usar resultados de teste.

## Evolução em função da vida normalizada

Para cada unidade, a vida normalizada é `(cycle - 1) / (T_i - 1)`.
Interpolação linear em {eda['normalized_life_points']} posições entre 0 e 1 permite calcular a
média entre motores, com **igual peso por motor**, e a faixa P10–P90.
A faixa mostra dispersão entre trajetórias, não intervalo de confiança.
Esse eixo revela tendências médias e dispersão que as trajetórias individuais
podem ocultar. Os trechos iniciais/finais dependem da composição desta amostra.
Nas curvas deste treino, o crescimento dos sensores 2, 4, 11 e 15 e a queda
dos sensores 7, 12, 20 e 21 se acentuam perto do término; isso é evidência
descritiva de envelhecimento, não demonstração de desempenho preditivo.

O ciclo terminal T_i é conhecido somente retrospectivamente. Vida normalizada,
interpolação com pontos futuros e médias por trajetória completa **não podem
entrar nos atributos de inferência**.

## Definição formal dos alvos e do risco

Para a unidade i observada no ciclo t, seja T_i o ciclo terminal de falha,
assumindo trajetória completa até a falha neste estudo de caso:

- `RUL(i,t) = T_i - t`, em ciclos, inteiro não negativo e sem truncamento.
- `failure_within_horizon(i,t) = 1[RUL(i,t) <= H]`.
- `failure_within_critical_horizon(i,t) = 1[RUL(i,t) <= H_critical]`.

Configuração atual: **H={h} ciclos** e **H_critical={critical} ciclos**.
Ambos são parâmetros experimentais configuráveis; **não são regras
industriais, limites de segurança nem thresholds de alerta**.

A fronteira é inclusiva: RUL=H é positivo, RUL=H+1 é negativo.
No ciclo terminal RUL=0, os dois alvos são verdadeiros; esse registro é
preservado para avaliação retrospectiva. `is_operational = (RUL > 0)` identifica
o subconjunto a usar para futuros alertas prospectivos. Incluir o ciclo da falha
em métricas de antecipação pode inflar artificialmente o desempenho.

No treino há {t['failure_positive']} positivos em {t['rows']} linhas para H={h}
({t['failure_positive']/t['rows']:.2%}) e {t['critical_positive']} para H={critical}
({t['critical_positive']/t['rows']:.2%}). Excluindo os ciclos terminais, há
{t['operational_failure_positive']} e {t['operational_critical_positive']}
positivos, respectivamente, em {t['operational_rows']} linhas operacionais.
Essas proporções evidenciam desbalanceamento de classes e dependência temporal.

O objetivo principal futuro é estimar
`p_H(i,t) = P(0 < T_i-t <= H | T_i > t, histórico disponível até t)`.
Isso é risco de falha em uma janela futura para um ativo ainda operacional,
não regressão de RUL, nem taxa instantânea de falha. RUL é preservado como
variável de avaliação para erro em ciclos, antecedência e estratificação.
O alvo binário conhecido retrospectivamente não é um escore predito.
Futuramente, o mesmo histórico deve satisfazer p_critical ≤ p_H; calibração
e coerência dos horizontes precisarão ser verificadas.

O máximo observado de uma sequência censurada não é uma falha. Esta função
de alvos exige confirmação explícita de trajetória completa; não deverá ser
aplicada ao teste oficial truncado, nem a ativos em serviço, sem tratamento de
censura ou referência de desfecho apropriada.

## Vazamento de informação e avaliação futura

- Alvos, RUL real, ciclo terminal, vida normalizada e `is_operational` ficam
  separados da telemetria; não são atributos de um futuro modelo.
- Seleção, remoção, estatísticas, correlações e normalização visual usam
  somente treino. Validação foi lida apenas para chaves e alvos.
- Teste interno e teste oficial permanecem reservados. Não escolher sensores,
  horizontes ou thresholds com base neles.
- Separar por motor; janelas do mesmo motor não podem atravessar partições.
- Filtros, janelas e atributos futuros só podem usar ciclos até t. Evitar
  janelas centradas, normalização por trajetória completa e suavização futura.
- `unit_id` é chave, não variável explicativa. `cycle` é conhecido no instante,
  mas pode induzir atalhos de idade que exigirão comparação e validação.
- H foi definido experimentalmente, sem otimização por resultado de teste.
  Repetir muitas decisões no mesmo conjunto de validação também pode gerar
  sobreajuste de desenvolvimento.

## Como será definido o alerta

| Nível futuro | Significado conceitual |
| --- | --- |
| normal | Monitoramento de rotina, sem evidência suficiente para escalada. |
| atenção | Evidência inicial ou incerta; acompanhar evolução e qualidade dos dados. |
| alerta | Risco no horizonte principal que justifique planejar inspeção ou manutenção. |
| crítico | Risco no horizonte curto que justifique priorizar avaliação/intervenção. |

Nenhum threshold definitivo, regra de score ou nível por observação foi criado.
Os níveis deverão usar probabilidades calibradas, incerteza, persistência
temporal, custo de alarmes e consequências da falha. Não confundir H com um
limiar numérico de probabilidade.

A definição futura será feita com métricas de validação: precisão/recall e
PR-AUC, calibração/Brier, falsos alarmes por motor ou exposição, cobertura de
falhas, antecedência em ciclos e utilidade/custos. Avaliar no nível de evento e
unidade, não apenas por linha. Somente após congelar essas escolhas será
permitida a avaliação final em teste. Os quatro níveis não são recomendações
industriais validadas.

## Figuras

"""
    titles = [
        "Distribuição da vida útil", "RUL ao longo do tempo",
        "Trajetórias representativas", "Variância e concentração",
        "Correlações", "Evolução média em vida normalizada",
        "Configurações operacionais", "Diferenças entre motores",
    ]
    for title, filename in zip(titles, figures):
        content += f"### {title}\n\n![{title}](eda/figures/{filename})\n\n"
    content += (
        "## Reprodução\n\n"
        "Executar na raiz: `.venv/Scripts/python.exe -m "
        "predictive_maintenance.application.eda_fd001`.\n"
        "Código reutilizável em `src/predictive_maintenance/analysis` e "
        "`data/targets.py`; nenhum modelo é treinado. "
        "Os horizontes são salvos junto aos alvos para evitar ambiguidade "
        "quando a configuração mudar.\n"
    )
    path.write_text(content, encoding="utf-8")
