# Stage 3 — ciclo de vida dos recursos

Atualizado em 2026-09-17. **Stage 3 AWS: VALIDATED — LAB**, conforme E2E,
persistência RDS, recovery ECS e dashboard cloud relatados pelo operador em
[stage3_validation_report.md](stage3_validation_report.md). Nenhuma operação AWS
foi executada pelo Codex. O default Terraform permanece `ecs_desired_count=0`;
o LAB validado executou uma task. Os procedimentos abaixo servem para reprodução
e operação local; criação, alteração e destruição AWS são responsabilidade do
operador. Destruição e ausência de cobrança residual não foram testadas nesta
auditoria e não são inferidas do recovery PASS.

## Propriedade e rastreabilidade

Um ambiente/região por vez; tags `project`, `stage=3`, `environment=lab` e
`managed_by=terraform`; `owner` e `expiration_date` opcionais. Manter inventário
não sensível com IDs/ARNs, região,
conta, digest ECR, versão do código, versões de dependências, hashes de configs
e artefatos congelados. Não armazenar credenciais, senha ou tokens nesse inventário.

Usar AWS CLI v2 com autenticação local por SSO/perfil e sessão temporária.
Não criar arquivo de chaves no projeto. Terraform futuro deve gerar senha
por RDS/Secrets Manager, não por variável ou recurso random_password em state.
Não ler valores de secrets em data sources nem expô-los em plan/outputs.
Proteger state e planos locais, mantê-los fora do Git e não executar dois
operadores simultaneamente. Manter state até concluir a limpeza e conferência.

## ECR — publicar e verificar a imagem

Após revisar e aplicar localmente o plan que adiciona ECR, usar uma única imagem
Linux x86_64 para API e dashboard. O Dockerfile já inclui os artefatos congelados;
os containers futuros diferem apenas pelo comando. Não publicar dados brutos,
credenciais, state Terraform, `.venv` ou arquivos temporários.

```powershell
$env:AWS_PROFILE = "stage3-lab"
$env:AWS_REGION = "sa-east-1"
.\scripts\terraform_plan.ps1
# Após revisão independente do plan e apply executado pelo operador:
.\scripts\aws_ecr_push.ps1 -VersionTag "stage3-lab-v1"
.\scripts\aws_ecr_check.ps1 -ExpectedTag "stage3-lab-v1"
```

O push obtém o nome/URI do repositório a partir do state Terraform aplicado,
autentica Docker com `aws ecr get-login-password` sem gravar a senha em arquivo,
e publica `stage3-lab-v1` e `latest`. A tag versionada é imutável; `latest` é
uma conveniência mutável e não deve ser a referência de deploy ECS. Registrar o
digest confirmado e usá-lo, ou usar a tag versionada, no futuro serviço ECS.

O repositório usa scan básico no push, criptografia AWS-managed e política que
mantém os dez manifests mais recentes. A expiração é assíncrona e pode levar até
24 horas; visualizar a prévia da política antes de qualquer alteração futura.
O check confirma repositório, login e digest da tag solicitada, sem criar, apagar
ou alterar recursos AWS.

Para remover imagens de forma deliberada, inspecionar primeiro o digest e os
deployments que o referenciam. A política de ciclo de vida não é uma garantia de
remoção imediata. Na destruição total, excluir as imagens e então o repositório
dedicado pelo Terraform; `force_delete = false` impede exclusão acidental de um
repositório não vazio. Para uma remoção autorizada e pontual, obter o nome pelo
output Terraform e usar `aws ecr batch-delete-image --repository-name <nome>
--image-ids imageDigest=<digest-confirmado>` no perfil/região corretos. Não usar
remoção por prefixo ou comando em massa sem revisar os digests e consumidores.
Conferir armazenamento ECR remanescente depois.

## Criar — somente pelo usuário, após revisão

### RDS LAB — configurar, verificar e controlar o ciclo de vida

O RDS usa PostgreSQL **16.13** configurável, compatível com o engine PostgreSQL 16
do Compose, `db.t4g.micro`, 20 GiB gp3, criptografia AWS-managed, Single-AZ na
primeira AZ configurada e as subnets/SG privados existentes. Não há IP público,
réplica, proxy, autoscaling de storage, Performance Insights ou Enhanced Monitoring.
Não copiar novamente o exemplo de tfvars sobre a configuração local já aplicada.
Os novos parâmetros podem ser adicionados ao arquivo existente ou usar os defaults.

A versão minor exata é consultada pelo Terraform durante plan, sem substituição
silenciosa. Confirmar também classe/engine/storage na região antes do apply:

```powershell
$env:AWS_PROFILE = "stage3-lab"
$env:AWS_REGION = "sa-east-1"
aws rds describe-orderable-db-instance-options --engine postgres --engine-version 16.13 --db-instance-class db.t4g.micro --region $env:AWS_REGION --query "OrderableDBInstanceOptions[?StorageType=='gp3'].DBInstanceClass" --output text
.\scripts\terraform_plan.ps1
# Inspecionar o plan e executar apply somente localmente após aprovação do operador.
.\scripts\aws_rds_check.ps1
```

Com a fundação e ECR sem drift, o plan deve adicionar somente `aws_db_instance.lab`,
seus outputs e a leitura regional da versão. O secret é criado/gerenciado pelo
próprio RDS, não por um recurso contendo senha em Terraform. Nenhuma senha entra
em tfvars, outputs ou state pelo código desta etapa. A política IAM de secret
existente agora referencia automaticamente o ARN exato do RDS para injeção ECS;
nenhuma role precisa ser recriada. O antigo flag opcional é mantido somente por
compatibilidade, e um ARN legado informado deve coincidir com o RDS atual.
O usuário master tem privilégios elevados:
seu uso está limitado ao LAB isolado e descartável.

`aws_rds_check.ps1` verifica instância available, engine, DNS/porta, rede privada,
subnet group, SG, Single-AZ, classe/storage/encryption e secret ativo. Consulta
somente metadados via `describe-db-instances` e `describe-secret`, nunca seu valor.
Não executa SQL do Windows; a conexão FastAPI → RDS será testada dentro de ECS.

Backup automático: **um dia**, sem backup retido após exclusão. A instância tem
`deletion_protection = false` e `skip_final_snapshot = true`. Destruição descarta
os registros simulados sem criar snapshot final; snapshots manuais eventualmente
criados pelo operador precisam de limpeza separada. Essa política não é de produção.
Upgrades automáticos de minor e mudanças de major estão desabilitados para manter
a configuração explícita: revisar atualizações/avisos obrigatórios da AWS e ajustar
a versão deliberadamente. Extended Support não é contratado pela configuração.

Comandos abaixo são **somente para o operador local**:

```powershell
$rdsIdentifier = (terraform -chdir=infra/aws output -raw rds_instance_identifier).Trim()
aws rds describe-db-instances --db-instance-identifier $rdsIdentifier --region $env:AWS_REGION --query "DBInstances[0].DBInstanceStatus" --output text
aws rds stop-db-instance --db-instance-identifier $rdsIdentifier --region $env:AWS_REGION --query "DBInstance.DBInstanceStatus" --output text
# Para retomar:
aws rds start-db-instance --db-instance-identifier $rdsIdentifier --region $env:AWS_REGION --query "DBInstance.DBInstanceStatus" --output text
aws rds wait db-instance-available --db-instance-identifier $rdsIdentifier --region $env:AWS_REGION
.\scripts\aws_rds_check.ps1
```

RDS reinicia automaticamente após sete dias parado. Storage, backups e secret
continuam gerando custo durante a parada. Não executar plan/apply durante uma
parada sem revisar seus efeitos; recursos não são removidos por stop.
Para destruição do LAB inteiro, revisar `terraform -chdir=infra/aws plan -destroy`
e executar `terraform -chdir=infra/aws destroy` apenas localmente. Isso também
remove a fundação e ECR: tratar antes as imagens do repositório não vazio e seguir
as conferências de resíduos abaixo. Não usar exclusão manual da instância fora
do Terraform como procedimento normal.

Referências: [versões RDS PostgreSQL](https://docs.aws.amazon.com/AmazonRDS/latest/PostgreSQLReleaseNotes/postgresql-versions.html),
[senha gerenciada pelo RDS](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-secrets-manager.html),
[parada temporária](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_StopInstance.html).

1. Confirmar conta/perfil/região, CIDR /32 do operador, orçamento e prazo.
   Conferir cotação, memória/startup e combinação engine/classe RDS.
2. Aplicar primeiro o repositório ECR após revisar o plan; publicar uma imagem
   Linux x86_64 sem dados brutos, credenciais ou artefatos temporários e validar
   digest/hashes sem regenerar artefatos científicos.
3. Futuro Terraform: `terraform init`, `terraform fmt -check`,
   `terraform validate` e `terraform plan`. Inspecionar recursos e remoções;
   não substituir silenciosamente a arquitetura escolhida.
4. Ordem de provisionamento: rede/IAM e ECR; publicar imagem; logs,
   RDS e secret gerenciado; serviço ECS com digest e containers API/dashboard.
   O futuro código poderá separar bootstrap/publicação e ativação do serviço
   para não iniciar task antes de a imagem e o banco estarem disponíveis.
5. Executar apply somente localmente após revisão. Não usar credentials/secret
   values em arquivos tfvars, scripts, outputs, linha de comando ou logs.
6. LAB sem snapshot final obrigatório: decidir descarte dos dados simulados antes
   de criar. PORTFOLIO: decisão explícita de snapshot final, nome e prazo de exclusão.
   Proteção contra exclusão deve ter procedimento de desativação antes de destruir;
   não deixar o ambiente indestrutível por um default não documentado.

## ECS LAB — preparar, ligar, verificar e desligar

Não recopiar o exemplo de tfvars sobre a configuração aplicada. A nova revisão
adiciona cluster, task definition, service, dois log groups e a política de leitura
do secret específico. Rede, RDS e ECR não precisam ser recriados. Revisar o plan
real: mudanças nesses recursos não são esperadas e exigem investigação local.

```powershell
$env:AWS_PROFILE = "stage3-lab"
$env:AWS_REGION = "sa-east-1"
$env:TF_VAR_ecs_desired_count = "0"
.\scripts\terraform_plan.ps1
# Revisar e aplicar a infraestrutura somente no Windows local.
.\scripts\aws_ecs_check.ps1  # READY / NOT RUNNING com zero tasks
.\scripts\aws_lab.ps1 start
# Aguardar startup; este comando nao inicia RDS, que deve estar available.
.\scripts\aws_ecs_check.ps1
.\scripts\aws_ecs_endpoint.ps1
.\scripts\aws_lab.ps1 status
.\scripts\aws_lab.ps1 stop
```

`start`/`stop` geram um plan salvo e recusam qualquer criação, destruição ou
alteração de recurso diferente de `desired_count` do service existente. Aplicam
esse plan somente quando o operador executa o script localmente. State e output
ficam reconciliados, sem `aws ecs update-service` fora do Terraform. Depois,
esperar zero running/pending antes de considerar Fargate desligado. Consultas
`status`, `endpoints`, `aws_ecs_check` e `aws_ecs_endpoint` são somente leitura.

O script configura `TF_VAR_ecs_desired_count` na sessão atual. Em uma nova sessão,
definir explicitamente `"1"` enquanto o LAB deve rodar, ou `"0"` para desligar,
antes de um plan/apply normal. Não definir `ecs_desired_count` em tfvars se quiser
usar a variável de ambiente: tfvars tem precedência. O controle LAB usa `-var`
explícito. O default zero evita cobrança Fargate ao primeiro apply; um apply
posterior com zero também solicita a parada. Não usar `-target` para contornar
o bloqueio de mudanças encontrado pelo controle LAB.

Ambos containers reutilizam `stage3-lab-v1`, sem rebuild. API inicia Uvicorn
por bootstrap de infraestrutura; dashboard executa Streamlit e usa loopback
`http://127.0.0.1:8000`. O bootstrap monta `DATABASE_URL` em memória a partir
dos campos JSON injetados pelo ECS e baixa somente o certificado CA público AWS.
TLS usa `verify-full`; falhas impedem startup explicitamente. Os checks consultam
metadados e referências de secret, nunca o valor. A porta 5432 permanece privada.

O IPv4 da task muda ao substituir/reiniciar: obter URLs pelo script endpoint,
sem output Terraform estático. CloudWatch recebe logs em dois grupos por sete
dias. Após rotação da senha, substituir tasks de forma controlada, pois variáveis
injetadas não se atualizam em processos existentes. O check ECS PASS verifica
metadados/health; replay, SQL e retenção cloud ainda exigem execução real local.

## Verificar

1. Conferir RDS available/privado, serviço ECS estável, uma task running e os
   healthchecks dos containers; verificar grupos de logs e ausência de secrets.
2. Consultar IP atual da task LAB; atualizar URL do simulador, sem hardcode
   duradouro. PORTFOLIO usa hostname HTTPS do ALB com certificado válido.
3. Testar `/health` e `/api/v1/options`, selecionar opções retornadas e executar
   o CLI de simulador existente contra a API cloud, uma unidade e poucos ciclos.
   O intervalo continua sendo tempo de simulação, não tempo físico do motor.
4. Consultar `/api/v1/predictions` e `/api/v1/alerts`; comparar pequena amostra
   com RDS a partir de execução dentro da VPC, não abrindo 5432 ao operador.
5. Abrir dashboard e conferir Operational history da unidade/horizonte;
   confirmar APP_BACKEND=api, loopback interno e erro explícito quando API falha.
6. Substituir/reiniciar task de forma controlada, consultar novamente os registros
   e comprovar retenção no RDS. Reiniciar compute não deve recriar/remover o banco.
7. Registrar resultados reais, duração, custos observados quando disponíveis e
   limitações. Stage 2 VALIDATED não significa Stage 3 cloud validada antecipadamente.

## Desligar temporariamente

1. Interromper simulador e quaisquer tasks avulsas.
2. Ajustar serviço ECS para desired_count=0 e esperar zero tasks running/pending;
   parar apenas uma task sem alterar o serviço pode causar recriação automática.
3. Parar RDS para intervalo curto, quando a instância escolhida permitir.
   Não excluir dados durante simples desligamento.
4. Conferir liberação do IP temporário da task. ECR, secrets, logs, storage e
   backups ainda existem. No PORTFOLIO, ALB continua cobrando enquanto existir;
   para interromper esse custo é necessário excluí-lo e depois recriá-lo.
5. Registrar mudança de desired_count no workflow Terraform para evitar
   que um próximo apply reative o serviço inadvertidamente.

RDS reinicia automaticamente após sete dias consecutivos parado; storage e
backups continuam cobrando durante a parada. A recomendação para intervalos
longos é destruir com política explícita de dados, não criar automações extras
para contornar o reinício. [Parada RDS](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_StopInstance.html).

Para retomar: iniciar RDS, aguardar available, ativar uma task, aguardar health,
descobrir endereço vigente e conferir histórico. Secrets injetados precisam
estar atuais; após rotação, substituir tasks, não imprimir o secret para depurar.

## Destruir

1. Conferir conta/região e inventário exato. Decidir descarte ou exportação segura
   dos registros simulados e snapshot final; destruir banco apaga dados se não
   existir retenção escolhida. Não tocar no banco/volume Docker local da Stage 2.
2. Parar simulador/tasks e zerar serviço. Futuro `terraform plan -destroy`:
   revisar alvos; usuário executa `terraform destroy` localmente.
3. Remover serviço/cluster ECS e recursos dedicados; esperar ENIs gerenciadas
   liberadas. No PORTFOLIO, excluir listeners/ALB/target groups antes de rede.
4. Excluir RDS com política aprovada, decidir remoção de backups automatizados
   retidos e snapshots manuais/final. Snapshot final escolhido continua cobrando
   e deve constar de inventário com prazo de exclusão.
5. Conferir o ciclo de vida do secret gerenciado RDS; remover secrets próprios
   do projeto conforme política. Registrar eventual janela de recuperação e
   verificar seu término, sem presumir que agendamento significa limpeza completa.
6. Excluir imagens/repositório ECR se o objetivo for ausência de cobrança residual;
   remover log groups dedicados e eventuais exports. Retenção opcional deve ser
   deliberada e estimada, nunca um recurso esquecido.
7. Remover SGs, subnet group, rotas, subnets, IGW e VPC após dependências;
   roles/policies dedicadas. Não remover recursos de conta compartilhados.
8. Remover certificado e registros DNS dedicados no PORTFOLIO; domínio existente
   não pertence automaticamente ao stack e pode ter renovação independente.

Terraform deverá gerir o que criar. Itens gerenciados por RDS e resíduos fora
do state precisam de conferência; destroy não prova sozinho conta futura zero.
Não usar comandos de limpeza genérica da conta ou remoção em massa sem alvos.

## Verificar ausência de cobrança residual

| Área | Conferência após destruição |
| --- | --- |
| ECS/Fargate | Nenhuma task running/pending, inclusive avulsas; serviço/cluster dedicado removidos |
| RDS | Instância excluída; nenhum snapshot manual/final ou backup retido não autorizado |
| ECR | Nenhuma imagem/repositório dedicado mantido involuntariamente |
| Secrets | Nenhum secret órfão ativo; acompanhar exclusões ainda agendadas |
| CloudWatch | Log groups/exports/alarms específicos removidos ou retenção deliberada registrada |
| Rede | Nenhum ALB, ENI da task ou IP dedicado remanescente; nenhum NAT/endpoint pago foi criado |
| PORTFOLIO | ALB removido, DNS/certificado dedicados tratados; conta de domínio/zone externa identificada |
| IAM/state | Permissões dedicadas tratadas; state conferido e preservado até terminar verificação |
| Billing | Rever custo por serviço/região nos dias seguintes; cobranças atrasadas anteriores à exclusão não provam recurso ainda ativo |

Combinar inventário de recursos com Billing/Cost Explorer. Tags ajudam, mas
nem todos os resíduos podem ser descobertos somente por tags. Conferir a região
usada e qualquer outra efetivamente tocada; não afirmar custo zero antes de
verificar storage/backups/imagens/logs/IPs e a atualização do faturamento.

Verificações de preparação ECS no Codex: Terraform fmt/validate, parser Windows
PowerShell 5.1 e testes focados de bootstrap/controles com mocks locais. Isso
não comprova conectividade SQL, uso real de memória ou replay AWS. Nenhum
create/apply/destroy ou chamada AWS mutante foi executado no Codex.
