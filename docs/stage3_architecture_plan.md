# Stage 3 — plano arquitetural AWS

Atualizado em 2026-09-17. Estado: **Stage 3 AWS: VALIDATED — LAB**.
Infraestrutura aplicada pelo usuário; E2E cloud, persistência RDS, recuperação
ECS e histórico no dashboard cloud passaram, conforme evidência fornecida pelo
operador. A auditoria local e os limites dessa evidência estão em
[stage3_validation_report.md](stage3_validation_report.md).
Stage 1 e Stage 2 permanecem VALIDATED. Este plano é um cloud deployment
experiment de um engineering demonstrator baseado no benchmark simulado
C-MAPSS FD001. Não amplia as conclusões científicas do projeto.

## Decisão LAB — ADR-S3-001

Adotar **ECR + um serviço ECS Fargate com uma task + RDS PostgreSQL Single-AZ**.
A task terá dois containers distintos, API e dashboard, usando a mesma imagem
Python 3.11 e o mesmo digest. O simulador continuará sendo um processo separado,
executado sob demanda no Windows pelo CLI existente, enviando HTTP à API AWS.
Não haverá container PostgreSQL no ECS; a persistência será RDS.

Implementação validada no LAB: ECR → task ECS Fargate (FastAPI + Streamlit) → RDS
PostgreSQL privado. O Codex não acessou AWS nem alterou o Terraform aplicado;
execução e resultados reais foram fornecidos pelo operador.

Esta é a menor configuração gerenciada escolhida dentro da arquitetura
candidata, não uma afirmação de menor preço entre todos os serviços AWS.
Uma EC2 com Compose e PostgreSQL autogerenciado poderia reduzir a conta e
reproduzir a Stage 2, mas exigiria administrar host, patches, disco e recuperação
do banco. Não será adotada silenciosamente: se o orçamento não comportar RDS,
essa alternativa exige nova decisão explícita antes da implementação.

| Critério | Avaliação da decisão |
| --- | --- |
| Custo | Uma task compartilhada evita duplicar compute/IPv4; RDS é o principal custo persistente |
| Simplicidade | Sem host para administrar; containers API/dashboard mantêm processos e responsabilidades separados |
| Aprendizado e portfólio | Demonstra ECR, execução ECS, IAM, rede, secrets, logs e persistência gerenciada com escopo pequeno |
| Reprodutibilidade | Terraform para infraestrutura; tag versionada imutável resolvida pelo ECS para digest e inventário de dependências/artefatos |
| Segurança | RDS privado, secrets fora de arquivos e acesso externo restrito ao IP do operador; LAB sem TLS HTTP externo é uma limitação aceita apenas para dados simulados |
| Destruição | Recursos identificados e pertencentes ao ambiente; tratamento explícito de imagens, logs, snapshots e secrets residuais |

## Diagrama LAB

```text
Windows local — AWS CLI autenticada por SSO; operador e simulador existente
      | HTTP :8000 (simulador) / HTTP :8501 (navegador)
      | permitido somente do IPv4 público do operador /32
      v
VPC dedicada
  Internet Gateway
      |
  Subnet pública AZ-A — task Fargate com IPv4 público temporário
      +-- API :8000 --> LocalApplicationService --> artefatos congelados
      |       |
      |       +-- PostgreSQL/TLS :5432 --> RDS privado Single-AZ na AZ-A
      |                                     |
      |                              predictions / alerts
      |                                     |
      |       <--------- consultas SQL ------+
      +-- Streamlit :8501 --> http://127.0.0.1:8000
                 histórico via GET /api/v1/predictions e /api/v1/alerts

  Duas subnets privadas AZ-A/AZ-B --> DB subnet group (uma instância RDS)

  ECR --> mesma imagem para API/dashboard
  Secrets Manager --> segredo gerenciado RDS --> ambiente do container API
  CloudWatch Logs <-- stdout/stderr sem secrets
  IAM execution role --> pull ECR, logs e secret específico
```

Containers da mesma task Fargate podem comunicar por `localhost`; subnet
pública com IPv4 atribuído permite acesso aos serviços necessários ao startup.
Essa propriedade elimina descoberta de serviço neste LAB.
[Rede Fargate](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-task-networking.html).

## Recursos e dimensionamento propostos

- Uma região configurável; o LAB atual usa `sa-east-1` e perfil local
  `stage3-lab`. Confirmar tarifas regionais, sem criar outra região automaticamente.
- Um ECR privado, imagem Linux x86_64 Python 3.11. Reutilizar o Dockerfile e
  os artefatos incluídos na Stage 2. Não assumir compatibilidade ARM apenas
  porque a classe do banco é Graviton: banco e containers têm arquiteturas distintas.
- Um cluster ECS, um serviço Fargate On-Demand, **`desired_count=0` por padrão**.
  Uma task somente após ativação explícita. Default configurável de **1 vCPU e
  4 GiB compartilhados**: os dois processos importam dependências científicas,
  incluindo PyTorch/pandas, e a API carrega artefatos existentes. É uma margem
  inicial conservadora, não consumo medido nem garantia de capacidade. Substitui
  a proposta preliminar de 0,5 vCPU/2 GiB; medir pico/startup no primeiro LAB.
  Reservas suaves: 3 GiB para API e 512 MiB para dashboard, compartilhando o
  restante; não são limites individuais rígidos. Plataforma Linux x86_64 1.4.0.
- Armazenamento efêmero padrão de 20 GiB: confirmar tamanho descompactado da
  imagem e uso temporário. Persistência nunca depende do filesystem da task.
- Deploy com mínimo saudável 0% e máximo 100%, aceitando interrupção ao substituir
  a única task, sem duplicação transitória planejada. Sem autoscaling ou Spot.
- RDS PostgreSQL 16, versão minor suportada a fixar; `db.t4g.micro` como candidata
  mínima, 20 GiB gp3, Single-AZ, sem réplica e sem storage autoscaling inicial.
  Confirmar a combinação na região antes de criar. Mesmo AZ do compute reduz
  tráfego entre AZs. Retenção de backup proposta: um dia durante a sessão.
- Storage RDS criptografado com chave AWS gerenciada; secrets também usam
  criptografia gerenciada. Não criar chave KMS própria neste LAB apenas por
  convenção. [Criptografia RDS](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Overview.Encryption.html).
- VPC com DNS habilitado, uma subnet pública e duas privadas; privadas sem rota
  default para internet. O DB subnet group requer subnets em pelo menos duas AZs,
  mesmo para Single-AZ; isso não cria segunda instância nem alta disponibilidade.
  [Rede RDS](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_VPC.WorkingWithRDSInstanceinaVPC.html).
- Dois Security Groups: aplicação e banco; logs de API/dashboard com retenção
  sete dias; somente métricas padrão inicialmente.

## Conexões e regras de rede

| Origem → destino | Regra planejada |
| --- | --- |
| Operador/simulador → task | TCP 8000 e 8501 somente do CIDR /32 informado; nenhum ingresso geral 0.0.0.0/0 |
| Dashboard → API | Loopback 127.0.0.1:8000 dentro da task; sem endereço público ou DNS Compose |
| API → RDS | Endpoint DNS privado, TCP 5432, SG banco aceita somente SG aplicação |
| Task → ECR, secrets, logs | Saída HTTPS por Internet Gateway e IPv4 público; sem NAT |
| Internet → RDS | Proibido; publicly_accessible=false, sem ingresso do operador |

Rota de saída `0.0.0.0/0` para Internet Gateway não equivale a permitir ingresso
geral. O IPv4 da task pode mudar após restart/deploy: consultar o novo endereço,
não hardcode. Não existe endpoint estável nem HTTPS externo neste LAB.
Usar apenas dados simulados e sessões restritas; não abrir a aplicação sem
autenticação para demonstração pública permanente. SG compartilhado por task
não constitui isolamento forte entre API e dashboard.

## Configuração e secrets

- Preservar `APP_BACKEND=api` e `PREDICTIVE_MAINTENANCE_PROJECT_ROOT=/app`.
- No ECS, usar `PREDICTIVE_MAINTENANCE_API_URL=http://127.0.0.1:8000`;
  `http://api:8000` continua correto no Compose local e não será alterado.
- RDS gera e gerencia sua senha via Secrets Manager. Terraform deve referenciar
  o ARN, sem ler o valor do secret para variáveis, outputs, data sources ou state.
  [Gestão de senha RDS](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-secrets-manager.html).
- A imagem publicada aceita `DATABASE_URL`. O adaptador de infraestrutura
  `infra/aws/runtime/api_bootstrap.py` é incorporado ao comando `python -c`
  da task, sem rebuild. ECS injeta somente `username` e `password` do JSON
  gerenciado em `DB_USERNAME`/`DB_PASSWORD`; endpoint/porta/nome vêm do RDS.
  SQLAlchemy URL monta a conexão com escaping em memória e inicia Uvicorn.
  Nenhum segredo é passado por shell, escrito em arquivo ou output Terraform.
- TLS RDS usa `sslmode=verify-full`. No startup, o bootstrap baixa o bundle CA
  regional público pelo HTTPS oficial AWS e grava somente esse certificado
  no filesystem efêmero. Falha no download/configuração impede o startup;
  não há downgrade silencioso. Essa dependência de HTTPS externo usa a saída
  443 já existente. Startup e conexão foram exercitados no E2E real; continuam
  sujeitos à disponibilidade desse download em cada nova task.
  [TLS RDS](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.SSL.html).
- A mesma imagem `stage3-lab-v1` executa Uvicorn na API e `streamlit run` no
  dashboard. Health checks usam Python padrão, sem curl. Dashboard depende de
  API HEALTHY, com limite de espera 120 s; medir startup e rever se necessário.
  Logs separados têm retenção de sete dias, sem Container Insights.
- A execution role recebe `secretsmanager:GetSecretValue` somente no ARN
  gerenciado RDS. A política existente é reutilizada; o antigo flag opcional
  é mantido por compatibilidade de tfvars, mas não desativa uma permissão agora
  necessária ao ECS. ARN legado, se informado, deve coincidir com o RDS atual.
  A injeção de campos JSON exige plataforma Fargate Linux 1.4.0 ou superior.
  [Injeção JSON ECS](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/secrets-envvar-secrets-manager.html).
- Execution role limitada a pull do ECR, logs dos grupos definidos e leitura
  do secret RDS específico. Task role sem permissões AWS adicionais: não precisa
  chamar AWS SDK se ECS injeta o secret. Role do operador/deploy é separada.
- LAB pode usar o usuário gerenciado RDS somente no banco isolado e descartável;
  seus privilégios elevados são uma limitação explícita. PORTFOLIO deverá usar
  usuário de aplicação restrito, com privilégios necessários à inicialização do
  schema existente, e secret separado. Nunca copiar os defaults locais do Compose.
- Injeção de secrets não atualiza processos já iniciados após rotação: reiniciar
  tasks de forma controlada e verificar conexão quando a senha mudar.
  [Secrets no ECS](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/specifying-sensitive-data.html).

## Perfil PORTFOLIO

Extensão pequena do LAB, não implementação paralela obrigatória:

1. Manter uma task com dois containers, RDS Single-AZ e mesma imagem por digest.
2. Adicionar um ALB público, duas subnets públicas em AZs distintas, certificado
   ACM para domínio já controlado e listener HTTPS 443; HTTP 80 apenas redireciona.
   As duas subnets são requisito do ALB regional, não réplicas da aplicação;
   manter apenas uma task. [Subnets ALB](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/application-load-balancers.html).
3. Target groups do tipo `ip`: 8501 para Streamlit por default; 8000 para
   `/api/*`, `/health`, `/docs`, `/docs/*` e `/openapi.json`. Preservar caminhos,
   sem prefixo artificial. Verificar conexões da interface Streamlit e timeout.
4. Task ainda com IPv4 público para saída sem NAT, mas ingresso 8000/8501 somente
   do SG do ALB. Dashboard continua acessando API por localhost; simulator usa HTTPS
   do ALB. ALB inicialmente também restrito ao CIDR do operador.
5. Usar login PostgreSQL de aplicação e secret próprio; retenção de backups
   proposta de sete dias e testes de recuperação limitados ao experimento.

ALB é justificável aqui por HTTPS, hostname estável e roteamento, não por escala.
Ele cobra enquanto existe, mesmo com zero tasks: não integra o LAB inicial.
Tasks privadas exigiriam NAT ou endpoints privados para ECR/S3/logs/secrets;
seu custo e complexidade não são justificados neste escopo. Não adicioná-los
automaticamente apenas para ter uma subnet privada de compute.

## Reprodutibilidade, verificação e fronteiras

Terraform gere os recursos dedicados declarados, com tags `project`,
`stage`, `environment` e `managed_by`; `owner` e `expiration_date` são opcionais.
Backend local protegido e não
versionado é suficiente para um operador. Não criar bucket de state neste prompt.
State/plan locais nunca entram no Git. Autenticação da CLI por perfil/SSO local,
sem chaves ou tokens em arquivos do projeto.

O pyproject atual fixa Python 3.11, mas usa faixas de versões nas dependências.
Rebuild não é reprodução byte a byte garantida: promover a imagem já verificada
por digest, registrar versões efetivas e hashes dos artefatos, sem regenerá-los.
Compose validado é referência de comandos/env/healthchecks, não será executado
como orquestrador dentro de ECS. Configurar healthchecks e dependência de
dashboard na API saudável na task; não iniciar tarefas de treinamento.

Aceitação observada pelo operador: replay da unidade 1, H30/fusion/full/each_cycle,
40 predictions e 3 alerts recuperáveis pela API cloud, retenção dos mesmos
registros após substituição da task e histórico confirmado visualmente no
dashboard. Não houve consulta SQL direta do Windows ao RDS privado. Testes
locais com mocks verificam falhas explícitas sem fallback. A Stage 3 não modifica
métricas científicas, alvos ou thresholds.

Não haverá NAT Gateway, ALB no LAB, Cloud Map/Service Connect, EFS, EC2/bastion,
Aurora, réplicas, Multi-AZ de banco, autoscaling, pipeline contínuo, MLflow,
Kafka, Kubernetes, Airflow, feature store, drift ou retraining automático.

## Pré-requisitos do Prompt 23B

- Confirmar perfil LAB, região, orçamento máximo e duração prevista da sessão.
- AWS CLI v2 autenticada localmente por SSO/perfil; conta identificada e permissão
  para os recursos propostos, sem enviar credenciais ao Codex.
- Terraform e Docker Desktop disponíveis no Windows; definir versões/provider
  e lock da infraestrutura futura. Build Linux x86_64 e disco suficientes.
- Obter CIDR /32 público do operador; confirmar que não ficará exposto ao mundo.
- Medir memória conjunta, startup, tamanho da imagem e uso de disco efêmero;
  escolher tamanho de task antes de criar recursos.
- Confirmar classe/engine/storage RDS na região e estimativa completa no Pricing
  Calculator. Free Tier não faz parte da premissa de custo.
- Planejar bootstrap sem secrets em arquivos/state, bundle CA, ARN gerenciado,
  logs sem secrets e tratamento de rotação. PORTFOLIO exige domínio/certificado.
- Aprovar retenção/descarte dos registros simulados, snapshots e logs, seguindo
  os documentos de custo e lifecycle. O Codex só preparará/validará código;
  apply/destroy e demais mutações AWS serão executados pelo usuário localmente.
