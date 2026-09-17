# Stage 3 — plano de custos

Data da consulta: 2026-09-16; atualização de configuração em 2026-09-17.
O LAB foi aplicado e validado pelo operador: ECR, RDS privado e ECS/logs estão
operacionais. O default Terraform continua zero tasks; a execução validada usou
uma task. A auditoria não mediu a conta AWS nem reconsultou tarifas. Evidências:
[stage3_validation_report.md](stage3_validation_report.md).
Valores em USD são referências publicadas, sem tributos, câmbio ou benefícios
da conta. Revalidar região e tarifas antes do apply local. Não pressupor Free
Tier, créditos, Savings Plans ou reservas para justificar o experimento.

## Perfis

**LAB:** uma task Fargate On-Demand API/dashboard, RDS Single-AZ privado,
um ECR, secret gerenciado RDS, logs limitados e rede sem NAT/ALB. Sessão sugerida
de até oito horas, depois desligamento temporário ou destruição planejada.

**PORTFOLIO:** LAB mais ALB/HTTPS, certificado para domínio existente e secret
de login de aplicação. Ainda uma task e uma instância RDS. Não é ambiente
permanente nem exige alta disponibilidade.

## Inventário de recursos e cobrança residual

| Serviço / função | Por que necessário | Recurso mínimo proposto | Principal custo | Pode ficar desligado? | Como destruir | Risco residual |
| --- | --- | --- | --- | --- | --- | --- |
| ECR / distribuição de imagem | ECS precisa da imagem versionada | Um repositório privado, digest aprovado e no máximo poucas versões necessárias | GB de camadas armazenadas; transferência aplicável | Não tem modo stop; pode ficar sem uso | Excluir imagens e repositório dedicado via Terraform, política explícita para repositório não vazio | Imagens mantidas após parar tasks continuam armazenadas |
| ECS/Fargate / API e dashboard | Execução gerenciada sem servidor | Um cluster/serviço, zero tasks por default; ativação de uma task 1 vCPU/4 GiB configurável, sizing a medir | vCPU, RAM e eventual disco extra, inclusive tempo de pull/startup | Sim, desired_count=0; parar também tasks avulsas | Remover serviço/task definitions/cluster dedicados depois de parar tasks | Task avulsa ou segundo deploy ainda rodando; IP associado |
| RDS / PostgreSQL | Persistência gerenciada equivalente à Stage 2 | Uma db.t4g.micro candidata, PG16, Single-AZ, 20 GiB gp3 | Horas de instância, storage, backups excedentes, possíveis créditos CPU e transferência | Temporariamente; storage/backups permanecem cobrados | Excluir instância, backups/snapshots conforme política e recursos associados | Reinício automático após sete dias; snapshots/backups retidos; Extended Support se engine ficar antigo |
| Secrets Manager / credencial RDS | Evitar senha em repositório e state | Um secret gerenciado RDS; PORTFOLIO soma secret da aplicação | Quantidade/tempo de secrets e chamadas | Não tem stop separado | Secret RDS conforme ciclo de vida da instância; verificar exclusão; secret próprio via lifecycle explícito | Secrets órfãos, versões/replicação não planejada ou exclusão ainda em recuperação |
| CloudWatch Logs / diagnóstico | Ver startup, erros, health e replay | Dois log groups, retenção sete dias, awslogs; sem métricas customizadas | Ingestão, retenção e consultas | Parar logs novos parando tasks; dados existentes permanecem | Excluir grupos dedicados, não apenas log streams | Logs retidos sem expiração ou consultas volumosas |
| IAM / autorização | ECR/logs/secret e deploy sem chaves na task | Execution role e políticas restritas; task role sem acesso AWS extra | Sem tarifa direta de role/policy; operações dos serviços autorizados cobram | Não se aplica | Remover somente roles/policies do projeto | Sem cobrança direta; permissões órfãs são risco de acesso |
| VPC/subnets/rotas/IGW / rede | Ligar task e RDS sem expor DB | Uma VPC, uma subnet pública e duas privadas, IGW | Esses componentes básicos não são o custo principal; IPv4/transferência cobram à parte | Não precisam ser ligados/desligados | Excluir após liberar ENIs e dependências | ENIs/recursos não destruídos podem impedir limpeza |
| Security Groups / controle de acesso | Restringir operador e conexão ao banco | SG aplicação e SG RDS; PORTFOLIO soma SG ALB | Sem tarifa direta do SG | Não se aplica | Remover regras/referências e SGs dedicados | Sem cobrança direta; abertura indevida aumenta exposição |
| IPv4 público / saída e acesso LAB | Permitir pull/secrets/logs sem NAT e entrada restrita | Um IP temporário da task, sem Elastic IP | IP-hora | Liberado quando task para | Parar task e verificar ENI/IP liberados | Tasks restantes; PORTFOLIO também tem IPs do ALB |
| ALB / HTTPS e endereço estável PORTFOLIO | Necessário só para apresentação com TLS/hostname | Um ALB, duas subnets públicas, dois target groups IP | ALB-hora, LCU-hora e IPv4 | Não possui stop; existe cobrança mesmo com targets vazios | Excluir ALB/listeners/target groups pelo Terraform | ALB deixado após desligar compute, IPs e logs adicionais |
| ACM / TLS PORTFOLIO | Certificado para listener HTTPS | Um certificado público não exportável, domínio já controlado | Confirmar modalidade; registro de domínio/DNS separado pode cobrar | Não se aplica | Remover certificado dedicado e validação DNS criada para ele | Renovação de domínio ou zona DNS criada fora do stack |

Os tamanhos acima são propostas para verificação, não consumo de memória ou
latência já medidos em AWS. A imagem atual inclui PyTorch e artefatos: medir
camadas comprimidas/descompactadas antes de estimar ECR e storage da task.

## Modelo de cálculo

Usar uma planilha/calculadora com parâmetros de horas de task, horas de RDS,
tempo de retenção, GB de imagens/logs, tamanho de storage e número de IPs.

```text
C_LAB = horas_task × (vCPU × tarifa_vCPU + GiB_RAM × tarifa_RAM + tarifa_IP)
      + horas_RDS × tarifa_instancia
      + storage_RDS_proporcional + backups_excedentes
      + ECR_proporcional + secrets_proporcionais_e_chamadas
      + logs_ingestao_e_retencao + transferencia + CPU_RDS_se_aplicavel

C_PORTFOLIO = C_LAB + horas_ALB × tarifa_ALB
            + LCU_horas × tarifa_LCU + IPs_ALB_horas × tarifa_IP
            + secret_aplicacao + eventual DNS/dominio
```

Referência ilustrativa Linux/x86 em us-east-1: a página Fargate publica
US$ 0,000011244/vCPU-segundo e US$ 0,000001235/GiB-segundo nos exemplos.
Para 1 vCPU/4 GiB, isso equivale a aproximadamente **US$ 0,05826/h** de
compute. Os 20 GiB efêmeros padrão estão incluídos.
[Fargate pricing](https://aws.amazon.com/fargate/pricing/).

Somando um IPv4 a US$ 0,005/h, a parcela task/IP é aproximadamente
US$ 0,06326/h: **US$ 0,51 por oito horas**, US$ 2,53 por 40 horas ou
US$ 46,18 por 730 horas. Esses números **não são a conta total**: RDS,
storage, backups, secrets, ECR, logs e tráfego precisam ser acrescentados.
[Public IPv4 pricing](https://aws.amazon.com/vpc/pricing/).

RDS deve ser cotado para região/classe/engine/storage efetivamente escolhidos;
não foi obtida aqui uma cotação regional completa. Instância parada não elimina
storage e backups. Conferir também CPU burst e suporte da versão PostgreSQL.
[RDS PostgreSQL pricing](https://aws.amazon.com/rds/postgresql/pricing/).

Como referência, os exemplos oficiais indicam secret a US$ 0,40/mês mais
US$ 0,05/10.000 chamadas e ECR privado a US$ 0,10/GB-mês; confirmar aplicação
regional e proporcionalidade. A retenção, não somente as horas de uso, entra
na conta. [Secrets pricing](https://aws.amazon.com/secrets-manager/pricing/),
[ECR pricing](https://aws.amazon.com/ecr/pricing/).

Nos exemplos us-east-1, ALB soma US$ 0,0225/h e US$ 0,008/LCU-h.
O mínimo ilustrativo de base ALB mais dois IPv4 é cerca de US$ 0,0325/h,
**US$ 23,73 em 730 horas antes de LCUs**, além do LAB. Essa parcela fixa
justifica evitar ALB na primeira implantação.
[ELB pricing](https://aws.amazon.com/elasticloadbalancing/pricing/).

Logs cobram por dimensões próprias; usar volume medido e não assumir custo
zero para retenção/consultas. [CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/).

## Controles de laboratório

ECS default `desired_count=0`: nenhuma task Fargate executa após o primeiro
apply. `desired_count=1` inicia cobrança de Fargate e IPv4 público durante a
atividade da task, inclusive startup. RDS ativo tem custo independente; parar
ECS não para o banco. ECR, secret, logs e storage continuam existindo/cobrando.
Confirmar zero tasks running/pending, inclusive avulsas, depois do stop.
O sizing 1 vCPU/4 GiB substitui a proposta preliminar de 0,5/2 pela presença de
dependências científicas nos dois processos; ainda precisa de medição cloud.
Não foram adicionados NAT, ALB, endpoints pagos, autoscaling ou réplicas.

Defaults RDS implementados: PostgreSQL 16.13 configurável, `db.t4g.micro`,
20 GiB gp3 criptografados, Single-AZ, backup automático de um dia, sem storage
autoscaling, Performance Insights, Enhanced Monitoring ou Extended Support
contratado. A combinação deve ser confirmada na região escolhida (`sa-east-1`
no experimento atual); nenhuma tarifa de us-east-1 deve ser tratada como cotação
para São Paulo. Acrescentar secret gerenciado pelo RDS e custo de CPU burst
quando aplicável. Storage/backup/secret continuam cobrando após stop. Não há
snapshot final automático nem backup retido na exclusão do LAB; snapshots manuais
criados fora do Terraform podem continuar cobrando. Nenhum preço novo foi presumido.

- Antes do Prompt 23B: escolher região, duração e teto monetário; preencher a
  estimativa completa no [AWS Pricing Calculator](https://calculator.aws/).
  Não executar apply com expectativa de conta total baseada só no preço Fargate.
- Operação manual de sessão: registrar início e término; tags ExpirationDate
  documentam intenção, mas não desligam recursos automaticamente.
- Verificar Billing/Cost Explorer e alerta de orçamento disponível na conta;
  alertas não são limitadores rígidos de gasto e faturamento pode atrasar.
- Preferir destruir o LAB ao final, com descarte de dados simulado explicitamente
  decidido, em vez de manter RDS indefinidamente parado.
- Uma task, sem deploy duplicado, sem autoscaling, sem reservas, sem Spot inicial,
  sem enhanced scanning pago, métricas customizadas ou Container Insights inicial.
- Não adicionar NAT, endpoints privados pagos ou ALB sem rever a estimativa.

O custo final só será observado após execução pelo usuário. Nenhum recurso foi
criado para coletar preços ou métricas, e nenhuma porcentagem/custo é universal.
