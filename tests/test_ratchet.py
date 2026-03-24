"""Tests for sorkit.ratchet — convergence engine with git commit/reset and stopping conditions."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from sorkit.config import (
    DefaultConfig,
    LayerConfig,
    MetricConfig,
    OracleConfig,
    SorConfig,
    ThresholdConfig,
)
from sorkit.ratchet import RatchetOutcome, StopReason, ratchet_once
from sorkit.results import ResultsStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _git_init(project_dir: Path) -> None:
    """Initialize a git repo with an initial commit."""
    subprocess.run(["git", "init"], cwd=project_dir, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=project_dir, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=project_dir, capture_output=True)
    # Need at least one file to commit
    (project_dir / ".gitkeep").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=project_dir, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial", "--quiet"], cwd=project_dir, capture_output=True)


def _make_passing_contract(project_dir: Path) -> None:
    (project_dir / "test_contract.py").write_text("def test_ok(): assert True\n")


def _make_failing_contract(project_dir: Path) -> None:
    (project_dir / "test_contract.py").write_text("def test_fail(): assert False\n")


def _make_scored_test(project_dir: Path, relevance: float = 0.80, accuracy: float = 0.90) -> None:
    (project_dir / "test_score.py").write_text(
        f"def test_score(capsys):\n"
        f"    print('RELEVANCE_SCORE: {relevance}')\n"
        f"    print('VALUE_ACCURACY: {accuracy}')\n"
        f"    assert True\n"
    )


def _make_surface_file(project_dir: Path, content: str = "# initial") -> None:
    (project_dir / "src").mkdir(exist_ok=True)
    (project_dir / "src" / "main.py").write_text(content)


def _passfail_config(max_attempts: int = 20) -> SorConfig:
    return SorConfig(
        project_name="test",
        always_frozen=[],
        defaults=DefaultConfig(max_attempts=max_attempts),
        layers=[
            LayerConfig(
                name="layer0",
                surface=["src/main.py"],
                oracle=OracleConfig(contracts="test_contract.py", scored=False),
                thresholds=ThresholdConfig(),
            )
        ],
    )


def _scored_config(
    *,
    target_score: float = 0.90,
    max_attempts: int = 20,
    plateau_limit: int = 5,
    diminishing_threshold: float = 0.005,
    diminishing_window: int = 5,
    consecutive_failure_limit: int = 5,
) -> SorConfig:
    return SorConfig(
        project_name="test",
        always_frozen=[],
        defaults=DefaultConfig(
            max_attempts=max_attempts,
            consecutive_failure_limit=consecutive_failure_limit,
            plateau_limit=plateau_limit,
            diminishing_threshold=diminishing_threshold,
            diminishing_window=diminishing_window,
        ),
        layers=[
            LayerConfig(
                name="layer0",
                surface=["src/main.py"],
                oracle=OracleConfig(
                    contracts="test_contract.py",
                    scored=True,
                    scored_tests="test_score.py",
                    metrics=[
                        MetricConfig(name="relevance", extract="RELEVANCE_SCORE", weight=0.7),
                        MetricConfig(name="accuracy", extract="VALUE_ACCURACY", weight=0.3),
                    ],
                ),
                thresholds=ThresholdConfig(target_score=target_score),
            )
        ],
    )


@pytest.fixture
def git_project(tmp_path: Path) -> Path:
    """A tmp dir with git init + initial commit + surface file."""
    _git_init(tmp_path)
    _make_surface_file(tmp_path)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "add surface", "--quiet"], cwd=tmp_path, capture_output=True)
    return tmp_path


# ---------------------------------------------------------------------------
# Pass/fail layer tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
class TestPassFailLayer:
    async def test_passing_commits_and_stops(self, git_project: Path):
        _make_passing_contract(git_project)
        cfg = _passfail_config()
        result = await ratchet_once(cfg, 0, "make it pass", git_project)
        assert result.outcome == RatchetOutcome.STOP
        assert result.stop_reason == StopReason.ALL_PASS
        assert result.score == "PASS"
        assert result.keeps == 1

    async def test_failing_resets_and_discards(self, git_project: Path):
        _make_failing_contract(git_project)
        cfg = _passfail_config()
        result = await ratchet_once(cfg, 0, "bad change", git_project)
        assert result.outcome == RatchetOutcome.DISCARD
        assert result.score == "FAIL"
        assert "DISCARD FAIL" in result.message

    async def test_consecutive_failures_stop(self, git_project: Path):
        cfg = _passfail_config()
        _make_failing_contract(git_project)

        # Seed results with failures just below the limit
        store = ResultsStore(git_project)
        for i in range(4):
            store.append_now("layer0", f"attempt {i}", "FAIL", "DISCARD")

        result = await ratchet_once(cfg, 0, "one more fail", git_project)
        assert result.outcome == RatchetOutcome.STOP
        assert result.stop_reason == StopReason.CONSECUTIVE_FAILURES

    async def test_max_attempts_stop_on_failure(self, git_project: Path):
        cfg = _passfail_config(max_attempts=3)
        _make_failing_contract(git_project)

        store = ResultsStore(git_project)
        # Two prior attempts, one KEEP then one FAIL (breaks consecutive failures)
        store.append_now("layer0", "attempt 0", "PASS", "KEEP")
        store.append_now("layer0", "attempt 1", "FAIL", "DISCARD")

        result = await ratchet_once(cfg, 0, "third attempt", git_project)
        assert result.outcome == RatchetOutcome.STOP
        assert result.stop_reason == StopReason.MAX_ATTEMPTS


# ---------------------------------------------------------------------------
# Scored layer tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
class TestScoredLayerKeep:
    async def test_first_iteration_keeps(self, git_project: Path):
        _make_passing_contract(git_project)
        _make_scored_test(git_project, relevance=0.50, accuracy=0.50)
        cfg = _scored_config(target_score=0.90)

        result = await ratchet_once(cfg, 0, "first try", git_project)
        # composite = 0.50*0.7 + 0.50*0.3 = 0.50 > 0.0 (no prev)
        assert result.outcome == RatchetOutcome.KEEP
        assert result.score == "0.5000"
        assert result.prev_best == "0.0000"
        assert result.keeps == 1

    async def test_improvement_keeps(self, git_project: Path):
        _make_passing_contract(git_project)
        cfg = _scored_config(target_score=0.90)

        # Seed a previous KEEP
        store = ResultsStore(git_project)
        store.append_now("layer0", "prev", "0.4000", "KEEP")

        _make_scored_test(git_project, relevance=0.80, accuracy=0.90)
        result = await ratchet_once(cfg, 0, "improve it", git_project)
        # composite = 0.80*0.7 + 0.90*0.3 = 0.83 > 0.40
        assert result.outcome == RatchetOutcome.KEEP
        assert float(result.score) == pytest.approx(0.83, abs=0.001)

    async def test_target_met_stops(self, git_project: Path):
        _make_passing_contract(git_project)
        _make_scored_test(git_project, relevance=0.95, accuracy=0.95)
        cfg = _scored_config(target_score=0.90)

        result = await ratchet_once(cfg, 0, "nail it", git_project)
        # composite = 0.95*0.7 + 0.95*0.3 = 0.95 >= 0.90
        assert result.outcome == RatchetOutcome.STOP
        assert result.stop_reason == StopReason.TARGET_MET


@pytest.mark.asyncio(loop_scope="function")
class TestScoredLayerDiscard:
    async def test_no_improvement_discards(self, git_project: Path):
        _make_passing_contract(git_project)
        cfg = _scored_config(target_score=0.90)

        store = ResultsStore(git_project)
        store.append_now("layer0", "prev", "0.9000", "KEEP")

        _make_scored_test(git_project, relevance=0.50, accuracy=0.50)
        result = await ratchet_once(cfg, 0, "worse", git_project)
        # composite = 0.50 < 0.90
        assert result.outcome == RatchetOutcome.DISCARD
        assert "DISCARD" in result.message

    async def test_plateau_stops(self, git_project: Path):
        _make_passing_contract(git_project)
        cfg = _scored_config(target_score=0.99, plateau_limit=3)

        store = ResultsStore(git_project)
        store.append_now("layer0", "best", "0.8000", "KEEP")
        # 2 non-improvements already
        store.append_now("layer0", "try1", "0.5000", "DISCARD")
        store.append_now("layer0", "try2", "0.5000", "DISCARD")

        # Third non-improvement triggers plateau
        _make_scored_test(git_project, relevance=0.50, accuracy=0.50)
        result = await ratchet_once(cfg, 0, "try3", git_project)
        assert result.outcome == RatchetOutcome.STOP
        assert result.stop_reason == StopReason.PLATEAU


@pytest.mark.asyncio(loop_scope="function")
class TestScoredLayerMaxAttempts:
    async def test_max_attempts_on_discard(self, git_project: Path):
        _make_passing_contract(git_project)
        cfg = _scored_config(target_score=0.99, max_attempts=3, plateau_limit=99)

        store = ResultsStore(git_project)
        store.append_now("layer0", "keep1", "0.8000", "KEEP")
        store.append_now("layer0", "disc1", "0.5000", "DISCARD")

        _make_scored_test(git_project, relevance=0.50, accuracy=0.50)
        result = await ratchet_once(cfg, 0, "attempt 3", git_project)
        assert result.outcome == RatchetOutcome.STOP
        assert result.stop_reason == StopReason.MAX_ATTEMPTS


@pytest.mark.asyncio(loop_scope="function")
class TestDiminishingReturns:
    async def test_diminishing_stops(self, git_project: Path):
        _make_passing_contract(git_project)
        cfg = _scored_config(
            target_score=0.99,
            diminishing_window=3,
            diminishing_threshold=0.01,
        )

        store = ResultsStore(git_project)
        # 2 prior keeps with tiny improvements
        store.append_now("layer0", "k1", "0.8000", "KEEP")
        store.append_now("layer0", "k2", "0.8010", "KEEP")

        # Third keep also tiny improvement — window of 3 keeps with delta < 0.01
        _make_scored_test(git_project, relevance=0.8020 / 0.7 * 0.7, accuracy=0.8020 / 0.3 * 0.3)
        # Actually, let's be precise: we need composite = 0.8020
        # 0.7*r + 0.3*a = 0.8020. If r=a=x then x=0.8020. Let's use that.
        _make_scored_test(git_project, relevance=0.802, accuracy=0.802)
        result = await ratchet_once(cfg, 0, "tiny bump", git_project)
        # composite = 0.802*0.7 + 0.802*0.3 = 0.802 > 0.801 (keep)
        # window = [0.800, 0.801, 0.802] -> delta = 0.002 < 0.01
        assert result.outcome == RatchetOutcome.STOP
        assert result.stop_reason == StopReason.DIMINISHING


# ---------------------------------------------------------------------------
# Oracle error tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
class TestOracleError:
    async def test_oracle_error_discards(self, git_project: Path):
        (git_project / "test_contract.py").write_text(
            "import nonexistent_module_xyz\ndef test_ok(): pass\n"
        )
        cfg = _passfail_config()
        result = await ratchet_once(cfg, 0, "broken oracle", git_project)
        assert result.outcome == RatchetOutcome.DISCARD
        assert result.score == "ERROR"

    async def test_oracle_error_consecutive_stops(self, git_project: Path):
        (git_project / "test_contract.py").write_text(
            "import nonexistent_module_xyz\ndef test_ok(): pass\n"
        )
        cfg = _passfail_config()

        store = ResultsStore(git_project)
        for i in range(4):
            store.append_now("layer0", f"err {i}", "FAIL", "ORACLE_ERROR")

        result = await ratchet_once(cfg, 0, "5th error", git_project)
        assert result.outcome == RatchetOutcome.STOP
        assert result.stop_reason == StopReason.ORACLE_ERROR


# ---------------------------------------------------------------------------
# Git state verification
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
class TestGitState:
    async def test_keep_creates_commit(self, git_project: Path):
        _make_passing_contract(git_project)
        cfg = _passfail_config()

        # Count commits before
        before = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=git_project, capture_output=True, text=True,
        ).stdout.strip()

        await ratchet_once(cfg, 0, "good change", git_project)

        after = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=git_project, capture_output=True, text=True,
        ).stdout.strip()

        assert int(after) == int(before) + 1

    async def test_discard_resets_changes(self, git_project: Path):
        _make_failing_contract(git_project)
        # Make a change to the surface file
        _make_surface_file(git_project, content="# modified")
        cfg = _passfail_config()

        await ratchet_once(cfg, 0, "bad change", git_project)

        # Surface file should be reset to pre-change state
        content = (git_project / "src" / "main.py").read_text()
        assert content == "# initial"
