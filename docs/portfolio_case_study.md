# Portfolio case study

## Problem

Estimate risk within a stated future horizon, preserve causal information flow,
and deliver reproducible predictions through an integrated application.
NASA C MAPSS FD001 supplies simulated trajectories; H15/H30 are benchmark
cycles, not industrial maintenance rules.

## Approach and modeling

Compare an age-based Weibull baseline, causal-feature Random Forest/XGBoost,
discrete hazard, TCN and a small Transformer. Partitions, folds and bootstrap
preserve whole units. Grouped out-of-sample predictions support fusion;
Isolation Forest remains an anomaly indicator.

Transformer validation PR AUC is approximately 0.988/0.983 at H15/H30;
Fusion reaches 0.973/0.961. These are development results, not industrial
generalization. Neural models remain outside fusion pending approved OOF.

## Telemetry

Causal receiver reconstruction retains sensor age and validity. The selected
sensor subset reduced estimated bytes by about 25% while preserving the
evaluated Fusion scenario. Aggressive temporal filtering approached 80%
reduction with performance or availability tradeoffs.

## Architecture and cloud

FastAPI delegates prediction semantics to LocalApplicationService. PostgreSQL
persists results; Streamlit retrieves serving responses and history through
the API. One Docker image serves both API and dashboard.

The AWS LAB uses one Fargate task, private RDS, ECR, Secrets Manager and
CloudWatch. Restricted public ports and dynamic IPv4 avoid an ALB/NAT Gateway
but require endpoint rediscovery. The design is a temporary demonstrator.

## Validation and recovery

Real operator-observed cloud replay recovered 40 valid predictions and 3 alerts
from 40 cycles. After a controlled task stop with desired count 1, a healthy
replacement recovered the same records. This verifies the exercised
task-recovery behavior, not high availability or disaster recovery.

## Lessons learned

- Define event, horizon and conditioning before model selection.
- Keep targets and retrospective information out of features.
- Evaluate calibration and timing alongside discrimination.
- Treat filtering as an information-flow architecture change.
- Persist outside ephemeral compute and exercise recovery.
- Separate analytical diversity from demonstrated independence.

The [README](../README.md) links scientific reports and deployment evidence.
No models were retrained for this presentation.
