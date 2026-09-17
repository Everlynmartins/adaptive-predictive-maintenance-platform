FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY configs/local_app.toml configs/fusion_alert_policy.toml ./configs/
COPY data/processed/fd001/validation.parquet data/processed/fd001/split_manifest.json ./data/processed/fd001/
COPY reports/classical_ml/metrics.json reports/classical_ml/random_forest_model_card.json reports/classical_ml/xgboost_model_card.json ./reports/classical_ml/
COPY reports/classical_ml/artifacts/validation_predictions.parquet ./reports/classical_ml/artifacts/
COPY reports/discrete_hazard/metrics.json reports/discrete_hazard/model_card.json ./reports/discrete_hazard/
COPY reports/fusion/metrics.json reports/fusion/model_card.json ./reports/fusion/
COPY reports/weibull/metrics.json reports/weibull/model_card.json ./reports/weibull/
COPY reports/weibull/artifacts/validation_predictions.parquet ./reports/weibull/artifacts/
COPY reports/tcn/metrics.json reports/tcn/model_card.json ./reports/tcn/
COPY reports/tcn/artifacts/validation_predictions.parquet ./reports/tcn/artifacts/
COPY reports/transformer/metrics.json reports/transformer/model_card.json ./reports/transformer/
COPY reports/transformer/artifacts/validation_predictions.parquet ./reports/transformer/artifacts/
COPY reports/explainability_uncertainty/calibration_metrics.parquet reports/explainability_uncertainty/validation_explanations.parquet ./reports/explainability_uncertainty/
COPY reports/telemetry_filtering/artifacts/alert_thresholds.json reports/telemetry_filtering/artifacts/development_metrics.parquet reports/telemetry_filtering/artifacts/development_metrics_by_unit.parquet ./reports/telemetry_filtering/artifacts/
COPY reports/telemetry_filtering/artifacts/full_trained/full/packets.parquet reports/telemetry_filtering/artifacts/full_trained/full/receiver_states.parquet reports/telemetry_filtering/artifacts/full_trained/full/validation_predictions.parquet ./reports/telemetry_filtering/artifacts/full_trained/full/
COPY reports/telemetry_filtering/artifacts/full_trained/fixed_k2/packets.parquet reports/telemetry_filtering/artifacts/full_trained/fixed_k2/receiver_states.parquet reports/telemetry_filtering/artifacts/full_trained/fixed_k2/validation_predictions.parquet ./reports/telemetry_filtering/artifacts/full_trained/fixed_k2/
COPY reports/telemetry_filtering/artifacts/full_trained/fixed_k3/packets.parquet reports/telemetry_filtering/artifacts/full_trained/fixed_k3/receiver_states.parquet reports/telemetry_filtering/artifacts/full_trained/fixed_k3/validation_predictions.parquet ./reports/telemetry_filtering/artifacts/full_trained/fixed_k3/
COPY reports/telemetry_filtering/artifacts/full_trained/fixed_k5/packets.parquet reports/telemetry_filtering/artifacts/full_trained/fixed_k5/receiver_states.parquet reports/telemetry_filtering/artifacts/full_trained/fixed_k5/validation_predictions.parquet ./reports/telemetry_filtering/artifacts/full_trained/fixed_k5/
COPY reports/telemetry_filtering/artifacts/full_trained/subset_train17/packets.parquet reports/telemetry_filtering/artifacts/full_trained/subset_train17/receiver_states.parquet reports/telemetry_filtering/artifacts/full_trained/subset_train17/validation_predictions.parquet ./reports/telemetry_filtering/artifacts/full_trained/subset_train17/
COPY reports/telemetry_filtering/artifacts/full_trained/adaptive_q95/packets.parquet reports/telemetry_filtering/artifacts/full_trained/adaptive_q95/receiver_states.parquet reports/telemetry_filtering/artifacts/full_trained/adaptive_q95/validation_predictions.parquet ./reports/telemetry_filtering/artifacts/full_trained/adaptive_q95/
COPY reports/telemetry_filtering/artifacts/full_trained/adaptive_q99/packets.parquet reports/telemetry_filtering/artifacts/full_trained/adaptive_q99/receiver_states.parquet reports/telemetry_filtering/artifacts/full_trained/adaptive_q99/validation_predictions.parquet ./reports/telemetry_filtering/artifacts/full_trained/adaptive_q99/
COPY docs/prediction_contract.md docs/safety_requirements.md docs/safety_assumptions.md docs/traceability_matrix.csv ./docs/

RUN python -m pip install --no-build-isolation .

EXPOSE 8000 8501

CMD ["uvicorn", "predictive_maintenance.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
