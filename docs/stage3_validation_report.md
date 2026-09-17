# Stage 3 AWS — relatório de validação final

**Status: Stage 3 AWS: VALIDATED — LAB.**

Data da auditoria local: **2026-09-17**. Versão do projeto: **0.16.0**.
Stage 1 e Stage 2 permanecem VALIDATED. Este fechamento limita-se à integração
AWS de um engineering demonstrator do benchmark simulado C-MAPSS FD001.

## Escopo e origem das evidências

A auditoria revisou Terraform, scripts AWS, Dockerfile/Compose como referência,
adaptadores API/dashboard/simulador, persistência e documentação operacional.
Não repetiu análise científica, treinamento, calibração, seleção de thresholds
ou geração de artefatos. Não alterou o Terraform aplicado ou recursos AWS.

Há duas fontes distintas de evidência:

- **Real, fornecida pelo usuário no Prompt 23I:** infraestrutura operacional,
  E2E cloud PASS, recovery ECS PASS e histórico confirmado visualmente no
  dashboard AWS. As datas dessas execuções não foram fornecidas; não se assume
  que ocorreram na data desta auditoria.
- **Local, executada pelo Codex:** inspeção de código/configuração, parser
  Windows PowerShell 5.1 e testes de scripts com mocks, API, persistência SQLite,
  simulador e integração do dashboard. Não houve chamadas AWS reais, Docker,
  consulta direta ao RDS ou inspeção independente do estado remoto nesta sessão.

## Arquitetura validada

```text
Simulador local Windows — requisições HTTP sequenciais da unidade FD001
    |
    v  HTTP :8000, origem limitada ao IPv4 /32 do operador
ECS Fargate — uma task, dois containers, mesma imagem ECR versionada
    +-- FastAPI --> LocalApplicationService --> artefatos científicos congelados
    |      |
    |      +-- PostgreSQL/TLS :5432 --> RDS privado Single-AZ
    |      <--------- consulta do histórico persistido --------+
    +-- Streamlit :8501 --> FastAPI http://127.0.0.1:8000
                   Operational history: predictions / alerts

RDS/Secrets Manager --> injeção ECS de username/password na API
CloudWatch Logs     <-- logs separados de API/dashboard
Terraform           --> infraestrutura; scripts locais --> operação pelo usuário
```

O simulador envia seleções de `unit_id`, ciclo e cenário ao endpoint existente;
não é ingestão de sensores de equipamento real. O serviço reutiliza os
resultados/artefatos offline já congelados. O avanço das requisições é sequencial
e não consulta observações futuras no simulador. Esta etapa não demonstra uma
nova capacidade de inferência sobre telemetria industrial arbitrária.

## Infraestrutura e controles auditados

| Item | Configuração observada no código | Referência |
| --- | --- | --- |
| ECR | Um repository, mesma tag `stage3-lab-v1` para API/dashboard; tags versionadas imutáveis, exceção `latest`; scan on push; retenção de dez manifests | `infra/aws/ecr.tf`, `variables.tf`, `ecs.tf` |
| ECS | Fargate/awsvpc/Linux x86_64; uma task quando explicitamente ativada; default desired count 0; default 1 vCPU/4 GiB; sem autoscaling | `infra/aws/ecs.tf`, `variables.tf` |
| Rede compute | Uma subnet pública, assign public IP true; ingresso TCP 8000/8501 somente do operator IPv4 /32 | `networking.tf`, `security_groups.tf`, `variables.tf` |
| RDS | PostgreSQL 16.13 configurável; default db.t4g.micro/20 GiB gp3; private subnet group; publicly_accessible false; storage_encrypted true; multi_az false | `infra/aws/rds.tf`, `variables.tf` |
| Rede DB | TCP 5432 somente do SG aplicação; nenhuma regra pública 5432; duas subnets privadas sem rota default à internet | `security_groups.tf`, `networking.tf` |
| Descarte LAB | deletion_protection false, skip_final_snapshot true, backup um dia; sem replica, proxy ou monitoramento adicional pago | `infra/aws/rds.tf` |
| Credenciais | manage_master_user_password true; secret gerenciado RDS; injeção somente de campos username/password; nenhuma senha em task definition/output | `rds.tf`, `secrets.tf`, `ecs.tf`, `outputs.tf` |
| IAM | Execution role separada da task role; GetSecretValue somente no ARN gerenciado; pull no ECR específico; escrita em dois log groups; task role sem permissões AWS adicionais | `infra/aws/iam.tf`, `secrets.tf` |
| Conexão DB | Bootstrap monta DATABASE_URL em memória com SQLAlchemy URL e escaping; TLS verify-full com CA pública regional; erro de startup explícito, sem downgrade | `infra/aws/runtime/api_bootstrap.py` |
| Dashboard | APP_BACKEND api; API loopback dentro da task; sem acesso direto ao banco ou fallback local automático | `ecs.tf`, `ui/api_client.py`, `ui/streamlit_app.py` |
| Health/logs | Checks Python de API/Streamlit; dashboard depende de API HEALTHY; awslogs em grupos separados, retenção sete dias | `infra/aws/ecs.tf` |
| Exclusões LAB | Nenhum NAT Gateway, ALB, EIP, service discovery, Kubernetes ou serviço adicional | Recursos declarados em `infra/aws/*.tf` |

Estas linhas descrevem o Terraform e o código auditados. A evidência remota
fornecida confirma funcionamento integrado, sem substituir uma comparação
independente de cada atributo remoto ou uma análise de drift, que não ocorreu.
Os wildcards IAM existentes têm escopo explicado: autenticação ECR requer
Resource `*`; logs restringem streams aos dois grupos; trust ECS restringe
conta/região. Não há AdministratorAccess ou `secretsmanager:*`.

A varredura estática de **28 arquivos de implantação** não encontrou literais
de access keys AWS ou valores de secret access key/session token nos padrões
verificados. State, tfvars e plans locais estão ignorados pelo Git e agora
também pelo contexto Docker. Não foram abertos state/credenciais locais. Os
defaults de senha do Compose são exclusivamente valores fictícios de
desenvolvimento, não usados no ECS. Essa inspeção não é uma garantia universal
de ausência de segredo em qualquer arquivo externo ou log futuro.

## E2E cloud e persistência — evidência real do operador

| Campo | Resultado fornecido |
| --- | --- |
| unit_id / horizon | 1 / 30 |
| model / telemetry_policy / cadence | fusion / full / each_cycle |
| Ciclos enviados | 40 |
| Predictions persistidas e recuperadas | 40 |
| Alerts persistidos e recuperados | 3 |
| prediction_status | valid para as 40 predictions |
| ECS / API / dashboard | RUNNING / HEALTHY / HEALTHY |
| Persistence through cloud API | PASS |
| E2E result | PASS |
| Operational history | Registros confirmados visualmente pelo usuário no Streamlit AWS |

Os endpoints exercitados pelo fluxo são `/health`, `/api/v1/options`,
`/api/v1/units/{unit_id}`, `POST /api/v1/predict`,
`GET /api/v1/predictions` e `GET /api/v1/alerts`. O dashboard consulta também
`POST /api/v1/scenario` para a visualização do cenário existente.
Persistência foi comprovada pela API cloud configurada para RDS privado,
complementada pela preservação dos registros após substituição da task.
Não se afirma que houve SQL direto do Windows ao RDS.

## Recovery — evidência real do operador

A task original foi interrompida via ECS stop-task; desired count permaneceu
1. O scheduler criou automaticamente uma task diferente. Seu endpoint foi
redescoberto e os mesmos registros foram recuperados pela API.

| Verificação | Resultado fornecido |
| --- | --- |
| Original task | STOPPED |
| Replacement task | RUNNING |
| API / dashboard | HEALTHY / HEALTHY |
| Endpoint rediscovered | PASS |
| Predictions before / after | 40 / 40 |
| Alerts before / after | 3 / 3 |
| Persistent records preserved | PASS |
| Recovery / result | PASS / PASS |

Isso demonstra preservação do estado persistente fora da task efêmera no
cenário testado. Não demonstra alta disponibilidade, disaster recovery,
recuperação do banco, recuperação regional ou ausência de interrupção.

## Separação de responsabilidades e operações

- Simulador: produz requisições em ciclos crescentes, sem cálculo de risco.
- FastAPI: valida seleções, chama LocalApplicationService, serializa o resultado
  e solicita persistência; não recalcula probabilidades, health ou thresholds.
- LocalApplicationService/componentes científicos existentes: fonte da lógica
  científica e dos estados semânticos já estabelecidos.
- SQLAlchemy/PostgreSQL: grava e consulta resultados. Falha configurada de DB
  retorna erro explícito 503, sem gerar um score substituto.
- Streamlit: apresenta respostas API e histórico persistido. O mapeamento de
  níveis para números no gráfico é apresentação, não seleção de thresholds.
- Docker/Terraform: embalagem e infraestrutura; não executam treinamento.

Os scripts resolvem a raiz por PSScriptRoot, perfil/região configurados e
identificadores pelos outputs Terraform/ECS/ENI. E2E/recovery rejeitam endpoints
loopback e não usam localhost como fallback. As leituras históricas usam somente
os filtros suportados (`unit_id`, `horizon`, `limit`). Alerts não têm modelo,
versão, política ou cadência: os validators comparam unidade/ciclo/horizonte e
risco numérico, sem usar texto localizado como identidade.

Os waiters de recovery têm timeout explícito; E2E limita processo do simulador
a 600 s e retries históricos a três leituras. Warnings nativos não equivalem
automaticamente a falha: wrappers e login corrigido verificam exit code.
`aws_lab.ps1` só aplica localmente um plan inspecionado que altera desired count;
recusa outras mudanças. Recovery é uma ação controlada e interrompe uma task
somente quando o usuário executa esse script. Nenhum deles foi executado contra
AWS nesta auditoria. Start/stop ECS não inicia nem para RDS automaticamente.

## Observabilidade

Há grupos CloudWatch separados para API/dashboard e script somente leitura
`aws_stage3_logs.ps1 api|dashboard|both`, com janela/volume limitados e redação
de padrões conhecidos de credenciais. Configuração CloudWatch operacional foi
fornecida pelo usuário; o teste local verificou consulta mockada e redação.
Não se inventam consultas reais, alarmes, valores de latência/memória ou
conteúdos de logs não fornecidos. A redação é defesa adicional, não substitui
a proibição de imprimir secrets no runtime.

## Matriz de requisito de integração / evidência / status

Identificadores abaixo organizam esta auditoria; não são requisitos regulatórios.

| Requirement | Evidence | Status |
| --- | --- | --- |
| S3-INT01: Executar API/dashboard na mesma imagem, separados | ecs.tf; test_ecs_scripts.py; task real HEALTHY fornecida | PASS |
| S3-NET01: RDS privado e 5432 somente da aplicação | rds.tf/networking.tf/security_groups.tf; RDS privado operacional informado | PASS — configuração auditada + evidência do operador |
| S3-SEC01: Credencial RDS gerenciada, injeção específica, sem segredo no código de implantação | IAM/secrets/bootstrap; scan estático; test_ecs_api_bootstrap.py | PASS |
| S3-E2E01: Replay sequencial cloud produz e persiste resultados existentes | E2E real 40/40/3; test_aws_stage3_scripts.py; test_simulator.py | PASS |
| S3-PER01: Recuperar registros persistidos pela API cloud | E2E/recovery real; test_api_persistence.py; test_api.py | PASS |
| S3-UI01: Dashboard obtém histórico exclusivamente pela API | Confirmação visual cloud; test_api_client.py; test_stage2_integration.py | PASS |
| S3-REC01: Substituição da task preserva registros e redescobre endpoint | Recovery real 40/3 antes/depois; test_aws_stage3_recovery.py | PASS |
| S3-ERR01: Falhas retornam erro/status explícito sem fallback silencioso | Testes de API/DB indisponíveis, entradas inválidas e mocks E2E/recovery | PASS — falhas locais/mocks; não se afirma outage real do RDS |
| S3-OBS01: Logs separados e diagnóstico limitado sem consultar secrets | ecs.tf/iam.tf; test_aws_stage3_scripts.py (logs/redação) | PASS — configuração e mocks |
| S3-OPS01: Operação local limitada, caminhos dinâmicos e custo explícito | aws_lab/endpoint/check; tests ECS/audit; planos lifecycle/custo | PASS |
| S3-SCI01: Reutilizar ciência congelada sem recalcular nos adaptadores | Inspeção API/UI/simulador/service; preservação dos arquivos protegidos | PASS |

## Testes executados nesta auditoria

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_stage3_audit.py tests/test_aws_stage3_scripts.py tests/test_aws_stage3_recovery.py tests/test_ecs_scripts.py tests/test_ecs_api_bootstrap.py tests/test_api.py tests/test_api_persistence.py tests/test_api_client.py tests/test_simulator.py tests/test_stage2_integration.py -q
```

**84 passed, 2 warnings, 38,82 s**, no Python **3.11.16**. Nenhum teste skipped.
Scripts AWS/Docker/Terraform nos testes são mocks, não chamadas reais. TestClient
exercita adaptadores e artefatos congelados existentes; SQLite testa persistência
local. Não houve treinamento, avaliação científica nova ou geração de artefatos.

Parser **Windows PowerShell 5.1.26100.9444**: **12 scripts auditados,
zero erros de sintaxe** (`aws*.ps1` e `terraform_plan.ps1`). Testes com mocks
também executaram PowerShell 5.1. Hashes SHA-256 de **25 arquivos protegidos**
(Terraform `.tf`, Dockerfile/Compose, bootstrap, API, UI, simulador e
LocalApplicationService) permaneceram iguais entre a inspeção e o fechamento.
Terraform fmt/validate anteriores estão
registrados no CHANGELOG; não se executou init/plan/apply/destroy nesta sessão
nem se formataram os arquivos Terraform aplicados.

## Achados e resoluções

| ID | Severidade | Achado real | Resolução / evidência |
| --- | --- | --- | --- |
| S3-A01 | MINOR | aws_ecr_check mantinha o pipeline PowerShell de senha que já havia falhado no Windows e sido corrigido no push | Login via cmd.exe/pipeline nativo, sem token em variável/arquivo; warning não causa falha isoladamente; test_stage3_audit.py testa sucesso e exit code não zero |
| S3-A02 | MINOR | aws_check consultava região do perfil antes das variáveis e podia interromper antes do fallback quando o perfil não possuía região | Prioridade AWS_REGION/AWS_DEFAULT_REGION; consulta perfil somente se necessário; quatro testes mockados de região/falha explícita |
| S3-A03 | MINOR | .dockerignore não excluía state/plans/tfvars locais Terraform e arquivos .env do contexto de build | Exclusões explícitas; teste local. Dockerfile já copiava somente arquivos selecionados; não foi observada inclusão de segredo na imagem publicada |
| S3-A04 | MINOR | Documentação corrente ainda dizia execução ECS/cloud pendente apesar dos PASS reais fornecidos | Status e origem das evidências atualizados; nomes de tags alinhados aos nomes declarados. Sem mudança de Terraform |
| S3-A05 | INFORMATIONAL | Dois warnings de depreciação Starlette/httpx e alias BlockingPortal/anyio na suíte | Registrados; 84 testes passaram. Nenhuma dependência alterada apenas para ocultá-los |

**BLOCKER: 0. MAJOR: 0. MINOR: 4, todos corrigidos localmente.
INFORMATIONAL: 1, sem bloqueio.** Os riscos LAB abaixo são limites conhecidos
da arquitetura aprovada, não novas exigências para fechar esta etapa.

## Custos qualitativos, riscos conhecidos e limitações

- Uma task Fargate/IPv4 público ativo cobra compute/IP; desired count zero
  interrompe tasks, não todos os custos. RDS, storage, backups, ECR, secrets e
  logs têm custo próprio. Não se mediu gasto real nem se revalidaram preços.
- Uma task, RDS Single-AZ, IP dinâmico, HTTP externo sem autenticação/TLS,
  restrito ao operator /32. Apenas dados simulados; não exposição pública
  permanente, workload industrial ou informação sensível.
- O usuário master do RDS é usado no LAB isolado; privilégios elevados são
  limitação. Nenhum novo usuário/serviço foi criado na auditoria.
- Sem deletion protection/snapshot final: destruir o RDS pode apagar registros.
  Destruição e verificação de cobrança residual são procedimentos documentados,
  não resultados observados neste fechamento.
- CA pública é baixada em cada startup; indisponibilidade impede startup
  explicitamente. Rotação do secret exige substituição controlada de tasks.
- A política ECR de dez manifests não protege eternamente uma tag em uso:
  futuras publicações podem expirar versões antigas. Conferir a imagem ativa
  antes de publicar/remover versões; não se alterou essa política aplicada.
- Histórico está limitado a 200 registros na API, ordenados por unidade/ciclo,
  sem paginação; dashboard pede 100. O replay de 40 ciclos cabe nessa janela.
  Alerts não identificam modelo/política; não se promete atribuição exclusiva
  entre cenários concorrentes. A persistência reutiliza identidades existentes
  em replays repetidos; não é um registro independente de cada execução.
- Default 1 vCPU/4 GiB é dimensionamento inicial; pico, latência e capacidade
  máxima não foram medidos nesta auditoria. Não houve novo build ou alteração
  da imagem já publicada. A base Python/dependências usam faixas; promover a
  imagem validada por tag/digest evita equiparar rebuild a reprodução bit a bit.
- Testes de falha API/DB locais e mocks não equivalem a indisponibilidade real
  provocada no RDS. O recovery real cobre substituição de uma task, somente.
- Esta auditoria preservou contrato preditivo, ciência, thresholds, métricas,
  artefatos, API, persistência, UI, simulador, Dockerfile e Terraform aplicado.

Fora do escopo: nova arquitetura, serviços adicionais, HA/DR, deploy público
permanente, cloud científica, MLOps contínuo, treinamento/recalibração,
Kubernetes, Kafka, MLflow, Airflow, feature store, drift/retraining automático
e qualquer etapa posterior. ARP4754B/ARP4761A continuam apenas referências
conceituais da organização de engenharia já existente, sem claim de conformidade
ou certificação. O LAB não demonstra segurança operacional real.

## Fechamento

**Stage 3 AWS: VALIDATED.**

**E2E cloud PASS · RDS persistence PASS · ECS recovery PASS · dashboard cloud PASS.**
O fechamento usa os resultados reais fornecidos pelo usuário e a auditoria/testes
locais explicitados acima, sem BLOCKER aberto. Nenhuma nova etapa foi iniciada.

Nenhuma infraestrutura AWS foi modificada neste host Codex.
