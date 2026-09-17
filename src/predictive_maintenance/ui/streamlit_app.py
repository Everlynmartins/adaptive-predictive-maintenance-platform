"""Streamlit presentation for the local FD001 demonstrator."""

from __future__ import annotations

import json
import os
from pathlib import Path
import time

import numpy as np
import pandas as pd
import streamlit as st

from predictive_maintenance.application.local_service import (
    ApplicationSelection,
    LocalApplicationError,
    LocalApplicationService,
)
from predictive_maintenance.ui.api_client import APIApplicationService, APIClientError


ROOT = Path(__file__).resolve().parents[3]


@st.cache_resource
def _service() -> LocalApplicationService | APIApplicationService:
    backend = os.environ.get("APP_BACKEND", "api").strip().lower()
    if backend == "local":
        return LocalApplicationService(ROOT)
    if backend == "api":
        return APIApplicationService()
    raise APIClientError("APP_BACKEND must be 'api' or 'local'")


def _render_status(status: str, validity: str, stale: bool) -> None:
    message = f"Prediction status: **{status}** · input validity: **{validity}**"
    if stale:
        message += " · telemetry stale"
    if status == "valid":
        st.success(message)
    elif status == "degraded":
        st.warning(message)
    else:
        st.error(message)


def _safe_metric(value: object, digits: int = 4) -> str:
    if value is None or (isinstance(value, (float, np.floating)) and not np.isfinite(value)):
        return "unavailable"
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.{digits}f}"
    return str(value)


def main() -> None:
    st.set_page_config(page_title="Adaptive Predictive Maintenance", layout="wide")
    st.title("Adaptive Predictive Maintenance Platform")
    st.caption("Local FD001 demonstrator · simulated benchmark · no operational safety or certification claim")
    try:
        service = _service()
    except (LocalApplicationError, APIClientError) as exc:
        st.error(f"Application unavailable: {exc}")
        st.stop()

    with st.sidebar:
        st.header("Scenario")
        unit_id = st.selectbox("unit_id", service.available_units, index=0)
        horizon = st.selectbox("Horizon (cycles)", service.horizons, index=1)
        model = st.selectbox("Risk model", service.models, index=0)
        policy = st.selectbox("Telemetry policy", service.policies, index=0)
        cadence = st.selectbox("Inference cadence", service.inference_cadences, index=0)
        retrospective = st.checkbox(
            "Retrospective evaluation mode", value=False,
            help="Shows true RUL and lead time. This information is unavailable in production.",
        )
        st.info(f"Explicit prediction horizon: **H={horizon} cycles**")

    try:
        result = service.run(ApplicationSelection(
            unit_id=int(unit_id), horizon=int(horizon), model=str(model),
            telemetry_policy=str(policy), inference_cadence=str(cadence),
            retrospective=bool(retrospective),
        ))
    except (LocalApplicationError, APIClientError, ValueError) as exc:
        st.error(f"Scenario unavailable: {exc}")
        st.stop()

    trajectory = result.trajectory
    first_cycle = int(trajectory.cycle.min())
    last_cycle = int(trajectory.cycle.max())
    selected_unit = int(unit_id)
    previous_unit = st.session_state.get("_playback_unit_id")
    if previous_unit is None:
        st.session_state["_playback_unit_id"] = selected_unit
        st.session_state["_playback_cycle"] = last_cycle
        st.session_state["_playback_playing"] = False
        st.session_state["cycle_slider"] = last_cycle
    elif previous_unit != selected_unit:
        st.session_state["_playback_unit_id"] = selected_unit
        st.session_state["_playback_cycle"] = first_cycle
        st.session_state["_playback_playing"] = False
        st.session_state["cycle_slider"] = first_cycle
    if "cycle_slider" not in st.session_state:
        st.session_state["cycle_slider"] = st.session_state["_playback_cycle"]
    if st.session_state["_playback_playing"]:
        # Synchronize the widget before it is instantiated on each rerun.
        st.session_state["cycle_slider"] = st.session_state["_playback_cycle"]

    controls = st.columns([3, 1, 1, 1, 1])
    with controls[0]:
        cycle = st.slider(
            "Cycle displayed", first_cycle, last_cycle,
            key="cycle_slider",
            disabled=bool(st.session_state["_playback_playing"]),
        )
    with controls[1]:
        if st.button("Play", use_container_width=True):
            st.session_state["_playback_playing"] = True
    with controls[2]:
        if st.button("Pause", use_container_width=True):
            st.session_state["_playback_playing"] = False
    with controls[3]:
        if st.button("Reset", use_container_width=True):
            st.session_state["_playback_playing"] = False
            st.session_state["_playback_cycle"] = first_cycle
            st.rerun()
    with controls[4]:
        speed = st.selectbox("Speed", ["1x", "2x", "5x"], key="playback_speed")

    if not st.session_state["_playback_playing"]:
        st.session_state["_playback_cycle"] = int(cycle)
    else:
        cycle = int(st.session_state["_playback_cycle"])
    visible = trajectory.loc[trajectory.cycle.le(cycle)].copy()
    current = visible.iloc[-1]
    st.subheader(f"Unit {unit_id} · cycle {cycle} · horizon H={horizon}")
    _render_status(str(current.prediction_status), str(current.input_validity),
                   bool(current.telemetry_stale))

    first = st.columns(5)
    first[0].metric("Risk score", _safe_metric(current.risk_score))
    first[1].metric("Survival score", _safe_metric(current.survival_score))
    first[2].metric("Health score", _safe_metric(current.health_score, 1))
    first[2].caption("Visual only; depends on the selected horizon.")
    first[3].metric("Alert level", str(current.alert_level))
    first[4].metric("Maximum sensor age", f"{int(current.max_sensor_age_cycles)} cycles")

    second = st.columns(5)
    second[0].metric("Weibull risk", _safe_metric(current.risk_weibull))
    second[1].metric("XGBoost risk", _safe_metric(current.risk_xgboost))
    second[2].metric("Discrete hazard risk", _safe_metric(current.risk_hazard_discrete))
    second[3].metric("Anomaly score", _safe_metric(current.anomaly_score))
    second[3].caption("Abnormality indicator, not failure probability.")
    second[4].metric("Disagreement", _safe_metric(current.disagreement))
    second[4].caption("Model divergence, not confidence interval.")

    reason_codes = json.loads(current.reason_codes)
    st.write("**Reason codes:**", ", ".join(reason_codes) if reason_codes else "none")
    st.write(
        "**Telemetry transmitted this cycle:**", bool(current.telemetry_transmitted),
        "· **Sensors/settings:**", ", ".join(current.transmitted_sensors) if current.transmitted_sensors else "none",
        "· **Bytes accumulated:**", int(current.bytes_accumulated),
    )
    if retrospective:
        st.warning(
            "Retrospective mode: true RUL is evaluation information and would not be available in production."
        )
        retro = st.columns(3)
        retro[0].metric("True RUL (evaluation only)", int(current.rul_evaluation))
        retro[1].metric("First alert cycle", result.summary["first_alert_cycle"] or "none")
        retro[2].metric("Lead time (evaluation only)", result.summary["lead_time_evaluation"] or "unavailable")

    charts = st.tabs([
        "Risk and models", "Anomaly and alerts", "Telemetry and age",
        "Important sensors", "Comparisons", "Operational history", "Engineering assurance",
    ])
    with charts[0]:
        st.markdown(f"#### Risk over time — H={horizon}")
        st.line_chart(visible.set_index("cycle")[["risk_score", "risk_score_full_telemetry"]])
        st.markdown(f"#### Probability by model — H={horizon}")
        st.line_chart(visible.set_index("cycle")[[
            "risk_weibull", "risk_xgboost", "risk_hazard_discrete", "risk_final",
        ]])
    with charts[1]:
        st.markdown("#### Anomaly score")
        st.line_chart(visible.set_index("cycle")[["anomaly_score"]])
        alert_numbers = visible[["cycle", "alert_level"]].copy()
        alert_numbers["alert_level_numeric"] = alert_numbers.alert_level.map({
            "normal": 0, "atenção": 1, "alerta": 2, "crítico": 3,
            "indisponível": np.nan,
        })
        st.markdown("#### Alert level: 0 normal, 1 atenção, 2 alerta, 3 crítico")
        st.line_chart(alert_numbers.set_index("cycle")[["alert_level_numeric"]])
        if retrospective:
            st.metric("Lead time (evaluation only)", result.summary["lead_time_evaluation"] or "unavailable")
    with charts[2]:
        st.markdown("#### Telemetry transmitted and cumulative bytes")
        communication = visible[["cycle", "telemetry_transmitted", "bytes_accumulated",
                                 "full_bytes_accumulated"]].copy()
        communication["telemetry_transmitted"] = communication.telemetry_transmitted.astype(int)
        st.line_chart(communication.set_index("cycle"))
        st.markdown("#### Age of data used by the prediction")
        st.line_chart(visible.set_index("cycle")[["max_sensor_age_cycles"]])
        st.dataframe(visible.tail(20)[[
            "cycle", "telemetry_transmitted", "estimated_bytes", "bytes_accumulated",
            "max_sensor_age_cycles", "telemetry_stale", "prediction_status",
        ]], hide_index=True, use_container_width=True)
    with charts[3]:
        sensors = json.loads(current.important_sensors)
        if sensors:
            sensor_frame = pd.DataFrame(sensors).set_index("source_signal")
            st.bar_chart(sensor_frame[["relative_magnitude"]])
            st.dataframe(sensor_frame, use_container_width=True)
        else:
            st.info("Local sensor attribution is unavailable for filtered telemetry; full-stream SHAP is not reused as if it explained the filtered prediction.")
    with charts[4]:
        st.markdown("#### Model comparison on the same validation units")
        st.dataframe(result.model_comparison, hide_index=True, use_container_width=True)
        lead_time = result.model_comparison.loc[
            result.model_comparison.horizon.eq(horizon), ["model", "lead_time"]
        ].dropna()
        if not lead_time.empty:
            st.markdown(f"#### Median lead time by model — H={horizon} (retrospective validation)")
            st.bar_chart(lead_time.set_index("model"))
        st.markdown(f"#### Telemetry-policy comparison — fusion H={horizon}")
        st.dataframe(result.telemetry_comparison, hide_index=True, use_container_width=True)
    with charts[5]:
        st.header("Operational history")
        st.caption(
            "Persisted records returned by FastAPI for the selected unit and horizon. "
            "They are not recomputed by the dashboard."
        )
        if os.environ.get("APP_BACKEND", "api").strip().lower() != "api":
            st.info("Operational history is available only when APP_BACKEND=api.")
        else:
            try:
                stored_predictions = pd.DataFrame(service.historical_predictions(
                    unit_id=selected_unit, horizon=int(horizon), limit=100,
                ))
                stored_alerts = pd.DataFrame(service.historical_alerts(
                    unit_id=selected_unit, horizon=int(horizon), limit=100,
                ))
            except APIClientError as exc:
                st.error(f"Operational history unavailable: {exc}")
            else:
                if not stored_predictions.empty:
                    stored_predictions = stored_predictions.loc[
                        stored_predictions["model_name"].eq(str(model))
                    ].sort_values(["cycle", "created_at"])
                st.markdown("#### Persisted predictions")
                if stored_predictions.empty:
                    st.info("No persisted predictions are available for this selected scenario.")
                else:
                    prediction_columns = [
                        column for column in (
                            "unit_id", "cycle", "horizon", "model_name", "risk_score",
                            "prediction_status", "created_at",
                        ) if column in stored_predictions.columns
                    ]
                    st.dataframe(
                        stored_predictions[prediction_columns].tail(20),
                        hide_index=True,
                        use_container_width=True,
                    )
                    plot_data = stored_predictions.dropna(subset=["risk_score"])
                    if len(plot_data) >= 2:
                        st.markdown("#### Persisted risk score by cycle")
                        st.line_chart(plot_data.set_index("cycle")[["risk_score"]])

                st.markdown("#### Persisted alerts")
                if stored_alerts.empty:
                    st.info("No persisted alerts are available for this selected unit and horizon.")
                else:
                    alert_columns = [
                        column for column in (
                            "unit_id", "cycle", "horizon", "alert_level", "risk_score", "created_at",
                        ) if column in stored_alerts.columns
                    ]
                    st.dataframe(
                        stored_alerts[alert_columns].tail(20),
                        hide_index=True,
                        use_container_width=True,
                    )
    with charts[6]:
        st.header("Engineering assurance")
        st.warning(result.assurance["claim"])
        assurance_columns = st.columns(4)
        assurance_columns[0].metric("Model version", result.assurance["model_version"])
        assurance_columns[1].metric("Configuration version", result.assurance["application_version"])
        assurance_columns[2].metric("Horizon", f"H={result.assurance['horizon']}")
        assurance_columns[3].metric("Traceability rows", result.assurance["traceability_rows"])
        st.markdown("#### Data manifest")
        st.json(result.assurance["data_manifest"])
        st.markdown("#### Requirement status")
        st.json(result.assurance["requirements"])
        st.markdown("#### Open assumptions")
        st.dataframe(pd.DataFrame(result.assurance["open_assumptions"]),
                     hide_index=True, use_container_width=True)
        st.markdown("#### Telemetry status")
        st.json(result.assurance["telemetry_status"])
        st.markdown("#### Limitations")
        for limitation in result.assurance["limitations"]:
            st.write(f"- {limitation}")
        st.caption("This section summarizes engineering evidence and configuration. It is not a certificate of safety, airworthiness, or standards compliance.")

    if st.session_state.get("_playback_playing"):
        if cycle >= last_cycle:
            st.session_state["_playback_playing"] = False
        else:
            interval_seconds = {"1x": 1.0, "2x": 0.5, "5x": 0.2}[speed]
            time.sleep(interval_seconds)
            next_cycle = min(cycle + 1, last_cycle)
            st.session_state["_playback_cycle"] = next_cycle
            st.rerun()


main()
