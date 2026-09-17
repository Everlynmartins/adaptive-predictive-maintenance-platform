"""Local command that validates and partitions the official FD001 training file."""

import argparse
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import tomllib
from typing import Any, Sequence

from predictive_maintenance.data.cmapss import CMAPSSFD001Loader
from predictive_maintenance.data.reporting import build_fd001_report
from predictive_maintenance.data.splitting import (
    UnitSplitConfig,
    split_by_unit,
)


@dataclass(frozen=True)
class FD001PreparationConfig:
    dataset_name: str
    training_file: str
    official_test_file: str
    official_rul_file: str
    split: UnitSplitConfig


def load_preparation_config(path: Path) -> FD001PreparationConfig:
    with Path(path).open("rb") as stream:
        raw = tomllib.load(stream)
    dataset = raw["dataset"]
    split = raw["split"]
    if dataset["name"] != "FD001":
        raise ValueError("this command accepts only the FD001 configuration")
    split_config = UnitSplitConfig(
        seed=int(split["seed"]),
        train_fraction=float(split["train_fraction"]),
        validation_fraction=float(split["validation_fraction"]),
        test_fraction=float(split["test_fraction"]),
    )
    split_config.validate()
    return FD001PreparationConfig(
        dataset_name=dataset["name"],
        training_file=dataset["training_file"],
        official_test_file=dataset["official_test_file"],
        official_rul_file=dataset["official_rul_file"],
        split=split_config,
    )


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def prepare_fd001(
    config_path: Path,
    raw_dir: Path,
    processed_dir: Path,
) -> dict[str, Any]:
    """Validate official training telemetry and persist unit-level internal splits."""

    config = load_preparation_config(config_path)
    raw_dir = Path(raw_dir)
    source = raw_dir / config.training_file
    if not source.is_file():
        required = raw_dir / config.training_file
        raise FileNotFoundError(
            f"official FD001 training file is absent: {required}. "
            f"Place {config.training_file}, {config.official_test_file}, and "
            f"{config.official_rul_file} in {raw_dir}. The latter two files are "
            "reserved for later official evaluation and are not read by this command."
        )

    frame = CMAPSSFD001Loader().load_frame(source)
    partition = split_by_unit(frame, config.split)
    report = build_fd001_report(frame)

    output_dir = Path(processed_dir) / config.dataset_name.lower()
    output_dir.mkdir(parents=True, exist_ok=True)
    frames = {
        "train": partition.train,
        "validation": partition.validation,
        "test_internal": partition.test_internal,
    }
    temporary_parquets: list[tuple[Path, Path]] = []
    for name, subset in frames.items():
        destination = output_dir / f"{name}.parquet"
        temporary = destination.with_suffix(".parquet.tmp")
        subset.to_parquet(temporary, index=False, engine="pyarrow")
        temporary_parquets.append((temporary, destination))
    for temporary, destination in temporary_parquets:
        temporary.replace(destination)

    official_paths = {
        "official_test": raw_dir / config.official_test_file,
        "official_rul": raw_dir / config.official_rul_file,
    }
    manifest = {
        "dataset": config.dataset_name,
        "source": {
            "file": config.training_file,
            "sha256": _file_sha256(source),
        },
        "split": asdict(config.split),
        "units": {
            "train": list(partition.train_units),
            "validation": list(partition.validation_units),
            "test_internal": list(partition.test_internal_units),
        },
        "rows": {name: int(len(subset)) for name, subset in frames.items()},
        "official_evaluation": {
            "used": False,
            "files_present": {
                name: path.is_file() for name, path in official_paths.items()
            },
        },
    }
    _write_json(output_dir / "split_manifest.json", manifest)
    _write_json(output_dir / "validation_report.json", report)
    return {"report": report, "manifest": manifest, "output_dir": str(output_dir)}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and prepare internal unit-level splits from FD001 train data."
    )
    parser.add_argument("--config", type=Path, default=Path("configs/fd001.toml"))
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--processed-dir", type=Path, default=Path("data/processed"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    arguments = parser.parse_args(argv)
    try:
        result = prepare_fd001(
            arguments.config,
            arguments.raw_dir,
            arguments.processed_dir,
        )
    except (FileNotFoundError, KeyError, TypeError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

