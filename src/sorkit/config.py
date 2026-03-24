"""Configuration data model for sor.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class MetricConfig:
    name: str
    extract: str  # grep pattern in test stdout
    weight: float


@dataclass
class OracleConfig:
    contracts: str  # test file glob/path
    scored: bool = False
    scored_tests: str = ""
    metrics: list[MetricConfig] = field(default_factory=list)


@dataclass
class ThresholdConfig:
    """Per-layer threshold overrides. None means 'use default'."""

    target_score: float | None = None
    max_attempts: int | None = None
    consecutive_failure_limit: int | None = None
    plateau_limit: int | None = None
    diminishing_threshold: float | None = None
    diminishing_window: int | None = None


@dataclass
class DefaultConfig:
    test_runner: str = "python -m pytest"
    max_attempts: int = 20
    consecutive_failure_limit: int = 5
    plateau_limit: int = 5
    diminishing_threshold: float = 0.005
    diminishing_window: int = 5


@dataclass
class LayerConfig:
    name: str
    surface: list[str]
    oracle: OracleConfig
    thresholds: ThresholdConfig = field(default_factory=ThresholdConfig)


@dataclass
class SorConfig:
    project_name: str
    always_frozen: list[str]
    defaults: DefaultConfig
    layers: list[LayerConfig]


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_metric(raw: dict[str, Any]) -> MetricConfig:
    return MetricConfig(
        name=raw["name"],
        extract=raw["extract"],
        weight=float(raw["weight"]),
    )


def _parse_oracle(raw: dict[str, Any]) -> OracleConfig:
    return OracleConfig(
        contracts=raw.get("contracts", ""),
        scored=bool(raw.get("scored", False)),
        scored_tests=raw.get("scored_tests", ""),
        metrics=[_parse_metric(m) for m in raw.get("metrics", [])],
    )


def _parse_thresholds(raw: dict[str, Any] | None) -> ThresholdConfig:
    if not raw:
        return ThresholdConfig()
    return ThresholdConfig(
        target_score=raw.get("target_score"),
        max_attempts=raw.get("max_attempts"),
        consecutive_failure_limit=raw.get("consecutive_failure_limit"),
        plateau_limit=raw.get("plateau_limit"),
        diminishing_threshold=raw.get("diminishing_threshold"),
        diminishing_window=raw.get("diminishing_window"),
    )


def _parse_defaults(raw: dict[str, Any] | None) -> DefaultConfig:
    if not raw:
        return DefaultConfig()
    cfg = DefaultConfig()
    if "test_runner" in raw:
        cfg.test_runner = raw["test_runner"]
    if "max_attempts" in raw:
        cfg.max_attempts = int(raw["max_attempts"])
    if "consecutive_failure_limit" in raw:
        cfg.consecutive_failure_limit = int(raw["consecutive_failure_limit"])
    if "plateau_limit" in raw:
        cfg.plateau_limit = int(raw["plateau_limit"])
    if "diminishing_threshold" in raw:
        cfg.diminishing_threshold = float(raw["diminishing_threshold"])
    if "diminishing_window" in raw:
        cfg.diminishing_window = int(raw["diminishing_window"])
    return cfg


def _parse_layer(raw: dict[str, Any]) -> LayerConfig:
    return LayerConfig(
        name=raw["name"],
        surface=list(raw.get("surface", [])),
        oracle=_parse_oracle(raw.get("oracle", {})),
        thresholds=_parse_thresholds(raw.get("thresholds")),
    )


# ---------------------------------------------------------------------------
# Load / Save
# ---------------------------------------------------------------------------

def _find_config(project_dir: Path) -> Path:
    """Locate sor.yaml in the project directory."""
    path = project_dir / "sor.yaml"
    if path.is_file():
        return path
    raise FileNotFoundError(f"sor.yaml not found in {project_dir}")


def load_config(project_dir: Path) -> SorConfig:
    """Load and parse sor.yaml from the project directory."""
    path = _find_config(project_dir)
    with open(path) as f:
        raw = yaml.safe_load(f)

    if not raw or not isinstance(raw, dict):
        raise ValueError(f"Invalid sor.yaml: expected a mapping, got {type(raw)}")

    return SorConfig(
        project_name=raw.get("project_name", "Unnamed Project"),
        always_frozen=list(raw.get("always_frozen", [])),
        defaults=_parse_defaults(raw.get("defaults")),
        layers=[_parse_layer(l) for l in raw.get("layers", [])],
    )


def save_config(config: SorConfig, project_dir: Path) -> None:
    """Serialize SorConfig back to sor.yaml."""
    data = _config_to_dict(config)
    path = project_dir / "sor.yaml"
    with open(path, "w") as f:
        f.write("# sor.yaml — Surface-Oracle-Ratchet configuration\n\n")
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _config_to_dict(config: SorConfig) -> dict[str, Any]:
    """Convert SorConfig back to a plain dict for YAML serialization."""
    layers = []
    for layer in config.layers:
        oracle: dict[str, Any] = {"contracts": layer.oracle.contracts}
        if layer.oracle.scored:
            oracle["scored"] = True
            oracle["scored_tests"] = layer.oracle.scored_tests
            oracle["metrics"] = [
                {"name": m.name, "extract": m.extract, "weight": m.weight}
                for m in layer.oracle.metrics
            ]
        else:
            oracle["scored"] = False

        thresholds: dict[str, Any] = {}
        for fld in ("target_score", "max_attempts", "consecutive_failure_limit",
                     "plateau_limit", "diminishing_threshold", "diminishing_window"):
            val = getattr(layer.thresholds, fld)
            if val is not None:
                thresholds[fld] = val

        entry: dict[str, Any] = {
            "name": layer.name,
            "surface": layer.surface,
            "oracle": oracle,
        }
        if thresholds:
            entry["thresholds"] = thresholds
        layers.append(entry)

    return {
        "project_name": config.project_name,
        "always_frozen": config.always_frozen,
        "defaults": {
            "test_runner": config.defaults.test_runner,
            "max_attempts": config.defaults.max_attempts,
            "consecutive_failure_limit": config.defaults.consecutive_failure_limit,
            "plateau_limit": config.defaults.plateau_limit,
            "diminishing_threshold": config.defaults.diminishing_threshold,
            "diminishing_window": config.defaults.diminishing_window,
        },
        "layers": layers,
    }


# ---------------------------------------------------------------------------
# Threshold Resolution
# ---------------------------------------------------------------------------

def resolve_threshold(config: SorConfig, layer_idx: int, key: str) -> Any:
    """Get a threshold value: layer override takes precedence over default."""
    layer = config.layers[layer_idx]
    val = getattr(layer.thresholds, key, None)
    if val is not None:
        return val
    return getattr(config.defaults, key, None)


# ---------------------------------------------------------------------------
# Layer Resolution
# ---------------------------------------------------------------------------

def resolve_layer_index(config: SorConfig, name_or_index: str) -> int:
    """Resolve a layer name or index string to a 0-based index."""
    # Try numeric first
    try:
        idx = int(name_or_index)
    except ValueError:
        idx = None

    if idx is not None:
        if 0 <= idx < len(config.layers):
            return idx
        raise ValueError(f"Layer index {idx} out of range (have {len(config.layers)})")

    # Try name lookup (case-insensitive)
    needle = name_or_index.lower()
    for i, layer in enumerate(config.layers):
        if layer.name.lower() == needle:
            return i
    raise ValueError(f"No layer named '{name_or_index}'")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class ConfigError(Exception):
    """Raised when sor.yaml fails validation."""


def validate_config(config: SorConfig) -> list[str]:
    """Validate a SorConfig and return a list of error messages (empty = valid)."""
    errors: list[str] = []

    if not config.layers:
        errors.append("No layers defined")

    names_seen: set[str] = set()
    for i, layer in enumerate(config.layers):
        prefix = f"Layer {i} ({layer.name})"

        # Unique names
        if layer.name.lower() in names_seen:
            errors.append(f"{prefix}: duplicate layer name")
        names_seen.add(layer.name.lower())

        # Non-empty surface
        if not layer.surface:
            errors.append(f"{prefix}: surface is empty (no mutable files)")

        # Scored layer checks
        if layer.oracle.scored:
            if not layer.oracle.scored_tests:
                errors.append(f"{prefix}: scored=true but no scored_tests defined")
            if not layer.oracle.metrics:
                errors.append(f"{prefix}: scored=true but no metrics defined")
            else:
                total_weight = sum(m.weight for m in layer.oracle.metrics)
                if abs(total_weight - 1.0) > 0.01:
                    errors.append(
                        f"{prefix}: metric weights sum to {total_weight:.3f}, expected 1.0"
                    )

        # Contracts required
        if not layer.oracle.contracts:
            errors.append(f"{prefix}: no contract tests defined")

    return errors
