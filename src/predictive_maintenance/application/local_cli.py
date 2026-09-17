"""Command-line client for the local FD001 integrated application."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

from predictive_maintenance.application.local_service import (
    ApplicationSelection,
    LocalApplicationError,
    LocalApplicationService,
)


def _write_trajectory(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        frame.to_parquet(path, index=False)
    elif suffix == ".csv":
        frame.to_csv(path, index=False)
    elif suffix == ".json":
        path.write_text(frame.to_json(orient="records", force_ascii=False, indent=2),
                        encoding="utf-8")
    else:
        raise ValueError("output extension must be .parquet, .csv or .json")


def _json_default(value):
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if pd.isna(value):
        return None
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path("."))
    parser.add_argument("--config", type=Path, default=Path("configs/local_app.toml"))
    parser.add_argument("--unit-id", type=int)
    parser.add_argument("--horizon", type=int, default=30)
    parser.add_argument("--model", default="fusion")
    parser.add_argument("--telemetry-policy", default="full")
    parser.add_argument("--cadence", default="each_cycle")
    parser.add_argument("--retrospective", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--show-cycles", type=int, default=5)
    parser.add_argument("--list-options", action="store_true")
    args = parser.parse_args()
    try:
        service = LocalApplicationService(args.project_root, args.config)
        if args.list_options:
            print(json.dumps({
                "unit_ids": service.available_units, "horizons": service.horizons,
                "models": service.models, "telemetry_policies": service.policies,
                "inference_cadences": service.inference_cadences,
            }, ensure_ascii=False, indent=2))
            return
        if args.unit_id is None:
            parser.error("--unit-id is required unless --list-options is used")
        if args.show_cycles < 1:
            parser.error("--show-cycles must be positive")
        result = service.run(ApplicationSelection(
            unit_id=args.unit_id, horizon=args.horizon, model=args.model,
            telemetry_policy=args.telemetry_policy,
            inference_cadence=args.cadence, retrospective=args.retrospective,
        ))
        if args.output is not None:
            _write_trajectory(result.trajectory, args.output)
        visible = [
            "cycle", "horizon", "risk_score", "survival_score", "health_score",
            "alert_level", "risk_weibull", "risk_xgboost", "risk_hazard_discrete",
            "risk_final", "anomaly_score", "disagreement", "prediction_status",
            "input_validity", "telemetry_stale", "max_sensor_age_cycles",
            "reason_codes", "telemetry_transmitted", "estimated_bytes",
            "bytes_accumulated",
        ]
        if args.retrospective:
            visible.append("rul_evaluation")
        payload = {
            "summary": result.summary,
            "recent_cycles": result.trajectory.loc[:, visible].tail(args.show_cycles).to_dict("records"),
            "output": str(args.output.resolve()) if args.output is not None else None,
            "assurance_claim": result.assurance["claim"],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default,
                         allow_nan=False))
    except (LocalApplicationError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
