"""Sorkit MCP server — Surface-Oracle-Ratchet tools for autonomous code optimization."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from sorkit.audit import (
    analyze_hypotheses,
    format_hypotheses,
    format_score_history,
    generate_audit_report,
    get_score_history,
)
from sorkit.config import (
    ConfigError,
    load_config,
    resolve_layer_index,
    resolve_threshold,
    validate_config,
)
from sorkit.frozen import get_frozen_paths
from sorkit.init import (
    add_layer,
    generate_config_template,
    validate_and_save_config,
)
from sorkit.notify import send_notifications
from sorkit.oracle import run_oracle
from sorkit.ratchet import RatchetOutcome, ratchet_once
from sorkit.results import ResultsStore

mcp = FastMCP(
    "sorkit",
    instructions=(
        "Surface-Oracle-Ratchet server for autonomous code optimization. "
        "Use sor_init to set up a project, then sor_ratchet to iterate."
    ),
)


# ---------------------------------------------------------------------------
# sor_init
# ---------------------------------------------------------------------------

@mcp.tool()
def sor_init(
    project_dir: str,
    config: dict[str, Any] | None = None,
) -> str:
    """Initialize SOR in a project directory.

    Call with no config to get a template with defaults and descriptions.
    Call with a filled config dict to save sor.yaml and generate all artifacts
    (CLAUDE.md, experiment-loop skill, results.tsv).
    """
    if config is None:
        import json
        template = generate_config_template()
        return (
            "Fill in this template and call sor_init again with the config parameter:\n\n"
            + json.dumps(template, indent=2)
        )

    try:
        result = validate_and_save_config(config, Path(project_dir))
        errors = validate_config(result)
        if errors:
            return f"ERROR: Config validation failed: {'; '.join(errors)}"

        layer_summary = ", ".join(
            f"{l.name} ({'scored' if l.oracle.scored else 'pass/fail'})"
            for l in result.layers
        )
        return (
            f"Initialized SOR for '{result.project_name}' in {project_dir}\n"
            f"Layers: {layer_summary}\n"
            f"Generated: sor.yaml, CLAUDE.md, .claude/skills/experiment-loop.md, results.tsv"
        )
    except (ConfigError, Exception) as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# sor_add_layer
# ---------------------------------------------------------------------------

@mcp.tool()
def sor_add_layer(
    project_dir: str,
    name: str,
    surface: list[str],
    contracts: str,
    scored: bool = False,
    scored_tests: str = "",
    metrics: list[dict[str, Any]] | None = None,
    thresholds: dict[str, Any] | None = None,
) -> str:
    """Add a new layer to an existing SOR config.

    Args:
        project_dir: Path to the project directory containing sor.yaml.
        name: Layer name (must be unique).
        surface: List of mutable file paths.
        contracts: Test file path/glob for contract tests.
        scored: Whether this layer uses scored metrics.
        scored_tests: Test file for scored metrics (required if scored=True).
        metrics: List of {name, extract, weight} dicts (required if scored=True).
        thresholds: Optional {target_score, max_attempts, ...} overrides.
    """
    try:
        config = load_config(Path(project_dir))
    except FileNotFoundError:
        return "ERROR: sor.yaml not found. Run sor_init first."

    oracle: dict[str, Any] = {
        "contracts": contracts,
        "scored": scored,
    }
    if scored:
        oracle["scored_tests"] = scored_tests
        oracle["metrics"] = metrics or []

    layer_dict: dict[str, Any] = {
        "name": name,
        "surface": surface,
        "oracle": oracle,
    }
    if thresholds:
        layer_dict["thresholds"] = thresholds

    try:
        updated = add_layer(config, layer_dict, Path(project_dir))
        return (
            f"Added layer '{name}' (#{len(updated.layers)})\n"
            f"Surface: {', '.join(surface)}\n"
            f"Oracle: {'scored' if scored else 'pass/fail'}\n"
            f"Regenerated CLAUDE.md"
        )
    except (ConfigError, Exception) as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# sor_run_oracle
# ---------------------------------------------------------------------------

@mcp.tool()
async def sor_run_oracle(
    layer: str,
    project_dir: str = ".",
) -> str:
    """Run the oracle for a layer without ratcheting (no git commit/reset).

    Returns the test result: COMPOSITE score for scored layers, PASS/FAIL otherwise.
    Useful for checking current state before making changes.
    """
    try:
        config = load_config(Path(project_dir))
    except FileNotFoundError:
        return "ERROR: sor.yaml not found. Run sor_init first."

    try:
        layer_idx = resolve_layer_index(config, layer)
    except ValueError as e:
        return f"ERROR: {e}"

    result = await run_oracle(config, layer_idx, Path(project_dir))
    layer_name = config.layers[layer_idx].name

    if result.error:
        return f"ORACLE_ERROR ({layer_name}): {result.error_message}\n\nOutput:\n{result.output}"

    if not result.passed:
        return f"FAIL ({layer_name}): Contract tests failed\n\nOutput:\n{result.output}"

    if result.scored:
        metrics_str = "\n".join(
            f"  {name}: {val}" for name, val in result.metrics.items()
        )
        return f"COMPOSITE: {result.composite} ({layer_name})\n\nMetrics:\n{metrics_str}"

    return f"PASS ({layer_name}): All contract tests passed"


# ---------------------------------------------------------------------------
# sor_ratchet
# ---------------------------------------------------------------------------

@mcp.tool()
async def sor_ratchet(
    layer: str,
    hypothesis: str,
    project_dir: str = ".",
) -> str:
    """Run one ratchet iteration: oracle -> compare -> git commit/reset -> check stops.

    This is the core tool for the experiment loop. Call it after making changes
    to the mutation surface. It will:
    - Run the oracle tests
    - Compare the score to the previous best
    - Git commit if improved, git reset if not
    - Check all stopping conditions

    Returns one of:
    - KEEP score={X} prev={Y}
    - DISCARD score={X} best={Y}
    - DISCARD FAIL
    - STOP:{reason} score={X} attempts={N} kept={K}
    """
    try:
        config = load_config(Path(project_dir))
    except FileNotFoundError:
        return "ERROR: sor.yaml not found. Run sor_init first."

    try:
        layer_idx = resolve_layer_index(config, layer)
    except ValueError as e:
        return f"ERROR: {e}"

    result = await ratchet_once(config, layer_idx, hypothesis, Path(project_dir))

    # Send notifications on stop
    if result.outcome == RatchetOutcome.STOP and result.stop_reason:
        layer_name = config.layers[layer_idx].name
        await send_notifications(
            project_name=config.project_name,
            layer_name=layer_name,
            score=result.score,
            attempts=result.attempts,
            keeps=result.keeps,
            stop_reason=result.stop_reason.value,
            project_dir=Path(project_dir),
        )

    return result.message


# ---------------------------------------------------------------------------
# sor_status
# ---------------------------------------------------------------------------

@mcp.tool()
def sor_status(
    layer: str | None = None,
    project_dir: str = ".",
) -> str:
    """Get current progress for one or all layers.

    Shows: attempt count, best score, keeps, last outcome,
    and proximity to stopping conditions.
    """
    try:
        config = load_config(Path(project_dir))
    except FileNotFoundError:
        return "ERROR: sor.yaml not found. Run sor_init first."

    store = ResultsStore(Path(project_dir))

    if layer is not None:
        try:
            layer_idx = resolve_layer_index(config, layer)
        except ValueError as e:
            return f"ERROR: {e}"
        return _format_layer_status(config, layer_idx, store)

    # All layers
    sections: list[str] = [f"# {config.project_name} — SOR Status\n"]
    for i in range(len(config.layers)):
        sections.append(_format_layer_status(config, i, store))
        sections.append("")
    return "\n".join(sections)


def _format_layer_status(config: SorConfig, layer_idx: int, store: ResultsStore) -> str:
    layer = config.layers[layer_idx]
    layer_key = layer.name

    attempts = store.count_layer_attempts(layer_key)
    keeps = store.get_keep_count(layer_key)
    best = store.get_best_score(layer_key)
    entries = store.get_all_entries(layer_key)
    last_outcome = entries[-1].outcome if entries else "—"
    last_score = entries[-1].score if entries else "—"

    max_att = resolve_threshold(config, layer_idx, "max_attempts")
    consec_fail_limit = resolve_threshold(config, layer_idx, "consecutive_failure_limit")
    consec_fails = store.get_consecutive_failures(layer_key)
    consec_non_improve = store.get_consecutive_non_improvements(layer_key)

    lines = [
        f"## Layer {layer_idx + 1}: {layer.name} ({'scored' if layer.oracle.scored else 'pass/fail'})",
        f"  Attempts: {attempts}/{max_att}",
        f"  Keeps: {keeps}",
    ]

    if layer.oracle.scored:
        target = resolve_threshold(config, layer_idx, "target_score")
        best_str = f"{best:.4f}" if best is not None else "—"
        target_str = f"{target}" if target is not None else "—"
        lines.append(f"  Best score: {best_str} (target: {target_str})")
    else:
        lines.append(f"  Status: {'PASSED' if last_outcome == 'KEEP' else 'NOT YET PASSED'}")

    lines.append(f"  Last outcome: {last_outcome} (score: {last_score})")

    # Proximity warnings
    warnings: list[str] = []
    if max_att and attempts >= max_att * 0.8:
        warnings.append(f"Approaching max attempts ({attempts}/{max_att})")
    if consec_fails >= consec_fail_limit * 0.6:
        warnings.append(f"Consecutive failures: {consec_fails}/{consec_fail_limit}")
    if layer.oracle.scored:
        plateau_limit = resolve_threshold(config, layer_idx, "plateau_limit")
        if plateau_limit and consec_non_improve >= plateau_limit * 0.6:
            warnings.append(f"Non-improvements: {consec_non_improve}/{plateau_limit}")

    if warnings:
        lines.append(f"  Warnings: {'; '.join(warnings)}")

    # Frozen files for this layer
    frozen = get_frozen_paths(config, layer_idx)
    lines.append(f"  Frozen: {len(frozen)} paths")
    lines.append(f"  Surface: {', '.join(layer.surface)}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# sor_results
# ---------------------------------------------------------------------------

@mcp.tool()
def sor_results(
    layer: str | None = None,
    last_n: int = 20,
    project_dir: str = ".",
) -> str:
    """Query experiment results history.

    Returns the last N entries from results.tsv, optionally filtered by layer.
    """
    try:
        config = load_config(Path(project_dir))
    except FileNotFoundError:
        return "ERROR: sor.yaml not found. Run sor_init first."

    store = ResultsStore(Path(project_dir))

    # Resolve layer name if provided
    layer_key: str | None = None
    if layer is not None:
        try:
            layer_idx = resolve_layer_index(config, layer)
            layer_key = config.layers[layer_idx].name
        except ValueError as e:
            return f"ERROR: {e}"

    entries = store.get_all_entries(layer_key)

    if not entries:
        return "No results yet."

    # Take last N
    entries = entries[-last_n:]

    # Format as table
    lines = ["timestamp\tlayer\thypothesis\tscore\toutcome"]
    for e in entries:
        lines.append(f"{e.timestamp}\t{e.layer}\t{e.hypothesis}\t{e.score}\t{e.outcome}")

    header = f"Results: {len(entries)} entries"
    if layer_key:
        header += f" (layer: {layer_key})"
    return header + "\n\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# sor_audit
# ---------------------------------------------------------------------------

@mcp.tool()
def sor_audit(
    layer: str,
    project_dir: str = ".",
) -> str:
    """Generate a comprehensive audit report for a layer.

    Includes: summary stats, score progression, convergence analysis,
    improvement rate, estimated iterations to target, and hypothesis breakdown.
    """
    try:
        config = load_config(Path(project_dir))
    except FileNotFoundError:
        return "ERROR: sor.yaml not found. Run sor_init first."

    try:
        layer_idx = resolve_layer_index(config, layer)
    except ValueError as e:
        return f"ERROR: {e}"

    store = ResultsStore(Path(project_dir))
    return generate_audit_report(config, layer_idx, store)


# ---------------------------------------------------------------------------
# sor_score_history
# ---------------------------------------------------------------------------

@mcp.tool()
def sor_score_history(
    layer: str,
    project_dir: str = ".",
) -> str:
    """Get the score progression for a scored layer.

    Shows each attempt with its score, running best, outcome, and hypothesis.
    Useful for understanding the optimization trajectory.
    """
    try:
        config = load_config(Path(project_dir))
    except FileNotFoundError:
        return "ERROR: sor.yaml not found. Run sor_init first."

    try:
        layer_idx = resolve_layer_index(config, layer)
    except ValueError as e:
        return f"ERROR: {e}"

    layer_key = config.layers[layer_idx].name
    store = ResultsStore(Path(project_dir))
    points = get_score_history(store, layer_key)
    return format_score_history(points, layer_key)


# ---------------------------------------------------------------------------
# sor_hypotheses
# ---------------------------------------------------------------------------

@mcp.tool()
def sor_hypotheses(
    layer: str,
    project_dir: str = ".",
) -> str:
    """Analyze which hypotheses worked and which didn't for a layer.

    Groups experiments by hypothesis and shows: successful (kept),
    no improvement (discarded), and failed. Includes keep rate.
    """
    try:
        config = load_config(Path(project_dir))
    except FileNotFoundError:
        return "ERROR: sor.yaml not found. Run sor_init first."

    try:
        layer_idx = resolve_layer_index(config, layer)
    except ValueError as e:
        return f"ERROR: {e}"

    layer_key = config.layers[layer_idx].name
    store = ResultsStore(Path(project_dir))
    stats = analyze_hypotheses(store, layer_key)
    return format_hypotheses(stats, layer_key)
