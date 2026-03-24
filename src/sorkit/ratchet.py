"""Ratchet engine — single iteration: oracle → compare → commit/reset → check stops."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from sorkit.config import SorConfig, resolve_threshold
from sorkit.oracle import run_oracle
from sorkit.results import ResultsStore


class RatchetOutcome(Enum):
    KEEP = "KEEP"
    DISCARD = "DISCARD"
    STOP = "STOP"


class StopReason(Enum):
    TARGET_MET = "TARGET_MET"
    ALL_PASS = "ALL_PASS"
    PLATEAU = "PLATEAU"
    DIMINISHING = "DIMINISHING"
    MAX_ATTEMPTS = "MAX_ATTEMPTS"
    CONSECUTIVE_FAILURES = "CONSECUTIVE_FAILURES"
    ORACLE_ERROR = "ORACLE_ERROR"


@dataclass
class RatchetResult:
    outcome: RatchetOutcome
    score: str
    prev_best: str | None = None
    stop_reason: StopReason | None = None
    attempts: int = 0
    keeps: int = 0
    message: str = ""


async def ratchet_once(
    config: SorConfig,
    layer_idx: int,
    hypothesis: str,
    project_dir: Path,
) -> RatchetResult:
    """Execute one ratchet iteration for a layer.

    1. Run oracle
    2. On oracle error: record, check consecutive failures
    3. On test failure: git reset, record, check consecutive failures + max attempts
    4. On pass/fail layer pass: git commit, record, STOP(ALL_PASS)
    5. On scored layer improved: git commit, record, check TARGET_MET + DIMINISHING
    6. On scored layer not improved: git reset, record, check PLATEAU
    7. Check MAX_ATTEMPTS always
    """
    store = ResultsStore(project_dir)
    store.ensure_exists()
    layer = config.layers[layer_idx]
    layer_key = layer.name

    # Load thresholds
    max_attempts = resolve_threshold(config, layer_idx, "max_attempts")
    consec_fail_limit = resolve_threshold(config, layer_idx, "consecutive_failure_limit")
    target_score = resolve_threshold(config, layer_idx, "target_score")
    plateau_limit = resolve_threshold(config, layer_idx, "plateau_limit")
    diminishing_threshold = resolve_threshold(config, layer_idx, "diminishing_threshold")
    diminishing_window = resolve_threshold(config, layer_idx, "diminishing_window")

    # Run oracle
    oracle_result = await run_oracle(config, layer_idx, project_dir)

    # --- Oracle error (infrastructure crash) ---
    if oracle_result.error:
        store.append_now(layer_key, hypothesis, "ERROR", "DISCARD")
        consec = store.get_consecutive_failures(layer_key)
        attempts = store.count_layer_attempts(layer_key)

        if consec >= consec_fail_limit:
            return RatchetResult(
                outcome=RatchetOutcome.STOP,
                score="ERROR",
                stop_reason=StopReason.ORACLE_ERROR,
                attempts=attempts,
                keeps=store.get_keep_count(layer_key),
                message=f"STOP:ORACLE_ERROR — {oracle_result.error_message}",
            )

        return RatchetResult(
            outcome=RatchetOutcome.DISCARD,
            score="ERROR",
            attempts=attempts,
            keeps=store.get_keep_count(layer_key),
            message=f"DISCARD ERROR — {oracle_result.error_message}",
        )

    # --- Test failure ---
    if not oracle_result.passed:
        await _git_reset(project_dir)
        store.append_now(layer_key, hypothesis, "FAIL", "DISCARD")
        consec = store.get_consecutive_failures(layer_key)
        attempts = store.count_layer_attempts(layer_key)
        keeps = store.get_keep_count(layer_key)

        if consec >= consec_fail_limit:
            return RatchetResult(
                outcome=RatchetOutcome.STOP,
                score="FAIL",
                stop_reason=StopReason.CONSECUTIVE_FAILURES,
                attempts=attempts,
                keeps=keeps,
                message=f"STOP:CONSECUTIVE_FAILURES score=FAIL attempts={attempts} kept={keeps}",
            )

        if attempts >= max_attempts:
            best = store.get_best_score(layer_key)
            best_str = f"{best:.4f}" if best is not None else "FAIL"
            return RatchetResult(
                outcome=RatchetOutcome.STOP,
                score=best_str,
                stop_reason=StopReason.MAX_ATTEMPTS,
                attempts=attempts,
                keeps=keeps,
                message=f"STOP:MAX_ATTEMPTS score={best_str} attempts={attempts} kept={keeps}",
            )

        return RatchetResult(
            outcome=RatchetOutcome.DISCARD,
            score="FAIL",
            attempts=attempts,
            keeps=keeps,
            message="DISCARD FAIL",
        )

    # --- Pass/fail layer passed ---
    if not oracle_result.scored:
        await _git_commit(project_dir, f"{layer.name}: {hypothesis}")
        store.append_now(layer_key, hypothesis, "PASS", "KEEP")
        attempts = store.count_layer_attempts(layer_key)
        keeps = store.get_keep_count(layer_key)
        return RatchetResult(
            outcome=RatchetOutcome.STOP,
            score="PASS",
            stop_reason=StopReason.ALL_PASS,
            attempts=attempts,
            keeps=keeps,
            message=f"STOP:ALL_PASS score=PASS attempts={attempts} kept={keeps}",
        )

    # --- Scored layer ---
    composite = oracle_result.composite
    assert composite is not None
    score_str = f"{composite:.4f}"

    prev_best = store.get_best_score(layer_key)
    prev_best_val = prev_best if prev_best is not None else 0.0
    prev_best_str = f"{prev_best_val:.4f}"

    if composite > prev_best_val:
        # Improvement — commit
        commit_msg = f"{layer.name}: {hypothesis} | score={score_str} (was {prev_best_str})"
        await _git_commit(project_dir, commit_msg)
        store.append_now(layer_key, hypothesis, score_str, "KEEP")
        attempts = store.count_layer_attempts(layer_key)
        keeps = store.get_keep_count(layer_key)

        # Check: target met?
        if target_score is not None and composite >= target_score:
            return RatchetResult(
                outcome=RatchetOutcome.STOP,
                score=score_str,
                prev_best=prev_best_str,
                stop_reason=StopReason.TARGET_MET,
                attempts=attempts,
                keeps=keeps,
                message=f"STOP:TARGET_MET score={score_str} attempts={attempts} kept={keeps}",
            )

        # Check: diminishing returns?
        recent_keeps = store.get_recent_keeps(layer_key, diminishing_window)
        if len(recent_keeps) >= diminishing_window:
            total_delta = max(recent_keeps) - min(recent_keeps)
            if total_delta < diminishing_threshold:
                return RatchetResult(
                    outcome=RatchetOutcome.STOP,
                    score=score_str,
                    prev_best=prev_best_str,
                    stop_reason=StopReason.DIMINISHING,
                    attempts=attempts,
                    keeps=keeps,
                    message=f"STOP:DIMINISHING score={score_str} attempts={attempts} kept={keeps}",
                )

        return RatchetResult(
            outcome=RatchetOutcome.KEEP,
            score=score_str,
            prev_best=prev_best_str,
            attempts=attempts,
            keeps=keeps,
            message=f"KEEP score={score_str} prev={prev_best_str}",
        )
    else:
        # No improvement — reset
        await _git_reset(project_dir)
        store.append_now(layer_key, hypothesis, score_str, "DISCARD")
        attempts = store.count_layer_attempts(layer_key)
        keeps = store.get_keep_count(layer_key)

        # Check: plateau?
        consec_no_improve = store.get_consecutive_non_improvements(layer_key)
        if consec_no_improve >= plateau_limit:
            return RatchetResult(
                outcome=RatchetOutcome.STOP,
                score=prev_best_str,
                prev_best=prev_best_str,
                stop_reason=StopReason.PLATEAU,
                attempts=attempts,
                keeps=keeps,
                message=f"STOP:PLATEAU score={prev_best_str} attempts={attempts} kept={keeps}",
            )

        # Check: max attempts?
        if attempts >= max_attempts:
            best = store.get_best_score(layer_key)
            best_str = f"{best:.4f}" if best is not None else score_str
            return RatchetResult(
                outcome=RatchetOutcome.STOP,
                score=best_str,
                prev_best=prev_best_str,
                stop_reason=StopReason.MAX_ATTEMPTS,
                attempts=attempts,
                keeps=keeps,
                message=f"STOP:MAX_ATTEMPTS score={best_str} attempts={attempts} kept={keeps}",
            )

        return RatchetResult(
            outcome=RatchetOutcome.DISCARD,
            score=score_str,
            prev_best=prev_best_str,
            attempts=attempts,
            keeps=keeps,
            message=f"DISCARD score={score_str} best={prev_best_str}",
        )


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

async def _git_commit(project_dir: Path, message: str) -> None:
    """Stage all changes and commit."""
    await _run_git(project_dir, "add", "-A")
    await _run_git(project_dir, "commit", "-m", message, "--quiet")


async def _git_reset(project_dir: Path) -> None:
    """Reset all working tree changes."""
    await _run_git(project_dir, "checkout", "--", ".")


async def _run_git(project_dir: Path, *args: str) -> None:
    """Run a git command in the project directory."""
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=project_dir,
    )
    await proc.communicate()
