# Reviewed portfolio assets

PNGs were visually reviewed and copied unchanged. The
[manifest](manifest.json) records source names, captions and SHA256 hashes.
Original imports remain outside Git. The accidental CSV is unused.

| Asset | Visible content |
|---|---|
| [Dashboard](screenshots/dashboard_main.png) | Unit 1, cycle 191, H30, scores and controls |
| [Operational history](screenshots/operational_history.png) | Persisted predictions and alerts |
| [Cloud E2E](results/cloud_e2e_validation.png) | Observed 40-cycle replay PASS |
| [Recovery](results/ecs_recovery_validation.png) | Replacement task and preserved records |
| [ECS health](results/ecs_health.png) | Healthy API/dashboard, one running task |
| [AWS ECS console](results/aws_ecs_deployment.png) | Active service, one running task, successful deployment and metrics |
| [AWS RDS console](results/aws_rds_deployment.png) | Available PostgreSQL db.t4g.micro instance and configured Secrets Manager |
| [Probabilities](screenshots/model_probabilities.png) | Individual and fusion probabilities |
| [Risk trajectory](screenshots/risk_trajectory.png) | Selected/full telemetry curves |
| [Anomaly](screenshots/anomaly_trajectory.png) | Abnormality indicator, not probability |
| [Attributions](screenshots/important_sensors.png) | Snapshot contributions, not physical causality |
| [Comparison](screenshots/model_comparison.png) | Metric-axis label absent; not used to infer results |
| [Full telemetry](screenshots/telemetry_full_stream.png) | Cumulative bytes and transmission indicator |
| [Telemetry tradeoff](results/telemetry_bytes_vs_pr_auc.png) | Unchanged scientific experiment figure |

The full-stream screenshot does not show sensor age or prove byte reduction.
The anomaly screenshot does not identify alert episodes. Names reflect visible
content rather than original filenames. No generated GIF is included.
