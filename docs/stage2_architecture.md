# Arquitetura da Etapa 2

## Objetivo

Integrar reprodução local do NASA C-MAPSS FD001, contratos HTTP, persistência
e apresentação dos resultados congelados. C-MAPSS é um benchmark simulado;
este demonstrador não é um sistema aeronáutico real.

Status: **Stage 2 VALIDATED**. Evidências e limites em
`reports/stage2_validation.md`.

## Fluxo implementado

```text
Simulator -- POST /predict --> FastAPI :8000
                                  |
                                  v
                        LocalApplicationService
                                  |
                        artefatos congelados FD001
                                  |
                        resultado retornado à API
                                  |
                                  v
                     PostgreSQL :5432 (volume persistente)
                                  |
                         consulta pela FastAPI
                                  |
                  GET /predictions e GET /alerts
                                  |
                                  v
                         Streamlit :8501

Streamlit -- POST /scenario --> FastAPI --> LocalApplicationService
           cenário principal, separado do histórico persistido
```

O simulador envia seleções de unidade/ciclo, uma por ciclo em ordem crescente.
Não envia os valores dos sensores no payload. A API consulta a trajetória
congelada no serviço local, retorna a linha selecionada e registra evento,
previsão e alerta quando aplicável.

O dashboard consulta `/health`, `/api/v1/options` e `/api/v1/scenario`.
O cenário vem do serviço local. A seção Operational history consulta
`/api/v1/predictions` e `/api/v1/alerts` com unidade, horizonte e limite.
Mostra registros persistidos, sem cálculo de risco ou acesso direto ao banco.
Erro histórico é explícito e mantém o cenário principal utilizável; não existe
fallback automático para o backend local.

## Responsabilidades

| Componente | Responsabilidade |
| --- | --- |
| Simulator | Sequência de ciclos de uma unidade e envio HTTP; sem cálculo de risco ou alerta |
| FastAPI | Validação, delegação, serialização, persistência e consulta histórica |
| LocalApplicationService | Fonte comum da lógica de aplicação: risco, sobrevivência, health visual, alerta, validade e staleness; utiliza artefatos congelados |
| PostgreSQL | Armazenamento de telemetry_events, predictions e alerts; sem cálculo científico |
| Streamlit | Controles, cenários e histórico persistido exclusivamente pela API no modo API; sem fallback local automático |
| Docker Compose | Orquestração de banco, API, dashboard e simulador opcional |

API, dashboard e simulador usam a mesma definição de imagem Python 3.11.
O Dockerfile inclui validation e artefatos para replay; não inclui arquivos
brutos oficiais ou test_internal.

## Portas e variáveis de ambiente

| Serviço | Porta local | Endereço |
| --- | ---: | --- |
| PostgreSQL | 5432 | db:5432 na rede Compose |
| FastAPI | 8000 | http://localhost:8000/docs |
| Streamlit | 8501 | http://localhost:8501 |

- `DATABASE_URL`: habilita persistência na API. Ausente significa modo local
  explicitamente sem persistência.
- `PREDICTIVE_MAINTENANCE_PROJECT_ROOT=/app`: raiz dos artefatos/configs na API.
- `APP_BACKEND=api`: backend do dashboard no Compose; local é alternativa
  explícita de desenvolvimento.
- `PREDICTIVE_MAINTENANCE_API_URL=http://api:8000`: destino interno do dashboard.
- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`: configuração do banco;
  o Compose usa defaults de desenvolvimento.
- Volume `predictive_maintenance_db`: dados PostgreSQL; parada normal não o remove.

Os endpoints históricos filtram unit_id, horizon e limit (até 200).
Seleção por modelo é feita no consumidor usando model_name. A identidade de
previsão inclui modelo, versão, política e cadência; configurações diferentes
podem ter legitimamente o mesmo ciclo. Alertas não armazenam modelo, versão,
política ou cadência, limitando sua atribuição a uma configuração específica.

## Controle local no PowerShell

```powershell
.\scripts\local_stack.ps1 start
.\scripts\local_stack.ps1 status
.\scripts\local_stack.ps1 logs
.\scripts\local_stack.ps1 stop
.\scripts\local_stack.ps1 rebuild
```

start usa up -d; rebuild usa up --build -d; stop usa down.
O script resolve Compose pela própria localização, com -f e
--project-directory explícitos. Não apaga imagens ou volumes.

## Limitações

- A aplicação reproduz cenários congelados, não telemetria física em streaming.
- O cenário principal pode conter ciclos ainda não enviados pelo simulador;
  somente Operational history representa os registros persistidos do replay.
- O histórico é limitado e alerts não identificam modelo/configuração completos.
- Este host Codex não acessa Docker Desktop do usuário. Testes com SQLite
  e transportes controlados não comprovam o ciclo de vida do volume real.
- Os PASS reais Windows de replay e retenção após restart são evidências
  fornecidas pelo usuário, consolidadas em reports/stage2_validation.md.
