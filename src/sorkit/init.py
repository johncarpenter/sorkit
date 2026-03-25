"""Initialization and code generation — sor.yaml template, CLAUDE.md, experiment-loop skill."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sorkit.config import (
    SorConfig,
    load_config,
    resolve_threshold,
    save_config,
    validate_config,
)
from sorkit.results import ResultsStore


# ---------------------------------------------------------------------------
# Config template
# ---------------------------------------------------------------------------

def generate_config_template() -> dict[str, Any]:
    """Return a JSON-serializable config template with defaults and descriptions.

    The LLM fills in the values and passes back to validate_and_save_config().
    """
    return {
        "project_name": {
            "_value": "My Project",
            "_description": "Human-readable project name",
        },
        "always_frozen": {
            "_value": [
                "fixtures/",
                "tests/",
                "sor.yaml",
                "CLAUDE.md",
                ".claude/",
                "results.tsv",
            ],
            "_description": "Paths the agent must never modify (tests, fixtures, config)",
        },
        "defaults": {
            "_description": "Global defaults — layers can override any of these",
            "test_runner": {
                "_value": "python -m pytest",
                "_description": "Command to run tests (e.g. 'python -m pytest', 'npm test')",
            },
            "max_attempts": {
                "_value": 20,
                "_description": "Hard ceiling on iterations per layer",
            },
            "consecutive_failure_limit": {
                "_value": 5,
                "_description": "Stop after this many consecutive test failures",
            },
            "plateau_limit": {
                "_value": 5,
                "_description": "Stop after this many consecutive non-improvements (scored layers)",
            },
            "diminishing_threshold": {
                "_value": 0.005,
                "_description": "Stop if score delta over window is below this (scored layers)",
            },
            "diminishing_window": {
                "_value": 5,
                "_description": "Number of recent keeps to check for diminishing returns",
            },
        },
        "layers": {
            "_description": "Define layers bottom-up. Each completed layer freezes before the next.",
            "_example_layer": {
                "name": "layer_name",
                "surface": ["src/module/file1.py", "src/module/file2.py"],
                "oracle": {
                    "contracts": "tests/test_module_contract.py",
                    "scored": False,
                    "scored_tests": "",
                    "metrics": [],
                },
                "thresholds": {
                    "target_score": None,
                    "max_attempts": None,
                },
            },
            "_example_scored_layer": {
                "name": "scored_layer_name",
                "surface": ["src/search/ranker.py"],
                "oracle": {
                    "contracts": "tests/test_search_contract.py",
                    "scored": True,
                    "scored_tests": "tests/test_search_relevance.py",
                    "metrics": [
                        {"name": "relevance", "extract": "RELEVANCE_SCORE", "weight": 0.7},
                        {"name": "accuracy", "extract": "VALUE_ACCURACY", "weight": 0.3},
                    ],
                },
                "thresholds": {
                    "target_score": 0.90,
                    "max_attempts": 30,
                },
            },
        },
    }


def config_from_dict(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert a filled template (or plain config dict) to a sor.yaml-compatible dict.

    Handles both template format (with _value/_description keys) and
    plain config dicts. Strips template metadata, keeps values.
    """
    result: dict[str, Any] = {}

    # Project name
    pn = raw.get("project_name", "My Project")
    result["project_name"] = pn["_value"] if isinstance(pn, dict) else pn

    # Always frozen
    af = raw.get("always_frozen", [])
    result["always_frozen"] = af["_value"] if isinstance(af, dict) else af

    # Defaults
    defaults_raw = raw.get("defaults", {})
    defaults: dict[str, Any] = {}
    for key in ("test_runner", "max_attempts", "consecutive_failure_limit",
                "plateau_limit", "diminishing_threshold", "diminishing_window"):
        val = defaults_raw.get(key)
        if isinstance(val, dict):
            val = val.get("_value")
        if val is not None:
            defaults[key] = val
    result["defaults"] = defaults

    # Layers
    layers_raw = raw.get("layers", [])
    if isinstance(layers_raw, dict):
        # Template format — extract the actual layers list
        layers_raw = layers_raw.get("_value", [])
    result["layers"] = layers_raw

    return result


def validate_and_save_config(config_dict: dict[str, Any], project_dir: Path) -> SorConfig:
    """Validate a config dict and save as sor.yaml + generate artifacts.

    Accepts both template format and plain config dicts.
    """
    clean = config_from_dict(config_dict)

    # Write sor.yaml
    import yaml
    path = project_dir / "sor.yaml"
    with open(path, "w") as f:
        f.write("# sor.yaml — Surface-Oracle-Ratchet configuration\n\n")
        yaml.dump(clean, f, default_flow_style=False, sort_keys=False)

    # Load and validate
    config = load_config(project_dir)
    errors = validate_config(config)
    if errors:
        from sorkit.config import ConfigError
        raise ConfigError(f"Config validation failed: {'; '.join(errors)}")

    # Generate artifacts
    generate_claude_md(config, project_dir)
    generate_experiment_loop_skill(config, project_dir)
    initialize_results_tsv(project_dir)

    return config


# ---------------------------------------------------------------------------
# Add layer
# ---------------------------------------------------------------------------

def add_layer(config: SorConfig, layer_dict: dict[str, Any], project_dir: Path) -> SorConfig:
    """Add a new layer to existing config, re-save and regenerate artifacts."""
    from sorkit.config import _parse_layer

    new_layer = _parse_layer(layer_dict)
    config.layers.append(new_layer)

    errors = validate_config(config)
    if errors:
        config.layers.pop()
        from sorkit.config import ConfigError
        raise ConfigError(f"Validation failed: {'; '.join(errors)}")

    save_config(config, project_dir)
    generate_claude_md(config, project_dir)
    generate_experiment_loop_skill(config, project_dir)
    return config


# ---------------------------------------------------------------------------
# CLAUDE.md generation
# ---------------------------------------------------------------------------

def generate_claude_md(config: SorConfig, project_dir: Path) -> None:
    """Generate CLAUDE.md from config, matching sor-init.sh output format."""
    lines: list[str] = []

    # Header
    lines.append(f"# {config.project_name}")
    lines.append("")
    lines.append("## Development Method: Surface-Oracle-Ratchet")
    lines.append("")
    lines.append("This project uses autonomous iterative development. Each layer has:")
    lines.append("- A **mutation surface** (files the agent can edit)")
    lines.append("- An **oracle** (automated tests that determine pass/fail)")
    lines.append("- A **ratchet** (git commit on improvement, git reset on failure)")
    lines.append("")
    lines.append("Use `sor_run_oracle` to evaluate. See `.claude/skills/experiment-loop.md` for the protocol.")
    lines.append("")

    # Frozen files
    lines.append("## Frozen Files (DO NOT MODIFY)")
    lines.append("")
    lines.append("```")
    for path in config.always_frozen:
        lines.append(f"  {path}")
    lines.append("```")
    lines.append("")

    # Mutation surfaces table
    lines.append("## Mutation Surfaces (per layer)")
    lines.append("")
    lines.append("| Layer | Name | Mutable Files | Oracle Type |")
    lines.append("|-------|------|--------------|-------------|")
    for i, layer in enumerate(config.layers):
        surface = ",".join(layer.surface)
        oracle_type = "Scored (composite metric)" if layer.oracle.scored else "Pass/fail"
        lines.append(f"| {i + 1} | {layer.name} | `{surface}` | {oracle_type} |")
    lines.append("")
    lines.append("When working on Layer N, all layers < N are frozen.")
    lines.append("")

    # Stopping thresholds table
    lines.append("## Stopping Thresholds")
    lines.append("")
    lines.append("| Parameter | Value |")
    lines.append("|-----------|-------|")
    for i, layer in enumerate(config.layers):
        max_att = resolve_threshold(config, i, "max_attempts")
        lines.append(f"| Layer {i + 1} ({layer.name}) max attempts | {max_att} |")
        if layer.oracle.scored:
            target = resolve_threshold(config, i, "target_score")
            lines.append(f"| Layer {i + 1} ({layer.name}) target score | {target} |")

    plateau = config.defaults.plateau_limit
    diminishing = config.defaults.diminishing_threshold
    fail_limit = config.defaults.consecutive_failure_limit
    lines.append(f"| Plateau limit | {plateau} consecutive non-improvements |")
    lines.append(f"| Diminishing threshold | {diminishing} (min delta over window) |")
    lines.append(f"| Consecutive failure limit | {fail_limit} |")
    lines.append("")
    lines.append("To adjust, edit the thresholds in `sor.yaml` and regenerate with `sor_init`.")

    (project_dir / "CLAUDE.md").write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Experiment loop skill
# ---------------------------------------------------------------------------

_EXPERIMENT_LOOP_SKILL = """\
# Skill: Autonomous Experiment Loop

## When to Use
When implementing any layer of this project autonomously.
This skill defines the experiment protocol — how to iterate, evaluate, and ratchet.

## Protocol

### Before You Start

1. Read `CLAUDE.md` to confirm which layer you're working on
2. Read the oracle tests for your layer (see the contracts/scored_tests in sor.yaml)
3. Read the current mutation surface files to understand the starting state
4. Check `results.tsv` for previous experiment history (if any)

### Experiment Loop

Each iteration follows this exact sequence. Do not deviate.

#### Step 1: Plan the Change

Before editing any code, write a one-line hypothesis:

```
HYPOTHESIS: [what you're changing] should [expected effect] because [reasoning]
```

#### Step 2: Implement

Edit ONLY files in the current layer's mutation surface (see CLAUDE.md).
Do NOT touch frozen files. Do NOT touch files from other layers.
Keep changes atomic — one idea per iteration.

#### Step 3: Run the Ratchet

Call `sor_ratchet` with the layer name and your hypothesis description.

The ratchet will:
- Run the oracle
- Compare scores to previous best
- Git commit if improved, git reset if not
- Check all stopping conditions
- Notify if a stopping condition is hit

#### Step 4: Parse the Output

The ratchet prints exactly one of:
- `KEEP score={X} prev={Y}` — improvement, committed
- `DISCARD score={X} best={Y}` — no improvement, reverted
- `DISCARD FAIL` — tests failed, reverted
- `STOP:{reason} score={X} attempts={N} kept={K}` — stopping condition hit

#### Step 5: Decide Next Experiment

Review `results.tsv` to see what you've tried. Pick a different approach.
Do NOT repeat a failed hypothesis with minor variations more than once.

If you have 3+ consecutive failures, call `sor_results` to review recent outcomes
and read the test output more carefully.

### Stopping Conditions

Stop the loop and report to the human if you see any `STOP:` output:
- `TARGET_MET` — scored layer reached its target composite score
- `ALL_PASS` — pass/fail layer succeeded
- `PLATEAU` — too many consecutive non-improvements
- `DIMINISHING` — improvements too small to matter
- `MAX_ATTEMPTS` — hard ceiling reached
- `CONSECUTIVE_FAILURES` — too many crashes in a row
- `ORACLE_ERROR` — the oracle itself is broken (needs human fix)

### Results TSV Format

Tab-separated, appended by the ratchet:

```
timestamp\tlayer\thypothesis\tscore\toutcome
2026-03-12T10:30:00\t0\thybrid BM25+cosine 0.6/0.4\t0.72\tKEEP
2026-03-12T10:35:00\t0\tpure cosine similarity\t0.65\tDISCARD
```
"""


def generate_experiment_loop_skill(config: SorConfig, project_dir: Path) -> None:
    """Generate .claude/skills/experiment-loop.md."""
    skills_dir = project_dir / ".claude" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    (skills_dir / "experiment-loop.md").write_text(_EXPERIMENT_LOOP_SKILL)


# ---------------------------------------------------------------------------
# Results TSV
# ---------------------------------------------------------------------------

def initialize_results_tsv(project_dir: Path) -> None:
    """Create results.tsv with header if it doesn't exist."""
    store = ResultsStore(project_dir)
    store.ensure_exists()
