"""Application service for the local FD001 demonstrator.

The service owns orchestration, contracts and artifact validation. UI and CLI
clients only select options and render the returned tables.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import tomllib
from typing import Any

import numpy as np
import pandas as pd

from predictive_maintenance.core.records import FeatureRecord
from predictive_maintenance.features.causal import CausalTelemetryFeatures
from predictive_maintenance.models.anomaly.isolation_forest import IsolationForestAnomalyDetector
from predictive_maintenance.models.ml.classical import RandomForestRiskModel


class LocalApplicationError(RuntimeError):
    """Base error visible to local application clients."""


class ConfigurationUnavailableError(LocalApplicationError):
    """Required configuration is absent or invalid."""


class ArtifactCompatibilityError(LocalApplicationError):
    """A persisted artifact does not implement the expected contract."""


@dataclass(frozen=True)
class ApplicationSelection:
    unit_id: int
    horizon: int
    model: str
    telemetry_policy: str
    inference_cadence: str
    retrospective: bool = False


@dataclass(frozen=True)
class ApplicationResult:
    selection: ApplicationSelection
    trajectory: pd.DataFrame
    summary: dict[str, Any]
    assurance: dict[str, Any]
    model_comparison: pd.DataFrame
    telemetry_comparison: pd.DataFrame


class LocalApplicationService:
    """Read-only facade over reviewed local artifacts for the FD001 demo."""

    def __init__(
        self,
        project_root: Path = Path("."),
        config_path: Path = Path("configs/local_app.toml"),
    ) -> None:
        self.root = project_root.resolve()
        self.config_path = (
            config_path.resolve() if config_path.is_absolute()
            else (self.root / config_path).resolve()
        )
        if not self.config_path.exists():
            raise ConfigurationUnavailableError(
                f"application configuration is missing: {self.config_path}"
            )
        try:
            self.config = tomllib.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigurationUnavailableError(f"invalid application configuration: {exc}") from exc
        self._validate_config()
        app = self.config["application"]
        self.models = tuple(str(value) for value in app["allowed_models"])
        self.filtered_models = frozenset(str(value) for value in app["filtered_models"])
        self.policies = tuple(str(value) for value in app["allowed_policies"])
        self.paths = {
            name: (self.root / value).resolve()
            for name, value in self.config["paths"].items()
        }
        for name in (
            "split_manifest", "validation_data", "explanations",
            "telemetry_artifacts", "telemetry_metrics", "telemetry_metrics_by_unit",
            "model_calibration", "requirements", "assumptions", "traceability",
            "fusion_policy", "telemetry_thresholds",
        ):
            if not self.paths[name].exists():
                raise ConfigurationUnavailableError(
                    f"configured application dependency is missing: {name}={self.paths[name]}"
                )
        self.manifest = self._read_json(self.paths["split_manifest"])
        self._units = tuple(int(value) for value in self.manifest["units"]["validation"])
        self._cache: dict[tuple[str, int], pd.DataFrame] = {}

    @property
    def available_units(self) -> tuple[int, ...]:
        return self._units

    @property
    def horizons(self) -> tuple[int, ...]:
        return tuple(int(value) for value in self.config["application"]["horizons"])

    @property
    def inference_cadences(self) -> tuple[str, ...]:
        return tuple(self.config["application"]["allowed_inference_cadences"])

    def run(self, selection: ApplicationSelection) -> ApplicationResult:
        self._validate_selection(selection)
        states = self._receiver_states(selection.telemetry_policy, selection.unit_id)
        packets = self._packets(selection.telemetry_policy, selection.unit_id)
        full_packets = self._packets("full", selection.unit_id)
        base = states.merge(packets, on=["unit_id", "cycle"], how="left", validate="one_to_one")
        base = base.merge(
            full_packets[["unit_id", "cycle", "estimated_bytes"]].rename(
                columns={"estimated_bytes": "full_estimated_bytes"}
            ),
            on=["unit_id", "cycle"], how="left", validate="one_to_one",
        )
        base["estimated_bytes"] = base.estimated_bytes.fillna(0).astype(int)
        base["full_estimated_bytes"] = base.full_estimated_bytes.fillna(0).astype(int)
        base["bytes_accumulated"] = base.estimated_bytes.cumsum()
        base["full_bytes_accumulated"] = base.full_estimated_bytes.cumsum()
        base["telemetry_transmitted"] = base.packet_received.astype(bool)
        base["transmitted_sensors"] = base.transmitted_sensors.apply(
            lambda value: [] if not isinstance(value, (list, tuple, np.ndarray)) else list(value)
        )
        base["send_reason"] = base.send_reason.fillna("not_transmitted")
        final_cycle = None
        if selection.retrospective:
            final_cycle = int(self._unit_validation(selection.unit_id).cycle.max())
            base["rul_evaluation"] = final_cycle - base.cycle

        components = self._components(
            selection.telemetry_policy, selection.unit_id, selection.horizon,
        )
        frame = base.merge(components, on=["unit_id", "cycle"], how="left", validate="one_to_one")
        for column in ("risk_weibull", "risk_xgboost", "risk_hazard_discrete", "risk_final"):
            numeric = pd.to_numeric(frame[column], errors="coerce")
            frame[column] = numeric.where(np.isfinite(numeric) & numeric.between(0.0, 1.0))
        for column in ("anomaly_score", "disagreement"):
            numeric = pd.to_numeric(frame[column], errors="coerce")
            frame[column] = numeric.where(np.isfinite(numeric) & numeric.ge(0.0))
        selected = self._selected_model_scores(selection)
        selected = self._enforce_probability_contract(selected)
        frame = frame.merge(
            selected[["unit_id", "cycle", "risk_score", "model_status",
                      "model_input_validity", "invalid_probability_artifact"]],
            on=["unit_id", "cycle"], how="left", validate="one_to_one",
        )
        full_selected = self._selected_model_scores(ApplicationSelection(
            unit_id=selection.unit_id, horizon=selection.horizon, model=selection.model,
            telemetry_policy="full", inference_cadence="each_cycle",
        ))
        full_selected = self._enforce_probability_contract(full_selected).rename(
            columns={"risk_score": "risk_score_full_telemetry"}
        )
        frame = frame.merge(
            full_selected[["unit_id", "cycle", "risk_score_full_telemetry"]],
            on=["unit_id", "cycle"], how="left", validate="one_to_one",
        )

        unsupported = selection.telemetry_policy != "full" and selection.model not in self.filtered_models
        frame["prediction_status"] = frame.model_status.map(
            {"available": "valid", "valid": "valid", "degraded": "degraded",
             "unavailable": "unavailable"}
        ).fillna("unavailable")
        frame["input_validity"] = frame.model_input_validity.fillna("invalid")
        frame.loc[frame.max_sensor_age_cycles.gt(0) & frame.prediction_status.eq("valid"),
                  "prediction_status"] = "degraded"
        frame.loc[frame.telemetry_stale, ["prediction_status", "input_validity"]] = [
            "unavailable", "stale",
        ]
        if selection.inference_cadence == "on_transmission":
            frame.loc[~frame.packet_received, "prediction_status"] = "unavailable"
        if unsupported:
            frame["risk_score"] = np.nan
            frame["prediction_status"] = "unavailable"
            frame["input_validity"] = "invalid"
        frame.loc[frame.prediction_status.eq("unavailable"), "risk_score"] = np.nan
        frame["survival_score"] = 1.0 - frame.risk_score
        frame["health_score"] = 100.0 * frame.survival_score
        frame["health_score_semantics"] = "visual_horizon_dependent"
        frame["horizon"] = selection.horizon
        frame["model"] = selection.model
        frame["telemetry_policy"] = selection.telemetry_policy
        frame["inference_cadence"] = selection.inference_cadence
        frame["risk_delta_from_full"] = frame.risk_score - frame.risk_score_full_telemetry

        alert_levels = self._alert_levels(selection.telemetry_policy, selection.unit_id,
                                          selection.inference_cadence)
        frame = frame.merge(alert_levels, on=["unit_id", "cycle"], how="left", validate="one_to_one")
        frame["reason_codes"] = self._reason_codes(frame, selection, unsupported)
        frame["important_sensors"] = frame.apply(
            lambda row: row.top_sensors if selection.telemetry_policy == "full" else "[]", axis=1,
        )
        frame["prediction_status"] = frame.prediction_status.astype(str)
        frame["input_validity"] = frame.input_validity.astype(str)

        emitted = frame.loc[frame.alert_level.isin(["atenção", "alerta", "crítico"])]
        first_alert = int(emitted.cycle.min()) if not emitted.empty else None
        lead_time = (
            final_cycle - first_alert
            if final_cycle is not None and first_alert is not None else None
        )
        summary = {
            "unit_id": selection.unit_id, "horizon": selection.horizon,
            "model": selection.model, "telemetry_policy": selection.telemetry_policy,
            "inference_cadence": selection.inference_cadence,
            "cycles": len(frame), "final_cycle_evaluation": final_cycle,
            "first_alert_cycle": first_alert,
            "lead_time_evaluation": lead_time,
            "valid_fraction": float(frame.prediction_status.eq("valid").mean()),
            "degraded_fraction": float(frame.prediction_status.eq("degraded").mean()),
            "unavailable_fraction": float(frame.prediction_status.eq("unavailable").mean()),
            "stale_fraction": float(frame.telemetry_stale.mean()),
            "bytes_accumulated": int(frame.bytes_accumulated.iloc[-1]),
            "full_bytes_accumulated": int(frame.full_bytes_accumulated.iloc[-1]),
            "byte_reduction_fraction": 1.0 - (
                float(frame.bytes_accumulated.iloc[-1]) /
                float(frame.full_bytes_accumulated.iloc[-1])
            ),
            "retrospective": selection.retrospective,
            "rul_warning": self.config["contracts"]["rul_statement"],
        }
        assurance = self.engineering_assurance(selection, frame)
        return ApplicationResult(
            selection=selection, trajectory=frame, summary=summary,
            assurance=assurance, model_comparison=self.model_comparison(),
            telemetry_comparison=self.telemetry_comparison(selection.horizon),
        )

    def model_comparison(self) -> pd.DataFrame:
        calibration = self._read_parquet_contract(
            self.paths["model_calibration"],
            {"model", "horizon", "brier_score"},
        )
        metric_sources = self._probability_metric_catalog()
        rows: list[dict[str, Any]] = []
        for model in self.models:
            for horizon in self.horizons:
                metrics = metric_sources.get((model, horizon), {})
                brier_row = calibration.loc[
                    calibration.model.eq(model) & calibration.horizon.eq(horizon)
                ]
                temporal = self._temporal_model_metrics(model, horizon)
                rows.append({
                    "model": model, "horizon": horizon,
                    "pr_auc": metrics.get("pr_auc"),
                    "brier": (float(brier_row.brier_score.iloc[0]) if len(brier_row)
                              else metrics.get("brier")),
                    "roc_auc": metrics.get("roc_auc"),
                    "lead_time": temporal.get("lead_time"),
                    "false_alerts_per_unit": temporal.get("false_alerts_per_unit"),
                    "inference_ms_per_origin": temporal.get("inference_ms_per_origin"),
                    "timing_scope": temporal.get("timing_scope", "not isolated"),
                    "approximate_complexity": self._complexity(model),
                })
        return pd.DataFrame(rows)

    def telemetry_comparison(self, horizon: int) -> pd.DataFrame:
        metrics = self._read_parquet_contract(
            self.paths["telemetry_metrics"],
            {"regime", "partition", "policy_id", "model", "horizon",
             "bytes_relative", "byte_reduction_fraction", "pr_auc_average_precision",
             "brier_score", "roc_auc", "median_lead_time",
             "false_alert_episodes_per_unit", "degraded_fraction",
             "unavailable_fraction", "stale_fraction", "maximum_data_age_cycles"},
        )
        selected = metrics.loc[
            metrics.regime.eq("full_trained") & metrics.partition.eq("validation")
            & metrics.model.eq("fusion") & metrics.horizon.eq(horizon)
        ].copy()
        columns = [
            "policy_id", "bytes_relative", "byte_reduction_fraction",
            "pr_auc_average_precision", "brier_score", "roc_auc",
            "median_lead_time", "false_alert_episodes_per_unit",
            "degraded_fraction", "unavailable_fraction", "stale_fraction",
            "maximum_data_age_cycles",
        ]
        return selected.loc[:, columns].sort_values("bytes_relative").reset_index(drop=True)

    def engineering_assurance(
        self, selection: ApplicationSelection, trajectory: pd.DataFrame,
    ) -> dict[str, Any]:
        requirements_text = self.paths["requirements"].read_text(encoding="utf-8")
        requirement_status = {
            status: len(re.findall(rf"^- status: {status}$", requirements_text, re.MULTILINE))
            for status in ("verified", "partial", "planned")
        }
        assumptions_text = self.paths["assumptions"].read_text(encoding="utf-8")
        open_assumptions = []
        for line in assumptions_text.splitlines():
            if re.match(r"^\| ASM\d{3} \|", line) and line.rstrip().endswith("| open |"):
                cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
                open_assumptions.append({"assumption_id": cells[0], "statement": cells[1]})
        traceability = pd.read_csv(self.paths["traceability"], dtype=str).fillna("")
        return {
            "claim": "Engineering organization aid; not a safety certificate or compliance claim.",
            "certification_claim": bool(self.config["scope"]["certification_claim"]),
            "application_version": self.config["application"]["version"],
            "project_version": self.config["application"]["project_version"],
            "configuration_sha256": sha256(self.config_path.read_bytes()).hexdigest(),
            "model": selection.model,
            "model_version": self._model_version(selection.model),
            "horizon": selection.horizon,
            "data_manifest": {
                "dataset": self.manifest["dataset"],
                "partition": "validation", "units": len(self._units),
                "rows": self.manifest["rows"]["validation"],
                "source_sha256": self.manifest["source"]["sha256"],
            },
            "requirements": requirement_status,
            "traceability_rows": len(traceability),
            "open_assumptions": open_assumptions,
            "limitations": [
                "C-MAPSS FD001 is a simulated benchmark.",
                "Validation evidence does not demonstrate operational safety or industrial generalization.",
                "The local application replays frozen offline artifacts; it is not a live monitoring system.",
                "Alert thresholds are experimental demonstrator settings, not aeronautical limits.",
            ],
            "telemetry_status": {
                "policy": selection.telemetry_policy,
                "cadence": selection.inference_cadence,
                "stale_fraction": float(trajectory.telemetry_stale.mean()),
                "maximum_age_cycles": int(trajectory.max_sensor_age_cycles.max()),
                "degraded_fraction": float(trajectory.prediction_status.eq("degraded").mean()),
                "unavailable_fraction": float(trajectory.prediction_status.eq("unavailable").mean()),
            },
            "scope": dict(self.config["scope"]),
        }

    def _components(self, policy: str, unit_id: int, horizon: int) -> pd.DataFrame:
        explanation = self._read_parquet_contract(
            self.paths["explanations"],
            {"unit_id", "cycle", "horizon", "risk_weibull", "risk_xgboost",
             "risk_hazard_discrete", "risk_final", "anomaly_score", "disagreement",
             "top_sensors", "reason_codes"},
        )
        full = explanation.loc[
            explanation.unit_id.eq(unit_id) & explanation.horizon.eq(horizon)
        ].copy()
        full = full.rename(columns={"reason_codes": "full_reason_codes"})
        columns = [
            "unit_id", "cycle", "risk_weibull", "risk_xgboost",
            "risk_hazard_discrete", "risk_final", "anomaly_score", "disagreement",
            "top_sensors", "full_reason_codes",
        ]
        if policy == "full":
            return full.loc[:, columns]
        prediction = self._policy_predictions(policy, unit_id)
        current = prediction.loc[prediction.horizon.eq(horizon)]
        pivot = current.pivot(index=["unit_id", "cycle"], columns="model", values="risk_score").reset_index()
        pivot = pivot.rename(columns={
            "xgboost": "risk_xgboost", "discrete_hazard": "risk_hazard_discrete",
            "fusion": "risk_final",
        })
        output = full[["unit_id", "cycle", "risk_weibull"]].merge(
            pivot, on=["unit_id", "cycle"], how="left", validate="one_to_one",
        )
        auxiliary = self._filtered_auxiliary(policy, unit_id, horizon, output)
        output = output.merge(auxiliary, on=["unit_id", "cycle"], how="left", validate="one_to_one")
        output["top_sensors"] = "[]"
        output["full_reason_codes"] = "[]"
        return output.loc[:, columns]

    def _filtered_auxiliary(
        self, policy: str, unit_id: int, horizon: int, components: pd.DataFrame,
    ) -> pd.DataFrame:
        key = (policy, unit_id)
        if key not in self._cache:
            policy_root = self.paths["telemetry_artifacts"] / policy
            values = self._read_parquet_contract(
                policy_root / "receiver_values.parquet", {"unit_id", "cycle"},
            )
            observed = self._read_parquet_contract(
                policy_root / "receiver_observed_mask.parquet", {"unit_id", "cycle"},
            )
            states = self._receiver_states(policy, unit_id)
            values = values.loc[values.unit_id.eq(unit_id)].reset_index(drop=True)
            observed = observed.loc[observed.unit_id.eq(unit_id)].reset_index(drop=True)
            operational = values.loc[values.cycle.lt(values.cycle.max())].reset_index(drop=True)
            observed_operational = observed.loc[observed.cycle.lt(observed.cycle.max())].reset_index(drop=True)

            feature_engineer = CausalTelemetryFeatures.load(
                self.root / "reports/classical_ml/artifacts/causal_feature_engineer.json"
            )
            missing = set(feature_engineer.raw_columns) - set(operational.columns)
            if missing:
                raise ArtifactCompatibilityError(
                    f"receiver artifact lacks required frozen features: {sorted(missing)}"
                )
            engineered = feature_engineer.transform_receiver_frame(
                operational[["unit_id", "cycle", *feature_engineer.raw_columns]],
                observed_operational[list(feature_engineer.raw_columns)],
            )
            records = self._feature_records(engineered, feature_engineer.feature_names)
            rf_scores: dict[int, np.ndarray] = {}
            for local_horizon in self.horizons:
                model = RandomForestRiskModel.load(
                    self.root / f"reports/classical_ml/artifacts/models/random_forest_h{local_horizon}.joblib"
                )
                rf_scores[local_horizon] = np.asarray([
                    item.risk_score for item in model.predict_risk(records, horizon=local_horizon)
                ], dtype=float)

            anomaly_engineer = CausalTelemetryFeatures.load(
                self.root / "reports/anomaly_detection/artifacts/causal_feature_engineer.json"
            )
            anomaly_features = anomaly_engineer.transform_receiver_frame(
                operational[["unit_id", "cycle", *anomaly_engineer.raw_columns]],
                observed_operational[list(anomaly_engineer.raw_columns)],
            )
            anomaly_records = self._feature_records(anomaly_features, anomaly_engineer.feature_names)
            detector = IsolationForestAnomalyDetector.load(
                self.root / "reports/anomaly_detection/artifacts/isolation_forest.joblib"
            )
            raw = detector.raw_anomaly_score(anomaly_records)
            anomaly = np.searchsorted(
                detector.healthy_raw_scores, raw, side="right",
            ) / len(detector.healthy_raw_scores)
            cached = operational[["unit_id", "cycle"]].copy()
            cached["anomaly_score"] = anomaly
            for local_horizon in self.horizons:
                cached[f"risk_random_forest_h{local_horizon}"] = rf_scores[local_horizon]
            cached = cached.merge(
                states[["unit_id", "cycle", "telemetry_stale"]],
                on=["unit_id", "cycle"], validate="one_to_one",
            )
            cached.loc[cached.telemetry_stale, "anomaly_score"] = np.nan
            self._cache[key] = cached
        cached = self._cache[key]
        output = components[["unit_id", "cycle"]].merge(
            cached[["unit_id", "cycle", "anomaly_score", f"risk_random_forest_h{horizon}"]],
            on=["unit_id", "cycle"], how="left", validate="one_to_one",
        )
        risk = components[["risk_weibull", "risk_xgboost", "risk_hazard_discrete"]].copy()
        risk["risk_random_forest"] = output[f"risk_random_forest_h{horizon}"]
        output["disagreement"] = risk.max(axis=1, skipna=False) - risk.min(axis=1, skipna=False)
        return output[["unit_id", "cycle", "anomaly_score", "disagreement"]]

    def _selected_model_scores(self, selection: ApplicationSelection) -> pd.DataFrame:
        if selection.telemetry_policy != "full" and selection.model not in self.filtered_models:
            states = self._receiver_states(selection.telemetry_policy, selection.unit_id)
            frame = states[["unit_id", "cycle"]].copy()
            frame["risk_score"] = np.nan
            frame["model_status"] = "unavailable"
            frame["model_input_validity"] = "invalid"
            return frame
        if selection.model in self.filtered_models:
            predictions = self._policy_predictions(selection.telemetry_policy, selection.unit_id)
            return predictions.loc[
                predictions.model.eq(selection.model) & predictions.horizon.eq(selection.horizon),
                ["unit_id", "cycle", "risk_score", "prediction_status", "input_validity"],
            ].rename(columns={
                "prediction_status": "model_status", "input_validity": "model_input_validity",
            }).reset_index(drop=True)

        path, query = self._full_model_source(selection.model)
        source = self._read_parquet_contract(
            path, {"unit_id", "cycle", "horizon", "risk_score"},
        )
        if query is not None:
            source = source.query(query)
        frame = source.loc[
            source.unit_id.eq(selection.unit_id) & source.horizon.eq(selection.horizon)
        ].copy()
        if frame.empty:
            raise ArtifactCompatibilityError(
                f"model artifact has no rows for {selection.model}, unit={selection.unit_id}, H={selection.horizon}"
            )
        frame["model_status"] = frame.get("prediction_status", "available")
        frame["model_input_validity"] = frame.get("input_validity", "valid")
        return frame[["unit_id", "cycle", "risk_score", "model_status", "model_input_validity"]]

    def _alert_levels(self, policy: str, unit_id: int, cadence: str) -> pd.DataFrame:
        predictions = self._policy_predictions(policy, unit_id)
        fusion = predictions.loc[predictions.model.eq("fusion")].pivot(
            index=["unit_id", "cycle"], columns="horizon", values="risk_score"
        ).reset_index()
        state = self._receiver_states(policy, unit_id)
        frame = state[["unit_id", "cycle", "packet_received", "telemetry_stale"]].merge(
            fusion, on=["unit_id", "cycle"], how="left", validate="one_to_one",
        )
        raw = tomllib.loads(self.paths["fusion_policy"].read_text(encoding="utf-8"))
        attention = float(raw["thresholds"]["attention"])
        alert = float(raw["thresholds"]["alert"])
        critical = float(raw["thresholds"]["critical"])
        persistence = int(raw["persistence"]["cycles"])
        run = np.zeros(4, dtype=int)
        names = np.asarray(["normal", "atenção", "alerta", "crítico"], dtype=object)
        levels: list[str] = []
        ordered = frame[["unit_id", "cycle", "packet_received", "telemetry_stale", 15, 30]]
        for _, _, packet_received, telemetry_stale, p15_raw, p30_raw in ordered.itertuples(
            index=False, name=None,
        ):
            due = cadence == "each_cycle" or bool(packet_received)
            probabilities = np.asarray([p15_raw, p30_raw], dtype=float)
            if (bool(telemetry_stale) or not due
                    or not np.isfinite(probabilities).all()
                    or (probabilities < 0.0).any() or (probabilities > 1.0).any()):
                run[:] = 0
                levels.append("indisponível")
                continue
            p15 = float(p15_raw)
            p30 = float(p30_raw)
            candidate = max(int(p30 >= attention), 2 * int(p30 >= alert), 3 * int(p15 >= critical))
            for level in (1, 2, 3):
                run[level] = run[level] + 1 if candidate >= level else 0
            eligible = [level for level in (1, 2, 3) if run[level] >= persistence]
            levels.append(str(names[max(eligible, default=0)]))
        return frame[["unit_id", "cycle"]].assign(
            alert_level=levels, alert_source="frozen_fusion_policy",
        )

    def _reason_codes(
        self, frame: pd.DataFrame, selection: ApplicationSelection, unsupported: bool,
    ) -> pd.Series:
        threshold_payload = self._read_json(self.paths["telemetry_thresholds"])
        threshold = threshold_payload["thresholds"].get(selection.model, {}).get(str(selection.horizon))
        values: list[str] = []
        for row in frame.itertuples(index=False):
            codes: list[str] = []
            if selection.telemetry_policy == "full":
                try:
                    codes.extend(json.loads(row.full_reason_codes))
                except (TypeError, json.JSONDecodeError):
                    codes.append("EXPLANATION_ARTIFACT_INVALID")
            else:
                codes.append("FILTERED_STREAM_LOCAL_SHAP_NOT_AVAILABLE")
            if unsupported:
                codes.append("MODEL_NOT_AVAILABLE_FOR_TELEMETRY_POLICY")
            if bool(row.invalid_probability_artifact):
                codes.append("INVALID_RISK_SCORE_ARTIFACT")
            if bool(row.telemetry_stale):
                codes.append("TELEMETRY_STALE")
            elif int(row.max_sensor_age_cycles) > 0:
                codes.append(f"HELD_TELEMETRY_MAX_AGE_{int(row.max_sensor_age_cycles)}_CYCLES")
            if selection.inference_cadence == "on_transmission" and not bool(row.packet_received):
                codes.append("INFERENCE_NOT_DUE_NO_NEW_TELEMETRY")
            if threshold is not None and np.isfinite(row.risk_score) and row.risk_score >= threshold:
                codes.append("RISK_ABOVE_EXPERIMENTAL_MODEL_THRESHOLD")
            if row.prediction_status == "unavailable":
                codes.append("PREDICTION_UNAVAILABLE_EXPLICIT")
            values.append(json.dumps(list(dict.fromkeys(codes)), ensure_ascii=False))
        return pd.Series(values, index=frame.index, dtype="string")

    def _receiver_states(self, policy: str, unit_id: int) -> pd.DataFrame:
        path = self.paths["telemetry_artifacts"] / policy / "receiver_states.parquet"
        states = self._read_parquet_contract(
            path, {"unit_id", "cycle", "packet_received", "telemetry_stale",
                   "max_sensor_age_cycles", "inference_due"},
        )
        states = states.loc[states.unit_id.eq(unit_id)].sort_values("cycle").reset_index(drop=True)
        if states.empty:
            raise ArtifactCompatibilityError(f"receiver state has no unit_id={unit_id}")
        return states.loc[states.cycle.lt(states.cycle.max())].reset_index(drop=True)

    def _packets(self, policy: str, unit_id: int) -> pd.DataFrame:
        path = self.paths["telemetry_artifacts"] / policy / "packets.parquet"
        packets = self._read_parquet_contract(
            path, {"unit_id", "cycle", "transmitted_sensors", "estimated_bytes", "send_reason"},
        )
        return packets.loc[packets.unit_id.eq(unit_id), [
            "unit_id", "cycle", "transmitted_sensors", "estimated_bytes", "send_reason",
        ]].copy()

    def _policy_predictions(self, policy: str, unit_id: int) -> pd.DataFrame:
        path = self.paths["telemetry_artifacts"] / policy / "validation_predictions.parquet"
        frame = self._read_parquet_contract(
            path, {"unit_id", "cycle", "horizon", "risk_score", "prediction_status",
                   "input_validity", "model", "telemetry_stale", "max_sensor_age_cycles"},
        )
        return frame.loc[frame.unit_id.eq(unit_id)].copy()

    def _unit_validation(self, unit_id: int) -> pd.DataFrame:
        frame = self._read_parquet_contract(
            self.paths["validation_data"], {"unit_id", "cycle"},
        )
        return frame.loc[frame.unit_id.eq(unit_id)].copy()

    def _full_model_source(self, model: str) -> tuple[Path, str | None]:
        mapping = {
            "weibull": (self.root / "reports/weibull/artifacts/validation_predictions.parquet", None),
            "random_forest": (self.root / "reports/classical_ml/artifacts/validation_predictions.parquet", "algorithm == 'random_forest'"),
            "tcn": (self.root / "reports/tcn/artifacts/validation_predictions.parquet", None),
            "transformer": (self.root / "reports/transformer/artifacts/validation_predictions.parquet", None),
        }
        return mapping[model]

    def _probability_metric_catalog(self) -> dict[tuple[str, int], dict[str, float]]:
        catalog: dict[tuple[str, int], dict[str, float]] = {}
        classical = self._read_json(self.root / "reports/classical_ml/metrics.json")["results"]["validation"]
        for model in ("random_forest", "xgboost"):
            for horizon in self.horizons:
                item = classical[model][str(horizon)]
                catalog[(model, horizon)] = self._metric_triplet(item)
        hazard = self._read_json(self.root / "reports/discrete_hazard/metrics.json")["validation"]
        weibull = self._read_json(self.root / "reports/weibull/metrics.json")["validation"]
        tcn = self._read_json(self.root / "reports/tcn/metrics.json")["metrics"]
        transformer = self._read_json(self.root / "reports/transformer/metrics.json")["metrics"]
        fusion = self._read_json(self.root / "reports/fusion/metrics.json")["validation"]["stacking"]
        for horizon in self.horizons:
            catalog[("discrete_hazard", horizon)] = self._metric_triplet(hazard[str(horizon)])
            catalog[("weibull", horizon)] = self._metric_triplet(
                weibull[str(horizon)]["overall_by_observation"]
            )
            catalog[("tcn", horizon)] = self._metric_triplet(tcn[str(horizon)])
            catalog[("transformer", horizon)] = self._metric_triplet(transformer[str(horizon)])
            catalog[("fusion", horizon)] = self._metric_triplet(fusion[str(horizon)])
        return catalog

    @staticmethod
    def _metric_triplet(item: dict[str, Any]) -> dict[str, float]:
        return {
            "pr_auc": float(item["pr_auc_average_precision"]),
            "brier": float(item["brier_score"]),
            "roc_auc": float(item["roc_auc"]),
        }

    def _temporal_model_metrics(self, model: str, horizon: int) -> dict[str, Any]:
        if model in {"xgboost", "discrete_hazard", "fusion"}:
            metrics = self._read_parquet_contract(
                self.paths["telemetry_metrics"],
                {"regime", "policy_id", "model", "horizon", "median_lead_time",
                 "false_alert_episodes_per_unit", "inference_time_seconds", "opportunities"},
            )
            row = metrics.loc[
                metrics.regime.eq("full_trained") & metrics.policy_id.eq("full")
                & metrics.model.eq(model) & metrics.horizon.eq(horizon)
            ].iloc[0]
            return {
                "lead_time": float(row.median_lead_time),
                "false_alerts_per_unit": float(row.false_alert_episodes_per_unit),
                "inference_ms_per_origin": None,
                "timing_scope": "shared pipeline timing; model timing not isolated",
            }
        if model in {"tcn", "transformer"}:
            payload = self._read_json(self.root / f"reports/{model}/metrics.json")
            alert = payload["metrics"][str(horizon)]["alert_summary"]
            return {
                "lead_time": float(alert["median_lead_time"]),
                "false_alerts_per_unit": float(alert["mean_false_alert_episodes_per_unit"]),
                "inference_ms_per_origin": float(payload["model"]["validation_inference_ms_per_origin"]),
                "timing_scope": "measured local CPU validation run",
            }
        return {"lead_time": None, "false_alerts_per_unit": None,
                "inference_ms_per_origin": None, "timing_scope": "not recorded"}

    @staticmethod
    def _complexity(model: str) -> str:
        return {
            "weibull": "2 fitted parameters",
            "random_forest": "200 trees per horizon",
            "xgboost": "200 boosted trees per horizon",
            "discrete_hazard": "324 features + age/step logistic terms",
            "fusion": "logistic meta-model + 4 base probabilities + anomaly covariate",
            "tcn": "3,570 trainable parameters",
            "transformer": "17,762 trainable parameters",
        }[model]

    def _model_version(self, model: str) -> str:
        cards = {
            "fusion": "reports/fusion/model_card.json",
            "xgboost": "reports/classical_ml/xgboost_model_card.json",
            "discrete_hazard": "reports/discrete_hazard/model_card.json",
            "weibull": "reports/weibull/model_card.json",
            "random_forest": "reports/classical_ml/random_forest_model_card.json",
            "tcn": "reports/tcn/model_card.json",
            "transformer": "reports/transformer/model_card.json",
        }
        payload = self._read_json(self.root / cards[model])
        version = payload.get("model_version")
        if not isinstance(version, str) or not version.strip():
            raise ArtifactCompatibilityError(f"model card has no version: {cards[model]}")
        return version

    @staticmethod
    def _enforce_probability_contract(frame: pd.DataFrame) -> pd.DataFrame:
        """Turn invalid persisted probabilities into explicit unavailable rows."""
        output = frame.copy()
        numeric = pd.to_numeric(output["risk_score"], errors="coerce")
        invalid = output["risk_score"].notna() & (
            ~np.isfinite(numeric) | numeric.lt(0.0) | numeric.gt(1.0)
        )
        output["risk_score"] = numeric
        output["invalid_probability_artifact"] = invalid.astype(bool)
        output.loc[invalid, "risk_score"] = np.nan
        output.loc[invalid, "model_status"] = "unavailable"
        output.loc[invalid, "model_input_validity"] = "invalid"
        return output

    def _validate_selection(self, selection: ApplicationSelection) -> None:
        if type(selection.unit_id) is not int or selection.unit_id not in self._units:
            raise ValueError(f"unit_id must be one of {list(self._units)}")
        if type(selection.horizon) is not int or selection.horizon not in self.horizons:
            raise ValueError(f"horizon must be one of {list(self.horizons)}")
        if selection.model not in self.models:
            raise ValueError(f"model must be one of {list(self.models)}")
        if selection.telemetry_policy not in self.policies:
            raise ValueError(f"telemetry_policy must be one of {list(self.policies)}")
        if selection.inference_cadence not in self.inference_cadences:
            raise ValueError(
                f"inference_cadence must be one of {list(self.inference_cadences)}"
            )

    def _validate_config(self) -> None:
        try:
            app = self.config["application"]
            scope = self.config["scope"]
            horizons = tuple(int(value) for value in app["horizons"])
            cadences = tuple(app["allowed_inference_cadences"])
            models = tuple(str(value) for value in app["allowed_models"])
            filtered_models = frozenset(str(value) for value in app["filtered_models"])
            policies = tuple(str(value) for value in app["allowed_policies"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigurationUnavailableError(f"incomplete local app configuration: {exc}") from exc
        if horizons != (15, 30):
            raise ConfigurationUnavailableError("local app requires reviewed horizons [15, 30]")
        if cadences != ("each_cycle", "on_transmission"):
            raise ConfigurationUnavailableError("local app cadence contract is incompatible")
        expected_models = {
            "fusion", "xgboost", "discrete_hazard", "weibull",
            "random_forest", "tcn", "transformer",
        }
        if set(models) != expected_models or len(models) != len(expected_models):
            raise ConfigurationUnavailableError("local app model set is incompatible")
        if not filtered_models <= set(models):
            raise ConfigurationUnavailableError("filtered model set is incompatible")
        if not policies or policies[0] != "full" or len(set(policies)) != len(policies):
            raise ConfigurationUnavailableError("local app telemetry policy set is incompatible")
        forbidden = ("test_internal_read", "official_test_read", "official_rul_read",
                     "models_retrained", "certification_claim")
        if any(bool(scope.get(name)) for name in forbidden):
            raise ConfigurationUnavailableError("local app scope enables a prohibited action or claim")

    @staticmethod
    def _feature_records(frame: pd.DataFrame, names: tuple[str, ...]) -> list[FeatureRecord]:
        return [FeatureRecord(
            unit_id=str(int(row.unit_id)), cycle=int(row.cycle),
            values={name: float(getattr(row, name)) for name in names},
        ) for row in frame.itertuples(index=False)]

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ArtifactCompatibilityError(f"cannot read JSON artifact {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ArtifactCompatibilityError(f"JSON artifact must contain an object: {path}")
        return payload

    @staticmethod
    def _read_parquet_contract(path: Path, required: set[str]) -> pd.DataFrame:
        if not path.exists():
            raise ArtifactCompatibilityError(f"required artifact is missing: {path}")
        try:
            frame = pd.read_parquet(path)
        except Exception as exc:
            raise ArtifactCompatibilityError(f"cannot read Parquet artifact {path}: {exc}") from exc
        missing = required - set(frame.columns)
        if frame.empty or missing:
            raise ArtifactCompatibilityError(
                f"incompatible artifact {path}; missing={sorted(missing)}, empty={frame.empty}"
            )
        return frame
