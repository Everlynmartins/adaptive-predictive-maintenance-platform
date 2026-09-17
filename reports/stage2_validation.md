# Validação de integração da Etapa 2

Data do fechamento: 2026-09-16. Status final: **Stage 2 VALIDATED**.

Fechamento da arquitetura local do demonstrador de engenharia no benchmark
simulado C-MAPSS FD001. As evidências Windows abaixo foram fornecidas pelo
usuário; os testes Python e as verificações estáticas foram executados neste
host. Nenhum teste Docker real foi repetido no ambiente Codex.

## Evidência repetida nesta auditoria

Comando executado no ambiente Python local, sem Docker:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_api.py tests/test_api_persistence.py tests/test_api_client.py tests/test_simulator.py tests/test_streamlit_application.py tests/test_stage2_integration.py tests/test_project_root.py -q -p no:cacheprovider
```

Resultado no fechamento: **30 passed**, dois warnings externos de depreciação
Starlette/TestClient e AnyIO, em 23,66 s. Somente testes de integração/aplicação
foram executados; nenhum treinamento ou processamento científico foi iniciado.

| Teste / componente | Resultado observado | Limite da evidência |
| --- | --- | --- |
| FastAPI /health e /api/v1/options | HTTP 200 e opções válidas | TestClient local |
| Replay Simulator → API → serviço local → persistência | Unidade 1, H30, fusion/full/each_cycle; três ciclos finais consecutivos enviados; previsões e alertas consultados em ordem | Artefatos existentes; SQLite em memória |
| /api/v1/predict, /units/1 e /units/1/trajectory | Respostas acessíveis pelo contrato | TestClient local |
| /api/v1/predictions e /api/v1/alerts | Registros persistidos e recuperados | SQLite em memória |
| Dashboard em backend API | AppTest renderizou cenário recebido pelo cliente HTTP e mostrou Risk score sem exceção | TestClient, não navegador/container do usuário |
| Histórico operacional do dashboard (22E) | Cliente consultou predictions/alerts; AppTest apresentou a seção de previsões persistidas | Transporte HTTP de teste; SQLite em memória |
| Histórico indisponível | Erro Operational history unavailable; cenário principal e Risk score continuam apresentados | Falha controlada; nenhum fallback local |
| Payload incompleto, modelo/horizonte inválido | HTTP 422 | Falhas controladas locais |
| Unidade inexistente | HTTP 404 | Falha controlada local |
| Previsão indisponível esperada | HTTP 200, prediction_status=unavailable e risco nulo | Status preservado |
| API indisponível para dashboard | Cliente lançou erro; AppTest exibiu Application unavailable e nenhum score | Indisponibilidade simulada |
| Recuperação do cliente da API | Consulta voltou a funcionar mantendo status e validade | Transporte simulado |
| Banco indisponível na gravação / health | HTTP 503 sem score fabricado | Repository controlado, não interrupção de PostgreSQL real |
| Recuperação do banco | Registros anteriores mantidos; nova gravação recuperada | SQLite em memória |
| Requisição repetida | Sem nova previsão/alerta duplicado; outro horizonte como identidade legítima | SQLite, sem concorrência |
| Root / configuração ausente | Root local correto e erro explícito | Testes de configuração |

Também executado tests/test_local_stack.ps1: **PASS** para os seis comandos
com Docker substituído por função de teste. Confirmados root correto quando
chamado de outro diretório, flags explícitas do Compose, start sem build
e ausência de remoção de volume. Nenhum comando foi enviado a Docker real.

Parser PowerShell: sintaxe válida em local_stack.ps1, stage2_e2e_test.ps1
e stage2_persistence_test.ps1.

## Evidência Windows fornecida pelo usuário

O usuário forneceu os seguintes resultados reais no Windows local:

| Item | Resultado informado |
| --- | --- |
| Unidade / configuração | 1 / H30 / fusion / full / each_cycle |
| Ciclos enviados | 40 |
| Predictions encontradas pela API | 40 |
| Alerts encontrados pela API | 3 |
| Health | available |
| Serviços | PostgreSQL, FastAPI e dashboard healthy |
| Prediction status durante o replay (22A) | Válido; replay PASS |
| Predictions API / DB (22B) | 40 / 40 |
| Alerts API / DB (22B) | 3 / 3 |
| Ciclos conferidos (22B) | 1 a 40 |
| Persistência após restart normal (22B) | PASS |
| Duplicações inesperadas (22B) | 0; validação PASS |
| Dashboard (22C) | APP_BACKEND=api; URL interna http://api:8000 |
| Indisponibilidade da API (22C) | Erro explícito; sem fallback local silencioso; testes relacionados aprovados |

Essa evidência externa não foi reexecutada neste host. O PASS do 22B confirma
retenção no PostgreSQL real e recuperação após restart normal para o replay
informado. O 22E acrescentou o consumo de histórico exclusivamente por FastAPI:
seus nove testes focados passaram na implementação, e todos integram a suíte
de 30 testes aprovada novamente neste fechamento.

## Verificação da arquitetura

- LocalApplicationService permanece a fonte comum da lógica da aplicação.
  API delega ao serviço; Streamlit em modo API solicita e apresenta cenários.
  Não foi encontrado recálculo de risco, health ou staleness nesses adaptadores.
  O mapeamento de alertas em números é apenas visual.
- O simulador envia ciclos sequenciais e não envia sensores futuros ou alvos
  no payload. Consulta metadados e solicita o ciclo corrente; não calcula previsão.
- PostgreSQL armazena/consulta resultados; Compose orquestra serviços.
- Dashboard usa APP_BACKEND=api e URL http://api:8000.
- Dashboard consulta /api/v1/scenario para o cenário e /api/v1/predictions
  e /api/v1/alerts para Operational history. Os registros históricos chegam
  pelo cliente HTTP; não são reconstruídos nem recalculados pela interface.
  Streamlit não acessa PostgreSQL diretamente.
- Nenhum threshold, métrica congelada, modelo ou artefato científico foi editado.

## Problemas encontrados e ação

1. local_stack.ps1 subia dois diretórios e podia procurar Compose fora da raiz.
   Corrigido para o pai de PSScriptRoot e chamadas com arquivo/project-directory
   explícitos. Verificação: teste PowerShell com Docker simulado.
2. Dashboard ainda não consumia o histórico PostgreSQL. Resolvido no 22E com
   cliente HTTP e seção Operational history, tabela, gráfico de risco persistido
   e alerts. Erros da consulta são explícitos e não acionam fallback científico.

## Resolução das pendências e fechamento

| Pendência anterior | Resolução / evidência |
| --- | --- |
| Retenção PostgreSQL e comparação API/DB | 22B Windows: 40 predictions e 3 alerts em ambos, ciclos 1–40, zero duplicações |
| Recuperação após restart | 22B Windows: PASS após restart normal |
| Histórico disponível ao dashboard | 22E: implementação HTTP, testes do cliente e AppTest de integração aprovados |
| Ausência de fallback científico silencioso | 22C fornecido; testes de timeout, indisponibilidade da API e histórico aprovados |
| Fonte única e separação de responsabilidades | Arquitetura auditada anteriormente preservada; 22E somente consulta/apresenta registros persistidos |

Não restam bloqueadores funcionais no escopo definido da Stage 2.

## Limitações preservadas

- Consultas históricas são limitadas a 200 registros, sem paginação; o dashboard
  solicita 100 registros e filtra o modelo no retorno. Não é uma visão ilimitada
  nem um novo Live Operations Dashboard.
- Alerts não possuem identidade completa de modelo/configuração; sua consulta
  e apresentação são por unidade e horizonte, sem atribuição inventada.
- O script de persistência foi validado para a base pequena informada. Sua
  comparação por ciclo/modelo exige cuidado em bases com múltiplas versões,
  políticas ou cadências. O PASS fornecido não é generalizado a outros cenários.
- Falhas do banco foram exercitadas de forma controlada nos testes locais;
  não se afirma uma interrupção real do container PostgreSQL neste host.
- A integração 22E foi validada por testes de cliente e AppTest, sem inspeção
  de navegador Docker neste host. Ausência de Docker aqui não invalida a
  evidência real Windows fornecida.
- C-MAPSS é benchmark simulado; o fechamento é de integração local e não
  demonstra adequação para manutenção real ou segurança operacional.

**Stage 2 VALIDATED**, pronta para seguir para Stage 3. Nenhuma funcionalidade
da Stage 3 foi implementada neste fechamento.
