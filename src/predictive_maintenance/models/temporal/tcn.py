"""Small causal Temporal Convolutional Network for horizon risk estimation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from math import isfinite
from pathlib import Path
import random
import re
from typing import Sequence, Self

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F
from torch.utils.data import DataLoader, Dataset

from predictive_maintenance.core.causality import validate_feature_names
from predictive_maintenance.core.records import FeatureRecord, RiskPrediction, TargetRecord
from predictive_maintenance.models.interfaces import RiskModel


@dataclass(frozen=True)
class TCNConfig:
    model_name: str = "tcn"
    model_version: str = "1.0.0"
    horizons: tuple[int, int] = (15, 30)
    sequence_length: int = 30
    channels: tuple[int, ...] = (16, 16)
    kernel_size: int = 3
    dropout: float = 0.10
    batch_size: int = 256
    learning_rate: float = 1.0e-3
    weight_decay: float = 1.0e-4
    max_epochs: int = 20
    patience: int = 4
    min_delta: float = 1.0e-4
    random_seed: int = 4701
    torch_threads: int = 2

    def __post_init__(self) -> None:
        if not self.model_name.strip() or not self.model_version.strip():
            raise ValueError("model name and version must be non-empty")
        if len(self.horizons) != 2 or tuple(sorted(self.horizons)) != self.horizons:
            raise ValueError("TCN currently requires two strictly ordered horizons")
        if any(type(value) is not int or value <= 0 for value in self.horizons):
            raise ValueError("horizons must be positive integers")
        if type(self.sequence_length) is not int or self.sequence_length < 2:
            raise ValueError("sequence_length must be at least two")
        if not self.channels or any(type(value) is not int or value <= 0 for value in self.channels):
            raise ValueError("channels must be positive integers")
        if type(self.kernel_size) is not int or self.kernel_size < 2:
            raise ValueError("kernel_size must be at least two")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("dropout must be in [0, 1)")
        if type(self.batch_size) is not int or self.batch_size < 1:
            raise ValueError("batch_size must be positive")
        if self.learning_rate <= 0 or self.weight_decay < 0:
            raise ValueError("optimizer parameters are invalid")
        if type(self.max_epochs) is not int or self.max_epochs < 1:
            raise ValueError("max_epochs must be positive")
        if type(self.patience) is not int or self.patience < 1:
            raise ValueError("patience must be positive")
        if self.min_delta < 0:
            raise ValueError("min_delta must be non-negative")
        if type(self.random_seed) is not int:
            raise ValueError("random_seed must be an integer")
        if type(self.torch_threads) is not int or self.torch_threads < 1:
            raise ValueError("torch_threads must be positive")


class CausalConv1d(nn.Module):
    """Conv1d whose output at t depends only on positions <= t."""

    def __init__(self, in_channels: int, out_channels: int, kernel_size: int,
                 dilation: int) -> None:
        super().__init__()
        self.left_padding = (kernel_size - 1) * dilation
        self.conv = nn.Conv1d(
            in_channels, out_channels, kernel_size=kernel_size,
            dilation=dilation, padding=0,
        )

    def forward(self, values: torch.Tensor) -> torch.Tensor:
        return self.conv(F.pad(values, (self.left_padding, 0)))


class TemporalBlock(nn.Module):
    def __init__(self, in_channels: int, out_channels: int, kernel_size: int,
                 dilation: int, dropout: float) -> None:
        super().__init__()
        self.conv1 = CausalConv1d(in_channels, out_channels, kernel_size, dilation)
        self.conv2 = CausalConv1d(out_channels, out_channels, kernel_size, dilation)
        self.dropout = nn.Dropout(dropout)
        self.activation = nn.ReLU()
        self.residual = (nn.Identity() if in_channels == out_channels
                         else nn.Conv1d(in_channels, out_channels, kernel_size=1))

    def forward(self, values: torch.Tensor) -> torch.Tensor:
        output = self.dropout(self.activation(self.conv1(values)))
        output = self.dropout(self.activation(self.conv2(output)))
        return self.activation(output + self.residual(values))


class SmallTCN(nn.Module):
    """Joint H15/H30 head with p(long) >= p(short) by construction."""

    def __init__(self, input_features: int, channels: Sequence[int], kernel_size: int,
                 dropout: float) -> None:
        super().__init__()
        blocks: list[nn.Module] = []
        previous = input_features
        for index, width in enumerate(channels):
            blocks.append(TemporalBlock(
                previous, int(width), kernel_size, dilation=2 ** index, dropout=dropout,
            ))
            previous = int(width)
        self.network = nn.Sequential(*blocks)
        self.head = nn.Linear(previous, 2)

    def forward(self, sequence: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        if sequence.ndim != 3 or mask.ndim != 2:
            raise ValueError("sequence and mask dimensions are invalid")
        if sequence.shape[:2] != mask.shape:
            raise ValueError("mask is not aligned to sequence")
        if not torch.all((mask == 0) | (mask == 1)):
            raise ValueError("mask must be binary")
        if torch.any(mask.sum(dim=1) < 1):
            raise ValueError("every sequence must contain an observed origin")
        if mask.shape[1] > 1 and torch.any(mask[:, 1:] < mask[:, :-1]):
            raise ValueError("mask must describe left padding followed by observations")
        masked = sequence * mask.unsqueeze(-1)
        hidden = self.network(masked.transpose(1, 2))
        logits = self.head(hidden[:, :, -1])
        p_short = torch.sigmoid(logits[:, 0])
        conditional_increment = torch.sigmoid(logits[:, 1])
        p_long = p_short + (1.0 - p_short) * conditional_increment
        return torch.stack((p_short, p_long), dim=1)


class _SequenceDataset(Dataset):
    def __init__(self, sequences: np.ndarray, masks: np.ndarray,
                 targets: np.ndarray | None = None, weights: np.ndarray | None = None) -> None:
        self.sequences = torch.as_tensor(sequences, dtype=torch.float32)
        self.masks = torch.as_tensor(masks, dtype=torch.float32)
        self.targets = None if targets is None else torch.as_tensor(targets, dtype=torch.float32)
        self.weights = None if weights is None else torch.as_tensor(weights, dtype=torch.float32)

    def __len__(self) -> int:
        return len(self.sequences)

    def __getitem__(self, index: int):
        result = [self.sequences[index], self.masks[index]]
        if self.targets is not None:
            result.append(self.targets[index])
        if self.weights is not None:
            result.append(self.weights[index])
        return tuple(result)


class TCNRiskModel(RiskModel):
    artifact_schema = "tcn-risk-model/v1"

    def __init__(self, config: TCNConfig, feature_names: Sequence[str]) -> None:
        if not feature_names or len(set(feature_names)) != len(feature_names):
            raise ValueError("feature_names must be non-empty and unique")
        validate_feature_names(feature_names)
        for name in feature_names:
            canonical = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
            if (canonical in {"target", "label", "event_cycle", "observed_end"}
                    or canonical.startswith(("target_", "label_"))
                    or canonical.endswith(("_target", "_label", "_at_future"))):
                raise ValueError(
                    f"retrospective or target field forbidden as TCN feature: {name}"
                )
        self.config = config
        self.feature_names = tuple(feature_names)
        self.mean = np.zeros(len(self.feature_names), dtype=float)
        self.scale = np.ones(len(self.feature_names), dtype=float)
        self.training_summary: dict[str, object] = {}
        self.training_history: list[dict[str, float | int]] = []
        self.network = SmallTCN(
            len(self.feature_names), self.config.channels,
            self.config.kernel_size, self.config.dropout,
        )
        self._fitted = False

    def fit(self, features: Sequence[FeatureRecord],
            targets: Sequence[TargetRecord] | None = None) -> Self:
        if not features or targets is None or len(features) != len(targets):
            raise ValueError("aligned non-empty features and targets are required")
        _set_determinism(self.config.random_seed, self.config.torch_threads)
        valid_matrix = self._matrix(features, strict=True)
        self._fit_normalizer(valid_matrix)
        sequences, masks, keys = self._sequence_arrays(features, allow_invalid=False)
        labels = self._labels_for_keys(keys, targets)
        weights = _unit_class_weights(keys, labels)
        self.network = self._new_network()
        self.training_history = self._train_fixed(sequences, masks, labels, weights,
                                                  epochs=self.config.max_epochs)
        self.training_summary = self._summary(keys, labels) | {
            "selected_epoch": self.config.max_epochs,
            "early_stopping_used": False,
            "device": self._device_name(),
            "parameter_count": self.parameter_count(),
        }
        self._fitted = True
        return self

    def fit_with_validation(
        self,
        features: Sequence[FeatureRecord],
        targets: Sequence[TargetRecord],
        validation_features: Sequence[FeatureRecord],
        validation_targets: Sequence[TargetRecord],
    ) -> Self:
        if (not features or not validation_features
                or len(features) != len(targets)
                or len(validation_features) != len(validation_targets)):
            raise ValueError("fit and early stopping partitions must be non-empty")
        fit_units = {record.unit_id for record in features}
        validation_units = {record.unit_id for record in validation_features}
        if fit_units & validation_units:
            raise ValueError("fit and early stopping partitions must be disjoint by unit_id")
        _set_determinism(self.config.random_seed, self.config.torch_threads)
        matrix = self._matrix(features, strict=True)
        self._fit_normalizer(matrix)
        train_seq, train_mask, train_keys = self._sequence_arrays(features, allow_invalid=False)
        val_seq, val_mask, val_keys = self._sequence_arrays(validation_features, allow_invalid=False)
        train_labels = self._labels_for_keys(train_keys, targets)
        val_labels = self._labels_for_keys(val_keys, validation_targets)
        train_weights = _unit_class_weights(train_keys, train_labels)
        self.network = self._new_network()
        history, best_epoch = self._train_early_stopping(
            train_seq, train_mask, train_labels, train_weights,
            val_seq, val_mask, val_labels,
        )
        self.training_history = history
        self.training_summary = self._summary(train_keys, train_labels) | {
            "early_stopping_rows": len(val_keys),
            "early_stopping_units": len({unit for unit, _ in val_keys}),
            "selected_epoch": best_epoch,
            "early_stopping_used": True,
            "device": self._device_name(),
            "parameter_count": self.parameter_count(),
        }
        self._fitted = True
        return self

    def predict_risk(self, features: Sequence[FeatureRecord], *, horizon: int) -> list[RiskPrediction]:
        if not self._fitted:
            raise RuntimeError("model must be fitted or loaded before prediction")
        if horizon not in self.config.horizons:
            raise ValueError(f"model supports only horizons {self.config.horizons}")
        if not features:
            return []
        sequences, masks, keys, available = self._sequence_arrays_with_status(features)
        scores_by_key: dict[tuple[str, int], float] = {}
        if len(sequences):
            probabilities = self._predict_arrays(sequences, masks)
            horizon_index = self.config.horizons.index(horizon)
            scores_by_key = {
                key: float(probabilities[index, horizon_index])
                for index, key in enumerate(keys)
            }
        results: list[RiskPrediction] = []
        for record, is_available, explanation in available:
            if is_available:
                score = scores_by_key[(record.unit_id, record.cycle)]
                results.append(RiskPrediction(
                    unit_id=record.unit_id, cycle=record.cycle, horizon=horizon,
                    risk_score=score,
                    model_name=self.config.model_name, model_version=self.config.model_version,
                    prediction_status="available", input_validity="valid",
                ))
            else:
                results.append(RiskPrediction(
                    unit_id=record.unit_id if str(record.unit_id).strip() else "invalid-unit",
                    cycle=record.cycle if type(record.cycle) is int and record.cycle > 0 else 1,
                    horizon=horizon, risk_score=None,
                    model_name=self.config.model_name, model_version=self.config.model_version,
                    prediction_status="unavailable", input_validity="invalid",
                    explanation=explanation or "invalid sequence input",
                ))
        return results

    def predict_probabilities(self, features: Sequence[FeatureRecord]) -> np.ndarray:
        """Return aligned H15/H30 probabilities for valid offline records."""
        if not self._fitted:
            raise RuntimeError("model must be fitted or loaded before prediction")
        sequences, masks, _, available = self._sequence_arrays_with_status(features)
        if not all(item[1] for item in available):
            raise ValueError("predict_probabilities requires every input sequence to be valid")
        return self._predict_arrays(sequences, masks)

    def save(self, path: Path) -> None:
        if not self._fitted:
            raise RuntimeError("cannot save an unfitted model")
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": self.artifact_schema,
            "configuration": asdict(self.config),
            "feature_names": list(self.feature_names),
            "normalization_mean": self.mean.tolist(),
            "normalization_scale": self.scale.tolist(),
            "training_summary": self.training_summary,
            "training_history": self.training_history,
            "state_dict": {name: tensor.detach().cpu() for name, tensor in self.network.state_dict().items()},
        }
        torch.save(payload, path)

    @classmethod
    def load(cls, path: Path) -> Self:
        try:
            payload = torch.load(path, map_location="cpu", weights_only=False)
        except TypeError:
            payload = torch.load(path, map_location="cpu")
        if not isinstance(payload, dict) or payload.get("schema") != cls.artifact_schema:
            raise ValueError("incompatible TCN artifact")
        raw = payload["configuration"]
        config = TCNConfig(
            model_name=str(raw["model_name"]), model_version=str(raw["model_version"]),
            horizons=tuple(int(value) for value in raw["horizons"]),
            sequence_length=int(raw["sequence_length"]),
            channels=tuple(int(value) for value in raw["channels"]),
            kernel_size=int(raw["kernel_size"]), dropout=float(raw["dropout"]),
            batch_size=int(raw["batch_size"]), learning_rate=float(raw["learning_rate"]),
            weight_decay=float(raw["weight_decay"]), max_epochs=int(raw["max_epochs"]),
            patience=int(raw["patience"]), min_delta=float(raw["min_delta"]),
            random_seed=int(raw["random_seed"]), torch_threads=int(raw["torch_threads"]),
        )
        instance = cls(config, payload["feature_names"])
        instance.mean = np.asarray(payload["normalization_mean"], dtype=float)
        instance.scale = np.asarray(payload["normalization_scale"], dtype=float)
        if instance.mean.shape != (len(instance.feature_names),) or instance.scale.shape != instance.mean.shape:
            raise ValueError("normalizer shape is incompatible with feature schema")
        if not np.isfinite(instance.mean).all() or not np.isfinite(instance.scale).all() or (instance.scale <= 0).any():
            raise ValueError("normalizer is invalid")
        instance.network.load_state_dict(payload["state_dict"], strict=True)
        instance.training_summary = dict(payload.get("training_summary", {}))
        instance.training_history = list(payload.get("training_history", []))
        instance.network.eval()
        instance._fitted = True
        return instance

    @staticmethod
    def artifact_hash(path: Path) -> str:
        return sha256(path.read_bytes()).hexdigest()

    def parameter_count(self) -> int:
        return int(sum(parameter.numel() for parameter in self.network.parameters()))

    def with_epochs(self, epochs: int) -> Self:
        return type(self)(replace(self.config, max_epochs=int(epochs)), self.feature_names)

    def _new_network(self) -> SmallTCN:
        return SmallTCN(len(self.feature_names), self.config.channels,
                        self.config.kernel_size, self.config.dropout)

    def _fit_normalizer(self, matrix: np.ndarray) -> None:
        self.mean = matrix.mean(axis=0)
        scale = matrix.std(axis=0, ddof=0)
        self.scale = np.where(scale > 1.0e-12, scale, 1.0)
        if not np.isfinite(self.mean).all() or not np.isfinite(self.scale).all():
            raise ValueError("normalization statistics are not finite")

    def _matrix(self, features: Sequence[FeatureRecord], *, strict: bool) -> np.ndarray:
        rows = []
        for record in features:
            reason = self._invalid_reason(record)
            if reason is not None:
                if strict:
                    raise ValueError(reason)
                continue
            rows.append([float(record.values[name]) for name in self.feature_names])
        if not rows:
            raise ValueError("no valid feature rows")
        return np.asarray(rows, dtype=float)

    def _invalid_reason(self, record: FeatureRecord) -> str | None:
        if not isinstance(record.unit_id, str) or not record.unit_id.strip():
            return "unit_id is invalid"
        if type(record.cycle) is not int or record.cycle <= 0:
            return "cycle is invalid"
        if set(record.values) != set(self.feature_names):
            return "feature schema is missing or incompatible"
        for name in self.feature_names:
            value = record.values[name]
            if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
                return f"feature {name} is not numeric"
            if not isfinite(float(value)):
                return f"feature {name} is not finite"
        return None

    def _sequence_arrays(self, features: Sequence[FeatureRecord], *, allow_invalid: bool):
        sequences, masks, keys, status = self._sequence_arrays_internal(features)
        if not allow_invalid and not all(item[1] for item in status):
            first = next(item[2] for item in status if not item[1])
            raise ValueError(first or "invalid sequence input")
        return sequences, masks, keys

    def _sequence_arrays_with_status(self, features: Sequence[FeatureRecord]):
        return self._sequence_arrays_internal(features)

    def _sequence_arrays_internal(self, features: Sequence[FeatureRecord]):
        by_unit: dict[str, list[tuple[int, FeatureRecord]]] = {}
        for original_index, record in enumerate(features):
            by_unit.setdefault(str(record.unit_id), []).append((original_index, record))
        output_sequence: list[np.ndarray] = []
        output_mask: list[np.ndarray] = []
        output_keys: list[tuple[str, int]] = []
        available_by_index: dict[int, tuple[FeatureRecord, bool, str | None]] = {}
        for _, indexed in by_unit.items():
            indexed.sort(key=lambda item: item[1].cycle)
            cycles = [item[1].cycle for item in indexed]
            if len(cycles) != len(set(cycles)):
                raise ValueError("duplicate cycle within unit")
            reasons = [self._invalid_reason(item[1]) for item in indexed]
            for local_index, (original_index, record) in enumerate(indexed):
                start = max(0, local_index - self.config.sequence_length + 1)
                window = indexed[start:local_index + 1]
                window_reasons = reasons[start:local_index + 1]
                invalid = next((reason for reason in window_reasons if reason is not None), None)
                if invalid is not None:
                    available_by_index[original_index] = (
                        record, False, f"sequence contains invalid observation: {invalid}",
                    )
                    continue
                values = np.asarray([
                    [float(item[1].values[name]) for name in self.feature_names] for item in window
                ], dtype=float)
                values = (values - self.mean) / self.scale
                sequence = np.zeros((self.config.sequence_length, len(self.feature_names)), dtype=np.float32)
                mask = np.zeros(self.config.sequence_length, dtype=np.float32)
                sequence[-len(values):] = values.astype(np.float32)
                mask[-len(values):] = 1.0
                output_sequence.append(sequence)
                output_mask.append(mask)
                output_keys.append((record.unit_id, record.cycle))
                available_by_index[original_index] = (record, True, None)
        status = [available_by_index[index] for index in range(len(features))]
        sequences = np.asarray(output_sequence, dtype=np.float32)
        masks = np.asarray(output_mask, dtype=np.float32)
        if len(output_sequence) == 0:
            sequences = np.empty((0, self.config.sequence_length, len(self.feature_names)), dtype=np.float32)
            masks = np.empty((0, self.config.sequence_length), dtype=np.float32)
        return sequences, masks, output_keys, status

    def _labels_for_keys(self, keys: Sequence[tuple[str, int]],
                         targets: Sequence[TargetRecord]) -> np.ndarray:
        target_map = {(target.unit_id, target.cycle): target for target in targets}
        if len(target_map) != len(targets):
            raise ValueError("target keys must be unique")
        labels = np.empty((len(keys), len(self.config.horizons)), dtype=np.float32)
        for row, key in enumerate(keys):
            if key not in target_map:
                raise ValueError("target is missing for a feature key")
            values = target_map[key].values
            for column, horizon in enumerate(self.config.horizons):
                name = f"failure_within_h{horizon}"
                label = values.get(name)
                if label not in {0, 1, False, True}:
                    raise ValueError(f"target {name} is missing or non-binary")
                labels[row, column] = float(label)
        return labels

    def _train_fixed(self, sequences: np.ndarray, masks: np.ndarray, labels: np.ndarray,
                     weights: np.ndarray, *, epochs: int) -> list[dict[str, float | int]]:
        device = self._device()
        self.network.to(device)
        optimizer = torch.optim.AdamW(
            self.network.parameters(), lr=self.config.learning_rate,
            weight_decay=self.config.weight_decay,
        )
        loader = self._loader(sequences, masks, labels, weights, shuffle=True,
                              seed=self.config.random_seed)
        history: list[dict[str, float | int]] = []
        for epoch in range(1, epochs + 1):
            loss = self._train_epoch(loader, optimizer, device)
            history.append({"epoch": epoch, "train_loss": float(loss)})
        self.network.to("cpu").eval()
        return history

    def _train_early_stopping(
        self, train_seq: np.ndarray, train_mask: np.ndarray, train_labels: np.ndarray,
        train_weights: np.ndarray, val_seq: np.ndarray, val_mask: np.ndarray,
        val_labels: np.ndarray,
    ) -> tuple[list[dict[str, float | int]], int]:
        device = self._device()
        self.network.to(device)
        optimizer = torch.optim.AdamW(
            self.network.parameters(), lr=self.config.learning_rate,
            weight_decay=self.config.weight_decay,
        )
        loader = self._loader(train_seq, train_mask, train_labels, train_weights,
                              shuffle=True, seed=self.config.random_seed)
        val_loader = self._loader(val_seq, val_mask, val_labels, None, shuffle=False,
                                  seed=self.config.random_seed)
        best_loss = float("inf")
        best_epoch = 1
        best_state = None
        stale_epochs = 0
        history: list[dict[str, float | int]] = []
        for epoch in range(1, self.config.max_epochs + 1):
            train_loss = self._train_epoch(loader, optimizer, device)
            val_loss = self._evaluate_loss(val_loader, device)
            history.append({"epoch": epoch, "train_loss": float(train_loss),
                            "validation_loss": float(val_loss)})
            if val_loss < best_loss - self.config.min_delta:
                best_loss = val_loss
                best_epoch = epoch
                best_state = {name: value.detach().cpu().clone()
                              for name, value in self.network.state_dict().items()}
                stale_epochs = 0
            else:
                stale_epochs += 1
            if stale_epochs >= self.config.patience:
                break
        if best_state is None:
            raise RuntimeError("early stopping did not produce a valid checkpoint")
        self.network.load_state_dict(best_state)
        self.network.to("cpu").eval()
        return history, best_epoch

    def _train_epoch(self, loader: DataLoader, optimizer: torch.optim.Optimizer,
                     device: torch.device) -> float:
        self.network.train()
        total = 0.0
        count = 0
        for sequence, mask, target, weight in loader:
            sequence, mask = sequence.to(device), mask.to(device)
            target, weight = target.to(device), weight.to(device)
            optimizer.zero_grad(set_to_none=True)
            probability = self.network(sequence, mask)
            loss_elements = F.binary_cross_entropy(
                probability.clamp(1.0e-7, 1.0 - 1.0e-7), target, reduction="none",
            )
            loss = (loss_elements * weight).mean()
            if not torch.isfinite(loss):
                raise RuntimeError("TCN training produced a non-finite loss")
            loss.backward()
            optimizer.step()
            total += float(loss.detach().cpu()) * len(sequence)
            count += len(sequence)
        return total / count

    def _evaluate_loss(self, loader: DataLoader, device: torch.device) -> float:
        self.network.eval()
        total = 0.0
        count = 0
        with torch.no_grad():
            for batch in loader:
                sequence, mask, target = batch[:3]
                sequence, mask, target = sequence.to(device), mask.to(device), target.to(device)
                probability = self.network(sequence, mask)
                loss = F.binary_cross_entropy(
                    probability.clamp(1.0e-7, 1.0 - 1.0e-7), target, reduction="mean",
                )
                total += float(loss.cpu()) * len(sequence)
                count += len(sequence)
        return total / count

    def _predict_arrays(self, sequences: np.ndarray, masks: np.ndarray) -> np.ndarray:
        loader = self._loader(sequences, masks, None, None, shuffle=False,
                              seed=self.config.random_seed)
        self.network.to("cpu").eval()
        pieces = []
        with torch.no_grad():
            for sequence, mask in loader:
                pieces.append(self.network(sequence, mask).cpu().numpy())
        probabilities = np.concatenate(pieces, axis=0)
        if (not np.isfinite(probabilities).all() or (probabilities < 0).any()
                or (probabilities > 1).any()):
            raise RuntimeError("TCN produced invalid probabilities")
        return probabilities

    def _loader(self, sequences: np.ndarray, masks: np.ndarray,
                targets: np.ndarray | None, weights: np.ndarray | None,
                *, shuffle: bool, seed: int) -> DataLoader:
        dataset = _SequenceDataset(sequences, masks, targets, weights)
        generator = torch.Generator().manual_seed(seed)
        return DataLoader(dataset, batch_size=self.config.batch_size, shuffle=shuffle,
                          num_workers=0, generator=generator, drop_last=False)

    def _summary(self, keys: Sequence[tuple[str, int]], labels: np.ndarray) -> dict[str, object]:
        units = [unit for unit, _ in keys]
        return {
            "rows": len(keys),
            "units": len(set(units)),
            "positive_rows": {str(h): int(labels[:, index].sum())
                              for index, h in enumerate(self.config.horizons)},
            "prevalence": {str(h): float(labels[:, index].mean())
                           for index, h in enumerate(self.config.horizons)},
            "sequence_length": self.config.sequence_length,
            "short_sequences_left_padded": True,
            "padding_value_after_normalization": 0.0,
            "padding_mask_applied": True,
            "horizon_coherence": "p_long = p_short + (1-p_short)*q, so p_long >= p_short by construction",
            "weighting": "inverse rows per unit multiplied by inverse class frequency separately per horizon",
        }

    def _device(self) -> torch.device:
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")

    def _device_name(self) -> str:
        return "cuda" if torch.cuda.is_available() else "cpu"


def _unit_class_weights(keys: Sequence[tuple[str, int]], labels: np.ndarray) -> np.ndarray:
    unit_ids = np.asarray([unit for unit, _ in keys], dtype=object)
    unique, inverse, counts = np.unique(unit_ids, return_inverse=True, return_counts=True)
    unit_weight = len(unit_ids) / (len(unique) * counts[inverse])
    output = np.empty_like(labels, dtype=np.float32)
    for column in range(labels.shape[1]):
        y = labels[:, column].astype(int)
        class_counts = np.bincount(y, minlength=2)
        class_weight = len(y) / (2.0 * class_counts[y])
        combined = unit_weight * class_weight
        output[:, column] = (combined / combined.mean()).astype(np.float32)
    return output


def _set_determinism(seed: int, torch_threads: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.set_num_threads(torch_threads)
    try:
        torch.use_deterministic_algorithms(True, warn_only=True)
    except TypeError:
        torch.use_deterministic_algorithms(True)
