"""Reproduce training-only FD001 EDA and offline development targets."""

import argparse
from dataclasses import asdict
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import tomllib

import pandas as pd

from predictive_maintenance.analysis.fd001 import summarize_training
from predictive_maintenance.analysis.plots import plot_training
from predictive_maintenance.analysis.report import write_eda_report
from predictive_maintenance.data.targets import HorizonConfig, build_evaluation_targets
from predictive_maintenance.data.validation import validate_fd001


def load_development(processed: Path) -> dict[str, pd.DataFrame]:
    """Read two explicit Parquets only; fail on modified membership or overlap."""
    manifest = json.loads((processed / "split_manifest.json").read_text(encoding="utf-8"))
    if manifest["dataset"] != "FD001" or manifest["source"]["file"] != "train_FD001.txt":
        raise ValueError("development targets require complete FD001 training trajectories")
    declared = {name: set(manifest["units"][name])
                for name in ("train", "validation", "test_internal")}
    if any(declared[a] & declared[b] for a, b in
           (("train", "validation"), ("train", "test_internal"), ("validation", "test_internal"))):
        raise ValueError("unit overlap in split manifest")
    frames = {}
    for name in ("train", "validation"):
        frame = validate_fd001(pd.read_parquet(processed / f"{name}.parquet"))
        if set(frame.unit_id) != declared[name] or len(frame) != manifest["rows"][name]:
            raise ValueError(f"{name}: Parquet does not match split manifest")
        frames[name] = frame
    return frames


def run_eda(
    processed: Path = Path("data/processed/fd001"),
    config_path: Path = Path("configs/fd001_eda.toml"),
    reports: Path = Path("reports"),
) -> dict:
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    horizons = HorizonConfig(**config["targets"])
    eda = config["eda"]
    if not 0 < eda["near_constant_dominant_fraction"] <= 1:
        raise ValueError("dominant fraction must be in (0, 1]")
    if type(eda["near_constant_max_unique"]) is not int or eda["near_constant_max_unique"] < 1:
        raise ValueError("max unique must be a positive integer")
    if not 0 <= eda["trend_min_absolute_median_rho"] <= 1 or not 0 <= eda["trend_min_direction_agreement"] <= 1:
        raise ValueError("trend heuristics must be in [0, 1]")
    if type(eda["normalized_life_points"]) is not int or eda["normalized_life_points"] < 2:
        raise ValueError("normalized life requires at least two grid points")

    inputs = [processed / "train.parquet", processed / "validation.parquet",
              processed / "split_manifest.json", config_path]
    hashes = {str(p): sha256(p.read_bytes()).hexdigest() for p in inputs}
    frames = load_development(processed)
    summary = summarize_training(
        frames["train"], dominant_fraction=eda["near_constant_dominant_fraction"],
        max_unique=eda["near_constant_max_unique"],
        trend_min_rho=eda["trend_min_absolute_median_rho"],
        trend_min_agreement=eda["trend_min_direction_agreement"],
    )
    # No validation telemetry, targets or test data is passed to analysis/plots.
    target_dir = processed / "evaluation_targets"
    target_dir.mkdir(parents=True, exist_ok=True)
    for name, frame in frames.items():
        targets = build_evaluation_targets(frame, horizons, complete_run_to_failure=True)
        targets.to_parquet(target_dir / f"{name}_targets.parquet", index=False)
        if name == "train":
            summary["training_targets"] = {
                "rows": len(targets), "operational_rows": int(targets.is_operational.sum()),
                "failure_positive": int(targets.failure_within_horizon.sum()),
                "critical_positive": int(targets.failure_within_critical_horizon.sum()),
                "operational_failure_positive": int(
                    (targets.is_operational & targets.failure_within_horizon).sum()),
                "operational_critical_positive": int(
                    (targets.is_operational & targets.failure_within_critical_horizon).sum()),
            }
    provenance = {
        "package_version": version("adaptive-predictive-maintenance"),
        "input_sha256": hashes, "configuration": config,
        "eda_partition": "train", "target_partitions": ["train", "validation"],
        "test_data_read": False, "complete_run_to_failure_required": True,
        "horizons": asdict(horizons), "event_convention": "0 <= RUL <= H",
        "runtime_versions": {name: version(name) for name in ("pandas", "numpy", "matplotlib", "pyarrow")},
    }
    (reports / "eda").mkdir(parents=True, exist_ok=True)
    figures = plot_training(
        frames["train"], summary, reports / "eda" / "figures",
        failure_horizon=horizons.failure_horizon,
        critical_horizon=horizons.critical_horizon,
        normalized_points=eda["normalized_life_points"],
    )
    for path in inputs:
        if sha256(path.read_bytes()).hexdigest() != hashes[str(path)]:
            raise RuntimeError(f"input changed during execution: {path}")
    (target_dir / "metadata.json").write_text(
        json.dumps(provenance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (reports / "eda" / "summary.json").write_text(
        json.dumps({"provenance": provenance, "statistics": summary}, indent=2,
                   ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
    )
    write_eda_report(reports / "eda_report.md", summary, horizons, eda, figures)
    return {"report": str(reports / "eda_report.md"), "engines_analyzed": summary["engines"],
            "rows_analyzed": summary["rows"], "constant_sensors": summary["constant_sensors"],
            "near_constant_sensors": summary["near_constant_sensors"],
            "trend_candidates": summary["trend_candidates"], "figures": len(figures)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--processed-dir", type=Path, default=Path("data/processed/fd001"))
    parser.add_argument("--config", type=Path, default=Path("configs/fd001_eda.toml"))
    parser.add_argument("--reports-dir", type=Path, default=Path("reports"))
    args = parser.parse_args()
    print(json.dumps(run_eda(args.processed_dir, args.config, args.reports_dir),
                     indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
