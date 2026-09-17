"""Reproducible structural audit for closing the local FD001 phase.

The audit reads existing evidence and validation artifacts. It does not fit a
model, change a threshold, or open either reserved NASA evaluation file.
"""

from __future__ import annotations

import argparse
import ast
import csv
from hashlib import sha256
import importlib.metadata
import json
from pathlib import Path
import platform
import re
import tomllib
from typing import Any

from predictive_maintenance.application.local_service import (
    ApplicationSelection,
    LocalApplicationService,
)
from predictive_maintenance.core.causality import FORBIDDEN_FEATURE_NAMES


CONFIG_FILES = (
    "fd001.toml", "fd001_eda.toml", "weibull.toml", "classical_ml.toml",
    "discrete_hazard.toml", "anomaly_detection.toml", "fusion.toml",
    "fusion_alert_policy.toml", "telemetry_filtering.toml",
    "telemetry_reduction_experiment.toml", "tcn.toml", "transformer.toml",
    "explainability_uncertainty.toml", "local_app.toml", "final_assurance.toml",
)
MODEL_CARDS = {
    "weibull": "reports/weibull/model_card.json",
    "random_forest": "reports/classical_ml/random_forest_model_card.json",
    "xgboost": "reports/classical_ml/xgboost_model_card.json",
    "discrete_hazard": "reports/discrete_hazard/model_card.json",
    "isolation_forest": "reports/anomaly_detection/model_card.json",
    "fusion": "reports/fusion/model_card.json",
    "tcn": "reports/tcn/model_card.json",
    "transformer": "reports/transformer/model_card.json",
}
MODEL_ARTIFACTS = {
    "weibull": "reports/weibull/artifacts/weibull_2p_model.json",
    "random_forest_h15": "reports/classical_ml/artifacts/models/random_forest_h15.joblib",
    "random_forest_h30": "reports/classical_ml/artifacts/models/random_forest_h30.joblib",
    "xgboost_h15": "reports/classical_ml/artifacts/models/xgboost_h15.joblib",
    "xgboost_h30": "reports/classical_ml/artifacts/models/xgboost_h30.joblib",
    "discrete_hazard": "reports/discrete_hazard/artifacts/model.joblib",
    "isolation_forest": "reports/anomaly_detection/artifacts/isolation_forest.joblib",
    "fusion_h15": "reports/fusion/artifacts/stacking_h15.joblib",
    "fusion_h30": "reports/fusion/artifacts/stacking_h30.joblib",
    "tcn": "reports/tcn/artifacts/tcn_model.pt",
    "transformer": "reports/transformer/artifacts/transformer_model.pt",
}
DEPENDENCIES = (
    "numpy", "pandas", "pyarrow", "scikit-learn", "xgboost", "scipy",
    "joblib", "threadpoolctl", "torch", "shap", "streamlit",
)


def _hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _requirements(path: Path) -> list[dict[str, str]]:
    text = path.read_text(encoding="utf-8")
    output: list[dict[str, str]] = []
    for block in re.split(r"(?=^## SRQ\d{3}\s*$)", text, flags=re.MULTILINE):
        heading = re.match(r"^## (SRQ\d{3})", block)
        if not heading:
            continue
        record = {"heading": heading.group(1)}
        for field in (
            "requirement_id", "statement", "source", "rationale",
            "validation_method", "verification_method", "status",
        ):
            match = re.search(rf"^- {field}:\s*(.*)$", block, flags=re.MULTILINE)
            record[field] = match.group(1).strip() if match else ""
        output.append(record)
    return output


def _assumptions(path: Path) -> list[dict[str, str]]:
    fields = ("assumption_id", "statement", "reason", "impact_if_false", "evidence", "status")
    output = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not re.match(r"^\| ASM\d{3} \|", line):
            continue
        values = [value.strip() for value in line.strip().strip("|").split("|")]
        if len(values) == len(fields):
            output.append(dict(zip(fields, values, strict=True)))
    return output


def _known_tests(root: Path) -> set[str]:
    output: set[str] = set()
    for path in (root / "tests").glob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for method in node.body:
                if isinstance(method, ast.FunctionDef) and method.name.startswith("test_"):
                    output.add(f"{path.stem}.{node.name}.{method.name}")
    return output


def _git_identity(root: Path) -> str:
    head = root / ".git" / "HEAD"
    if not head.exists():
        return "unavailable: no .git/HEAD"
    value = head.read_text(encoding="utf-8").strip()
    if value.startswith("ref: "):
        reference = root / ".git" / value.removeprefix("ref: ")
        if not reference.exists():
            return "unavailable: repository has no commit"
        return reference.read_text(encoding="utf-8").strip()
    return value


def run_audit(root: Path, config_path: Path) -> dict[str, Any]:
    root = root.resolve()
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    guards = config["scope_guards"]
    if any(bool(value) for value in guards.values()):
        raise ValueError("final assurance scope guard enables a prohibited action or claim")

    requirements = _requirements(root / config["assurance"]["requirements_document"])
    required_fields = {
        "requirement_id", "statement", "source", "rationale",
        "validation_method", "verification_method", "status",
    }
    missing_requirement_fields = [
        f"{item['heading']}:{field}" for item in requirements
        for field in required_fields if not item[field]
    ]
    with (root / config["assurance"]["traceability_matrix"]).open(
        encoding="utf-8-sig", newline="",
    ) as stream:
        traceability = list(csv.DictReader(stream))
    requirement_ids = [item["requirement_id"] for item in requirements]
    matrix_ids = [item["requirement_id"] for item in traceability]
    known_tests = _known_tests(root)
    missing_tests = sorted({
        test_id for row in traceability
        for test_id in (value.strip() for value in row["test_ids"].split(";"))
        if test_id and test_id != "—" and test_id not in known_tests
    })

    assumptions = _assumptions(root / config["assurance"]["assumptions_document"])
    allowed_assumption_status = {"open", "confirmed", "invalidated"}
    invalid_assumptions = [
        item["assumption_id"] for item in assumptions
        if not item["impact_if_false"] or item["status"] not in allowed_assumption_status
    ]

    split = json.loads((root / "data/processed/fd001/split_manifest.json").read_text(encoding="utf-8"))
    unit_sets = {name: set(values) for name, values in split["units"].items()}
    split_overlap = {
        f"{left}:{right}": sorted(unit_sets[left] & unit_sets[right])
        for left, right in (("train", "validation"), ("train", "test_internal"),
                            ("validation", "test_internal"))
    }

    feature_manifest = json.loads(
        (root / "reports/classical_ml/artifacts/feature_manifest.json").read_text(encoding="utf-8")
    )
    feature_names = [str(value) for value in feature_manifest["feature_names"]]
    forbidden = {name.casefold() for name in FORBIDDEN_FEATURE_NAMES}
    forbidden_features = sorted(
        name for name in feature_names
        if name.casefold() in forbidden or name.split("__", 1)[0].casefold() in forbidden
    )

    cards: dict[str, Any] = {}
    for name, relative in MODEL_CARDS.items():
        path = root / relative
        payload = json.loads(path.read_text(encoding="utf-8"))
        cards[name] = {
            "path": relative,
            "model_name": payload.get("model_name"),
            "model_version": payload.get("model_version"),
            "sha256": _hash(path),
        }

    oof = json.loads((root / "reports/fusion/oof_audit.json").read_text(encoding="utf-8"))
    oof_overlap = [fold for fold in oof["meta_folds"] if fold.get("overlap")]

    service = LocalApplicationService(root)
    simulation = []
    for unit_id in config["simulation"]["unit_ids"]:
        result = service.run(ApplicationSelection(
            unit_id=int(unit_id), horizon=int(config["simulation"]["horizon"]),
            model=str(config["simulation"]["model"]),
            telemetry_policy=str(config["simulation"]["telemetry_policy"]),
            inference_cadence=str(config["simulation"]["inference_cadence"]),
            retrospective=bool(config["simulation"]["retrospective"]),
        ))
        terminal_cycle = int(result.summary["final_cycle_evaluation"])
        simulation.append({
            "unit_id": int(unit_id),
            "first_cycle": int(result.trajectory.cycle.iloc[0]),
            "last_prediction_cycle": int(result.trajectory.cycle.iloc[-1]),
            "terminal_cycle_evaluation": terminal_cycle,
            "prediction_origins": int(len(result.trajectory)),
            "last_rul_evaluation": int(result.trajectory.rul_evaluation.iloc[-1]),
            "valid": int(result.trajectory.prediction_status.eq("valid").sum()),
            "degraded": int(result.trajectory.prediction_status.eq("degraded").sum()),
            "unavailable": int(result.trajectory.prediction_status.eq("unavailable").sum()),
            "risk_bounds_ok": bool(result.trajectory.risk_score.between(0.0, 1.0).all()),
            "event_boundary_ok": int(result.trajectory.cycle.iloc[-1]) + 1 == terminal_cycle,
        })

    config_hashes = {
        f"configs/{name}": _hash(root / "configs" / name) for name in CONFIG_FILES
    }
    artifact_hashes = {
        name: {"path": relative, "sha256": _hash(root / relative)}
        for name, relative in MODEL_ARTIFACTS.items()
    }
    dependency_versions = {
        name: importlib.metadata.version(name) for name in DEPENDENCIES
    }
    source_cache_directories = [
        path.relative_to(root).as_posix()
        for base in (root / "src", root / "tests")
        for path in base.rglob("__pycache__")
    ]

    checks = {
        "requirements_have_required_fields": not missing_requirement_fields,
        "requirements_unique": len(requirement_ids) == len(set(requirement_ids)),
        "matrix_order_matches_requirements": matrix_ids == requirement_ids,
        "verified_rows_have_implementation_evidence_and_tests": all(
            row["implementation"] and row["verification_evidence"] and row["test_ids"]
            for row in traceability if row["status"] == "verified"
        ),
        "all_referenced_tests_exist": not missing_tests,
        "assumptions_have_impact_and_allowed_status": not invalid_assumptions,
        "unit_partitions_are_disjoint": not any(split_overlap.values()),
        "feature_manifest_has_no_forbidden_features": not forbidden_features,
        "fusion_meta_folds_have_no_unit_overlap": not oof_overlap,
        "fusion_uses_train_oof": oof.get("test_internal_read") is False,
        "official_test_not_used_by_fusion": oof.get("official_test_read") is False,
        "model_cards_are_versioned": all(item["model_version"] for item in cards.values()),
        "multi_unit_simulation_reaches_event_boundary": all(
            item["event_boundary_ok"] and item["risk_bounds_ok"] for item in simulation
        ),
        "no_source_cache_artifacts": not source_cache_directories,
    }
    return {
        "audit_name": "FD001 local phase final assurance audit",
        "project_version": config["assurance"]["project_version"],
        "scope": config["assurance"]["scope"],
        "claim_boundary": "benchmark-only engineering evidence; no certification or operational safety claim",
        "code_identity": _git_identity(root),
        "environment": {"python": platform.python_version(), **dependency_versions},
        "checks": checks,
        "findings": {
            "missing_requirement_fields": missing_requirement_fields,
            "missing_test_references": missing_tests,
            "invalid_assumptions": invalid_assumptions,
            "split_overlap": split_overlap,
            "forbidden_features": forbidden_features,
            "oof_overlap_count": len(oof_overlap),
            "source_cache_directories": source_cache_directories,
        },
        "requirement_status": {
            status: sum(item["status"] == status for item in requirements)
            for status in ("verified", "partial", "planned")
        },
        "assumption_status": {
            status: sum(item["status"] == status for item in assumptions)
            for status in ("open", "confirmed", "invalidated")
        },
        "configuration_sha256": config_hashes,
        "model_cards": cards,
        "model_artifacts": artifact_hashes,
        "multi_unit_simulation": simulation,
        "scope_guards": guards,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path("."))
    parser.add_argument("--config", type=Path, default=Path("configs/final_assurance.toml"))
    args = parser.parse_args()
    root = args.project_root.resolve()
    config_path = args.config if args.config.is_absolute() else root / args.config
    payload = run_audit(root, config_path)
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    output = root / config["output"]["audit_results"]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    failed = [name for name, passed in payload["checks"].items() if not passed]
    print(json.dumps({"output": str(output), "failed_checks": failed}, ensure_ascii=False))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
