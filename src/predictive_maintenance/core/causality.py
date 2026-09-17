"""Fail-fast guard for known retrospective fields, not a proof of causality."""

import re
from collections.abc import Iterable


FORBIDDEN_FEATURE_NAMES = frozenset({
    "rul", "normalized_life", "final_cycle", "terminal_cycle", "final_time",
    "terminal_time", "max_cycle", "cycle_max", "unit_max_cycle",
    "unit_final_cycle", "unit_final_time", "time_to_failure", "remaining_useful_life",
    "lifetime", "t_i", "is_operational", "horizon", "critical_horizon",
    "tempo_final", "tempo_final_da_unidade", "ciclo_maximo", "ciclo_maximo_da_unidade",
})


def validate_feature_names(names: Iterable[str]) -> None:
    """Reject known target/retrospective names; aliases require engineering review.

    A renamed future-derived value cannot be detected from its name. Every future
    transform still requires provenance and prefix-invariance regression tests.
    """
    for name in names:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("feature names must be non-empty strings")
        canonical = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        if (canonical in FORBIDDEN_FEATURE_NAMES
                or canonical.startswith(("failure_within_", "future_"))):
            raise ValueError(f"retrospective or target field forbidden as feature: {name}")
