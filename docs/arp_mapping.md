# Referências conceituais de organização da engenharia

Usamos SAE ARP4754B e SAE ARP4761A **somente como referências conceituais**.
Este demonstrador não declara conformidade, certificação, equivalência de
processos ou aprovação de práticas. O mapeamento abaixo é uma adaptação própria
do projeto, não reprodução de cláusulas, checklist normativo ou avaliação formal.

As descrições públicas oficiais distinguem desenvolvimento de sistemas e
avaliação de segurança. Foram consultadas em 2026-09-07:

- [SAE ARP4754B, revisão de dezembro de 2023](https://saemobilus.sae.org/standards/arp4754b-guidelines-development-civil-aircraft-systems).
- [SAE ARP4761A, revisão de dezembro de 2023](https://saemobilus.sae.org/standards/arp4761a-guidelines-conducting-safety-assessment-process-civil-aircraft-systems-equipment).

A consulta cobriu as descrições públicas, não o conteúdo integral licenciado.
Não atribuímos requisitos, procedimentos ou números de cláusulas a esses textos.

## Conceitos adotados e tradução local

| Conceito | Uso no demonstrador | Artefato/evidência |
| --- | --- | --- |
| requirements capture | Traduzir o objetivo em requisitos identificáveis. | safety_requirements.md |
| requirements validation | Questionar se cada requisito é correto e suficientemente completo para o objetivo. | rationale e validation_method; hipóteses abertas |
| verification | Determinar se a implementação satisfaz o requisito especificado. | testes e verification_evidence |
| traceability | Relacionar origem, requisito, implementação e evidência. | traceability_matrix.csv |
| assumption management | Registrar hipótese, fundamento, impacto e estado. | safety_assumptions.md |
| configuration management | Identificar código, dados, configuração e artefatos por versão/hash. | pyproject, changelog, manifestos existentes; modelos futuros |
| change impact analysis | Avaliar alterações antes de reutilizar evidências. | change_impact_template.md |
| problem reporting | Registrar desvios observados e controles pendentes. | hazard_log.md, relatórios de auditoria |
| reliability analysis | Separar evento, horizonte, população, censura e incerteza. | prediction_contract.md; análise estatística futura |
| monitoring | Prever verificações de entrada, disponibilidade e atualidade. | SRQ006, SRQ007, SRQ017; monitor online não implementado |
| failure mode analysis | Raciocinar sobre modos internos como erro de entrada ou escore indisponível. | predictive_function_fmea.md e hazard_log.md, sem FMEA formal |
| logical failure propagation | Descrever cadeias entrada inválida → atributo incorreto → risco distorcido → alerta simulado inadequado. | scope e hazard_log; sem árvores formais |
| common cause awareness | Reconhecer que modelos podem compartilhar dados, features, rótulos e bugs. | model_common_dependencies.md e model cards clássicos |
| independence awareness | Não inferir independência de diversidade de algoritmo ou de vários testes escritos pelo mesmo autor. | model_common_dependencies.md e limitações de evidência |
| maintenance related reasoning | Relacionar risco/antecedência/falsos alertas a uma decisão simulada futura. | problem_definition.md; sem instrução operacional real |

Os conceitos de desenvolvimento motivam a organização de requisitos; os
conceitos de avaliação de segurança motivam o registro de estados indesejados.
Essa divisão é organizacional, não uma alocação normativa. Monitoring aqui
significa observação interna do demonstrador: não execução de processo de
avaliação de segurança em serviço previsto em outra prática.

## Validação não é verificação

**Validação** determina se o requisito está correto e suficientemente completo
para o objetivo do demonstrador. Exemplo: questionar se 30 ciclos e as métricas
previstas são adequados à decisão simulada. A adequação de H continua aberta.

**Verificação** determina se a implementação satisfaz o requisito especificado.
Exemplo: testar a fronteira inclusiva RUL=H e a presença de H na saída.
Testes aprovados não demonstram a adequação do horizonte nem calibração.

As evidências desta etapa são revisão interna de coerência e testes de software.
Não há revisão independente, validação operacional ou aprovação regulatória.

## Fora do escopo

Certificação; compliance claim; AFHA formal; PASA formal; SFHA formal; PSSA
formal; SSA formal; ASA formal; FDAL; IDAL; CMR; MMEL; TLD; safety objectives
regulatórios; probability budgets de certificação; classificação regulatória
de severidade. Não se executou nenhum desses processos nem se atribuiu qualquer
uma dessas classificações. Nomes internos SRQ/HAZ não criam equivalência com
requisitos ou failure conditions de uma aeronave.
