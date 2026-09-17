# Avaliação de impacto de mudança

Usar antes de aceitar alterações relevantes em modelo, feature, threshold,
política de telemetria/filtragem, contrato de dados ou dependência. Manter o
registro preenchido associado à mudança; não reutilizar evidência invalidada.
Este template não constitui processo de certificação ou aprovação regulatória.

## Identidade e motivo

- change_id:
- data, autor e responsável pela revisão:
- categoria e problema que motiva a mudança:
- versão/hash anterior e proposta (código, configuração e artefatos):
- comportamento anterior e esperado; critérios de aceitação:

## Impactos obrigatórios

| Aspecto | IDs/artefatos afetados e análise (justificar se não aplicável) |
| --- | --- |
| Requisitos afetados | SRQ; necessidade de novo requisito ou revisão de statement. |
| Hipóteses afetadas | ASM; evidência nova e transição open/confirmed/invalidated. |
| Estados indesejados | HAZ; causas novas ou controles enfraquecidos. |
| Métricas afetadas | Calibração, discriminação, disponibilidade, falsos alertas, antecedência, latência. |
| Testes de regressão necessários | IDs, população, fronteiras, causalidade por prefixo, segregação por unidade. |
| Artefatos a regenerar | Features, rótulos, modelos, calibração, thresholds, relatórios, manifestos e hashes. |
| Interpretação de resultados | Evento, horizonte, escala, censura, população, comparabilidade antes/depois. |
| Dados e partições | Preservação dos holdouts; justificar alteração sem usar resultados de teste para ajustar decisões. |
| Dependências e reprodutibilidade | Versões, compatibilidade, seed, ambiente e resultados reproduzidos. |
| Causas compartilhadas/independência | Componentes que compartilham dados, código ou pressupostos. |

## Validação do requisito e verificação da implementação

- Validação: o requisito continua correto e suficientemente completo para o
  objetivo? Registrar raciocínio, evidência e pendências, sem confundir com testes.
- Verificação: a implementação satisfaz o requisito especificado? Registrar
  comandos, resultados, versões e testes executados, incluindo falhas.
- Evidências anteriores ainda válidas / invalidadas (justificar):
- Regeneração necessária executada e vínculos dos novos artefatos:
- Matriz de rastreabilidade e hazard log atualizados:
- Resultado da revisão interna, pendências, responsável e condição para uso:
- Estratégia de reversão para artefatos anteriores compatíveis:

Modelo, thresholds e política só poderão ser usados após a revisão de adequação
e verificações pertinentes. Test_internal permanece para avaliação após congelar
decisões; teste oficial segue sua etapa autorizada própria. Registro incompleto
significa impacto ainda não avaliado, não aprovação implícita.
