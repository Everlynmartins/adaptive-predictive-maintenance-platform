"""Small causal Transformer Encoder for temporal horizon-risk estimation."""

from __future__ import annotations

from dataclasses import dataclass
from math import log
from pathlib import Path
from typing import Sequence, Self

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset

from predictive_maintenance.models.temporal.tcn import TCNRiskModel


@dataclass(frozen=True)
class TransformerConfig:
    model_name: str = "transformer_fd001"
    model_version: str = "1.0.0"
    horizons: tuple[int, int] = (15, 30)
    sequence_length: int = 30
    d_model: int = 32
    num_heads: int = 4
    num_layers: int = 2
    feedforward_dim: int = 64
    dropout: float = 0.10
    activation: str = "gelu"
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
            raise ValueError("Transformer requires two strictly ordered horizons")
        if any(type(value) is not int or value <= 0 for value in self.horizons):
            raise ValueError("horizons must be positive integers")
        if type(self.sequence_length) is not int or self.sequence_length < 2:
            raise ValueError("sequence_length must be at least two")
        if type(self.d_model) is not int or self.d_model < 4:
            raise ValueError("d_model must be at least four")
        if type(self.num_heads) is not int or self.num_heads < 1 or self.d_model % self.num_heads:
            raise ValueError("num_heads must divide d_model")
        if type(self.num_layers) is not int or self.num_layers < 1:
            raise ValueError("num_layers must be positive")
        if type(self.feedforward_dim) is not int or self.feedforward_dim < self.d_model:
            raise ValueError("feedforward_dim must be at least d_model")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("dropout must be in [0, 1)")
        if self.activation not in {"relu", "gelu"}:
            raise ValueError("activation must be relu or gelu")
        if type(self.batch_size) is not int or self.batch_size < 1:
            raise ValueError("batch_size must be positive")
        if self.learning_rate <= 0 or self.weight_decay < 0:
            raise ValueError("optimizer parameters are invalid")
        if type(self.max_epochs) is not int or self.max_epochs < 1:
            raise ValueError("max_epochs must be positive")
        if type(self.patience) is not int or self.patience < 1:
            raise ValueError("patience must be positive")
        if self.min_delta < 0 or type(self.random_seed) is not int:
            raise ValueError("training controls are invalid")
        if type(self.torch_threads) is not int or self.torch_threads < 1:
            raise ValueError("torch_threads must be positive")

    @property
    def channels(self) -> tuple[int, ...]:
        return (self.d_model,)

    @property
    def kernel_size(self) -> int:
        return 2


class TemporalSequenceDataset(Dataset):
    """Aligned temporal sequences, padding masks, targets and weights."""

    def __init__(self, sequences: np.ndarray, masks: np.ndarray,
                 targets: np.ndarray | None = None,
                 weights: np.ndarray | None = None) -> None:
        if sequences.ndim != 3 or masks.shape != sequences.shape[:2]:
            raise ValueError("temporal dataset arrays are not aligned")
        if targets is not None and len(targets) != len(sequences):
            raise ValueError("targets are not aligned to temporal sequences")
        if weights is not None and len(weights) != len(sequences):
            raise ValueError("weights are not aligned to temporal sequences")
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


class SinusoidalPositionalEncoding(nn.Module):
    """Deterministic position within the causal lookback window."""

    def __init__(self, d_model: int, maximum_length: int) -> None:
        super().__init__()
        positions = torch.arange(maximum_length, dtype=torch.float32).unsqueeze(1)
        even = torch.arange(0, d_model, 2, dtype=torch.float32)
        scale = torch.exp(even * (-log(10_000.0) / d_model))
        encoding = torch.zeros(maximum_length, d_model, dtype=torch.float32)
        encoding[:, 0::2] = torch.sin(positions * scale)
        encoding[:, 1::2] = torch.cos(positions * scale[:encoding[:, 1::2].shape[1]])
        self.register_buffer("encoding", encoding.unsqueeze(0), persistent=True)

    def forward(self, values: torch.Tensor) -> torch.Tensor:
        if values.ndim != 3 or values.shape[1] > self.encoding.shape[1]:
            raise ValueError("sequence length is incompatible with positional encoding")
        return values + self.encoding[:, :values.shape[1]].to(values.dtype)


class SmallCausalTransformer(nn.Module):
    """Transformer Encoder with causal attention and monotone H15/H30 head."""

    def __init__(self, input_features: int, config: TransformerConfig) -> None:
        super().__init__()
        self.sequence_length = config.sequence_length
        self.d_model = config.d_model
        self.num_heads = config.num_heads
        self.num_layers = config.num_layers
        self.input_projection = nn.Linear(input_features, config.d_model)
        self.position = SinusoidalPositionalEncoding(config.d_model, config.sequence_length)
        layer = nn.TransformerEncoderLayer(
            d_model=config.d_model, nhead=config.num_heads,
            dim_feedforward=config.feedforward_dim, dropout=config.dropout,
            activation=config.activation, batch_first=True, norm_first=False,
        )
        self.encoder = nn.TransformerEncoder(layer, num_layers=config.num_layers)
        self.head = nn.Linear(config.d_model, 2)

    @staticmethod
    def causal_attention_mask(length: int, device: torch.device | None = None) -> torch.Tensor:
        if type(length) is not int or length < 1:
            raise ValueError("attention-mask length must be positive")
        return torch.triu(torch.ones((length, length), dtype=torch.bool, device=device), diagonal=1)

    @staticmethod
    def _validate_mask(sequence: torch.Tensor, mask: torch.Tensor) -> None:
        if sequence.ndim != 3 or mask.ndim != 2 or sequence.shape[:2] != mask.shape:
            raise ValueError("sequence and mask dimensions are invalid")
        if not torch.all((mask == 0) | (mask == 1)):
            raise ValueError("mask must be binary")
        if torch.any(mask.sum(dim=1) < 1):
            raise ValueError("every sequence must contain an observed origin")
        if mask.shape[1] > 1 and torch.any(mask[:, 1:] < mask[:, :-1]):
            raise ValueError("mask must contain only left padding")
        if torch.any(mask[:, -1] != 1):
            raise ValueError("the origin must be the final valid sequence element")

    def encode(self, sequence: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        self._validate_mask(sequence, mask)
        if sequence.shape[1] != self.sequence_length:
            raise ValueError("sequence is outside the configured length")
        projected = self.position(self.input_projection(sequence * mask.unsqueeze(-1)))
        length = sequence.shape[1]
        causal = self.causal_attention_mask(length, sequence.device)
        attention = causal.unsqueeze(0).expand(
            sequence.shape[0] * self.num_heads, -1, -1,
        ).clone()
        padding_keys = mask.eq(0).repeat_interleave(self.num_heads, dim=0)
        attention |= padding_keys.unsqueeze(1)
        # A padded query would otherwise have every key masked and yield NaN.
        # Its diagonal is made finite, while valid queries still mask every
        # padded key and every future key.
        diagonal = torch.arange(length, device=sequence.device)
        attention[:, diagonal, diagonal] = False
        return self.encoder(projected, mask=attention, is_causal=True)

    def forward(self, sequence: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        logits = self.head(self.encode(sequence, mask)[:, -1])
        p_short = torch.sigmoid(logits[:, 0])
        increment = torch.sigmoid(logits[:, 1])
        p_long = p_short + (1.0 - p_short) * increment
        return torch.stack((p_short, p_long), dim=1)


class TransformerRiskModel(TCNRiskModel):
    """Risk model sharing the audited unit-scoped sequence protocol."""

    artifact_schema = "transformer-risk-model/v1"

    def __init__(self, config: TransformerConfig, feature_names: Sequence[str]) -> None:
        super().__init__(config, feature_names)
        self.config = config
        self.network = self._new_network()

    def _new_network(self) -> SmallCausalTransformer:
        return SmallCausalTransformer(len(self.feature_names), self.config)

    def _loader(self, sequences: np.ndarray, masks: np.ndarray,
                targets: np.ndarray | None, weights: np.ndarray | None,
                *, shuffle: bool, seed: int) -> DataLoader:
        dataset = TemporalSequenceDataset(sequences, masks, targets, weights)
        generator = torch.Generator().manual_seed(seed)
        return DataLoader(dataset, batch_size=self.config.batch_size, shuffle=shuffle,
                          num_workers=0, generator=generator, drop_last=False)

    @classmethod
    def load(cls, path: Path) -> Self:
        try:
            payload = torch.load(path, map_location="cpu", weights_only=False)
        except TypeError:
            payload = torch.load(path, map_location="cpu")
        if not isinstance(payload, dict) or payload.get("schema") != cls.artifact_schema:
            raise ValueError("incompatible Transformer artifact")
        raw = payload["configuration"]
        config = TransformerConfig(
            model_name=str(raw["model_name"]), model_version=str(raw["model_version"]),
            horizons=tuple(int(value) for value in raw["horizons"]),
            sequence_length=int(raw["sequence_length"]), d_model=int(raw["d_model"]),
            num_heads=int(raw["num_heads"]), num_layers=int(raw["num_layers"]),
            feedforward_dim=int(raw["feedforward_dim"]), dropout=float(raw["dropout"]),
            activation=str(raw["activation"]), batch_size=int(raw["batch_size"]),
            learning_rate=float(raw["learning_rate"]), weight_decay=float(raw["weight_decay"]),
            max_epochs=int(raw["max_epochs"]), patience=int(raw["patience"]),
            min_delta=float(raw["min_delta"]), random_seed=int(raw["random_seed"]),
            torch_threads=int(raw["torch_threads"]),
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

    def parameter_memory_bytes(self) -> int:
        return int(sum(parameter.numel() * parameter.element_size()
                       for parameter in self.network.parameters()))

    def approximate_inference_working_memory_bytes(self, batch_size: int = 1) -> int:
        if type(batch_size) is not int or batch_size < 1:
            raise ValueError("batch_size must be positive")
        length = self.config.sequence_length
        token_state = batch_size * length * self.config.d_model * (self.config.num_layers + 2)
        attention = batch_size * self.config.num_layers * self.config.num_heads * length * length
        return int(4 * (token_state + attention))
