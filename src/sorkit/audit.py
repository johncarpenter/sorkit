"""Audit and analysis tools for SOR experiment history."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sorkit.config import SorConfig, resolve_threshold
from sorkit.results import ResultsStore, _is_numeric


# ---------------------------------------------------------------------------
# Score history
# ---------------------------------------------------------------------------

@dataclass
class ScorePoint:
    """A single point in the score progression."""
    attempt: int
    timestamp: str
    score: float | None
    best_so_far: float | None
    outcome: str
    hypothesis: str


def get_score_history(store: ResultsStore, layer: str) -> list[ScorePoint]:
    """Build the score progression for a layer, tracking running best."""
    entries = store.get_all_entries(layer)
    points: list[ScorePoint] = []
    best: float | None = None

    for i, entry in enumerate(entries):
        score = float(entry.score) if _is_numeric(entry.score) else None

        if entry.outcome == "KEEP" and score is not None:
            if best is None or score > best:
                best = score

        points.append(ScorePoint(
            attempt=i + 1,
            timestamp=entry.timestamp,
            score=score,
            best_so_far=best,
            outcome=entry.outcome,
            hypothesis=entry.hypothesis,
        ))

    return points


def format_score_history(points: list[ScorePoint], layer: str) -> str:
    """Format score history as a readable table."""
    if not points:
        return f"No history for layer '{layer}'."

    lines = [
        f"Score history for '{layer}' ({len(points)} attempts)\n",
        f"{'#':>3}  {'Score':>8}  {'Best':>8}  {'Outcome':<12}  Hypothesis",
        f"{'---':>3}  {'--------':>8}  {'--------':>8}  {'------------':<12}  ----------",
    ]

    for p in points:
        score_str = f"{p.score:.4f}" if p.score is not None else "—".rjust(8)
        best_str = f"{p.best_so_far:.4f}" if p.best_so_far is not None else "—".rjust(8)
        hyp = p.hypothesis[:50] + "..." if len(p.hypothesis) > 50 else p.hypothesis
        lines.append(f"{p.attempt:>3}  {score_str:>8}  {best_str:>8}  {p.outcome:<12}  {hyp}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Hypothesis analysis
# ---------------------------------------------------------------------------

@dataclass
class HypothesisStats:
    """Aggregated stats for a hypothesis (or similar hypotheses)."""
    hypothesis: str
    attempts: int
    keeps: int
    discards: int
    fails: int
    best_score: float | None
    scores: list[float]


def analyze_hypotheses(store: ResultsStore, layer: str) -> list[HypothesisStats]:
    """Group entries by hypothesis and compute stats for each."""
    entries = store.get_all_entries(layer)
    groups: dict[str, HypothesisStats] = {}

    for entry in entries:
        key = entry.hypothesis
        if key not in groups:
            groups[key] = HypothesisStats(
                hypothesis=key,
                attempts=0,
                keeps=0,
                discards=0,
                fails=0,
                best_score=None,
                scores=[],
            )

        stats = groups[key]
        stats.attempts += 1

        if entry.outcome == "KEEP":
            stats.keeps += 1
        elif "FAIL" in entry.score or "ERROR" in entry.score:
            stats.fails += 1
        else:
            stats.discards += 1

        if _is_numeric(entry.score):
            score = float(entry.score)
            stats.scores.append(score)
            if stats.best_score is None or score > stats.best_score:
                stats.best_score = score

    # Sort: keeps first, then by best score descending
    result = sorted(
        groups.values(),
        key=lambda s: (s.keeps > 0, s.best_score or 0),
        reverse=True,
    )
    return result


def format_hypotheses(stats_list: list[HypothesisStats], layer: str) -> str:
    """Format hypothesis analysis as a readable report."""
    if not stats_list:
        return f"No hypotheses for layer '{layer}'."

    kept = [s for s in stats_list if s.keeps > 0]
    discarded = [s for s in stats_list if s.keeps == 0 and s.fails == 0]
    failed = [s for s in stats_list if s.keeps == 0 and s.fails > 0]

    lines = [f"Hypothesis analysis for '{layer}'\n"]

    if kept:
        lines.append(f"## Successful ({len(kept)})")
        for s in kept:
            score_str = f" (score: {s.best_score:.4f})" if s.best_score is not None else ""
            lines.append(f"  + {s.hypothesis}{score_str}")

    if discarded:
        lines.append(f"\n## No improvement ({len(discarded)})")
        for s in discarded:
            score_str = f" (score: {s.best_score:.4f})" if s.best_score is not None else ""
            lines.append(f"  - {s.hypothesis}{score_str}")

    if failed:
        lines.append(f"\n## Failed ({len(failed)})")
        for s in failed:
            lines.append(f"  x {s.hypothesis} ({s.fails} failure(s))")

    total = len(stats_list)
    keep_rate = len(kept) / total * 100 if total > 0 else 0
    lines.append(f"\nKeep rate: {len(kept)}/{total} ({keep_rate:.0f}%)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Full audit report
# ---------------------------------------------------------------------------

def generate_audit_report(
    config: SorConfig,
    layer_idx: int,
    store: ResultsStore,
) -> str:
    """Generate a comprehensive audit report for a layer."""
    layer = config.layers[layer_idx]
    layer_key = layer.name
    entries = store.get_all_entries(layer_key)

    if not entries:
        return f"No experiment data for layer '{layer_key}'."

    # Basic stats
    total = len(entries)
    keeps = [e for e in entries if e.outcome == "KEEP"]
    discards = [e for e in entries if e.outcome != "KEEP"]
    fails = [e for e in entries if "FAIL" in e.score or "ERROR" in e.score]
    keep_rate = len(keeps) / total * 100 if total > 0 else 0

    lines = [
        f"# Audit Report: {layer_key}",
        f"Type: {'scored' if layer.oracle.scored else 'pass/fail'}",
        "",
        "## Summary",
        f"  Total attempts: {total}",
        f"  Keeps: {len(keeps)} ({keep_rate:.0f}%)",
        f"  Discards: {len(discards) - len(fails)}",
        f"  Failures: {len(fails)}",
    ]

    # Scored layer specifics
    if layer.oracle.scored:
        scores = [float(e.score) for e in entries if _is_numeric(e.score)]
        keep_scores = [float(e.score) for e in keeps if _is_numeric(e.score)]

        if keep_scores:
            target = resolve_threshold(config, layer_idx, "target_score")
            best = max(keep_scores)
            first = keep_scores[0]
            improvement = best - first

            lines.append("")
            lines.append("## Score Progression")
            lines.append(f"  First keep: {first:.4f}")
            lines.append(f"  Best score: {best:.4f}")
            lines.append(f"  Total improvement: +{improvement:.4f}")
            if target is not None:
                gap = target - best
                if gap > 0:
                    lines.append(f"  Gap to target ({target}): {gap:.4f}")
                else:
                    lines.append(f"  Target ({target}): ACHIEVED")

            # Improvement rate
            if len(keep_scores) >= 2:
                deltas = [
                    keep_scores[i] - keep_scores[i - 1]
                    for i in range(1, len(keep_scores))
                ]
                avg_delta = sum(deltas) / len(deltas)
                lines.append(f"  Avg improvement per keep: {avg_delta:+.4f}")

                # Estimate remaining iterations to target
                if target is not None and avg_delta > 0 and gap > 0:
                    # keeps_needed * avg_delta = gap
                    keeps_needed = gap / avg_delta
                    # Estimate attempts needed based on keep rate
                    if keep_rate > 0:
                        attempts_needed = keeps_needed / (keep_rate / 100)
                        lines.append(f"  Est. attempts to target: ~{attempts_needed:.0f}")

        if scores:
            lines.append("")
            lines.append("## Score Distribution")
            lines.append(f"  Min: {min(scores):.4f}")
            lines.append(f"  Max: {max(scores):.4f}")
            lines.append(f"  Median: {sorted(scores)[len(scores) // 2]:.4f}")

    # Convergence analysis
    lines.append("")
    lines.append("## Convergence")

    # Efficiency: how many attempts per keep
    if keeps:
        efficiency = total / len(keeps)
        lines.append(f"  Attempts per keep: {efficiency:.1f}")

    # Streaks
    max_keep_streak = _max_streak(entries, "KEEP")
    max_discard_streak = _max_streak_not(entries, "KEEP")
    lines.append(f"  Longest keep streak: {max_keep_streak}")
    lines.append(f"  Longest non-keep streak: {max_discard_streak}")

    # Current streak
    current_streak_type, current_streak_len = _current_streak(entries)
    lines.append(f"  Current streak: {current_streak_len} {current_streak_type}")

    # Time span
    if len(entries) >= 2:
        lines.append("")
        lines.append("## Timeline")
        lines.append(f"  First attempt: {entries[0].timestamp}")
        lines.append(f"  Last attempt: {entries[-1].timestamp}")

    # Hypothesis summary
    hyp_stats = analyze_hypotheses(store, layer_key)
    if hyp_stats:
        lines.append("")
        lines.append(f"## Hypotheses: {len(hyp_stats)} unique")
        successful = [s for s in hyp_stats if s.keeps > 0]
        lines.append(f"  Successful: {len(successful)}")
        lines.append(f"  Unsuccessful: {len(hyp_stats) - len(successful)}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _max_streak(entries: list, target_outcome: str) -> int:
    """Find the longest consecutive run of a specific outcome."""
    max_run = 0
    current = 0
    for e in entries:
        if e.outcome == target_outcome:
            current += 1
            max_run = max(max_run, current)
        else:
            current = 0
    return max_run


def _max_streak_not(entries: list, target_outcome: str) -> int:
    """Find the longest consecutive run NOT matching an outcome."""
    max_run = 0
    current = 0
    for e in entries:
        if e.outcome != target_outcome:
            current += 1
            max_run = max(max_run, current)
        else:
            current = 0
    return max_run


def _current_streak(entries: list) -> tuple[str, int]:
    """Get the current streak type and length from the tail."""
    if not entries:
        return ("none", 0)
    last_outcome = entries[-1].outcome
    count = 0
    for e in reversed(entries):
        if e.outcome == last_outcome:
            count += 1
        else:
            break
    return (last_outcome, count)
