"""Tests for sorkit.audit — audit reports, score history, hypothesis analysis."""

from __future__ import annotations

from pathlib import Path

import pytest

from sorkit.audit import (
    analyze_hypotheses,
    format_hypotheses,
    format_score_history,
    generate_audit_report,
    get_score_history,
)
from sorkit.config import (
    DefaultConfig,
    LayerConfig,
    MetricConfig,
    OracleConfig,
    SorConfig,
    ThresholdConfig,
)
from sorkit.results import ResultsStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _scored_config() -> SorConfig:
    return SorConfig(
        project_name="test",
        always_frozen=[],
        defaults=DefaultConfig(),
        layers=[
            LayerConfig(
                name="search",
                surface=["src/search.py"],
                oracle=OracleConfig(
                    contracts="tests/test_contract.py",
                    scored=True,
                    scored_tests="tests/test_score.py",
                    metrics=[
                        MetricConfig(name="relevance", extract="REL", weight=0.7),
                        MetricConfig(name="accuracy", extract="ACC", weight=0.3),
                    ],
                ),
                thresholds=ThresholdConfig(target_score=0.90),
            ),
        ],
    )


def _passfail_config() -> SorConfig:
    return SorConfig(
        project_name="test",
        always_frozen=[],
        defaults=DefaultConfig(),
        layers=[
            LayerConfig(
                name="api",
                surface=["src/api.py"],
                oracle=OracleConfig(contracts="tests/test_api.py", scored=False),
            ),
        ],
    )


def _populated_store(tmp_path: Path) -> ResultsStore:
    """Create a store with a realistic experiment history."""
    store = ResultsStore(tmp_path)
    store.append_now("search", "add BM25 scoring", "0.4500", "KEEP")
    store.append_now("search", "tune BM25 k1 parameter", "0.4500", "DISCARD")
    store.append_now("search", "add tf-idf weighting", "0.5200", "KEEP")
    store.append_now("search", "try cosine similarity", "FAIL", "DISCARD")
    store.append_now("search", "hybrid BM25+embeddings", "0.6100", "KEEP")
    store.append_now("search", "increase embedding dim", "0.6100", "DISCARD")
    store.append_now("search", "add query expansion", "0.6800", "KEEP")
    store.append_now("search", "add reranker", "0.7200", "KEEP")
    return store


# ---------------------------------------------------------------------------
# Score history
# ---------------------------------------------------------------------------

class TestGetScoreHistory:
    def test_empty(self, tmp_path: Path):
        store = ResultsStore(tmp_path)
        store.ensure_exists()
        points = get_score_history(store, "search")
        assert points == []

    def test_tracks_running_best(self, tmp_path: Path):
        store = _populated_store(tmp_path)
        points = get_score_history(store, "search")
        assert len(points) == 8

        # First keep sets the best
        assert points[0].best_so_far == 0.45
        assert points[0].outcome == "KEEP"

        # Discard doesn't change best
        assert points[1].best_so_far == 0.45

        # Second keep updates best
        assert points[2].best_so_far == 0.52

        # FAIL entry
        assert points[3].score is None
        assert points[3].best_so_far == 0.52

        # Final best
        assert points[-1].best_so_far == 0.72

    def test_attempt_numbering(self, tmp_path: Path):
        store = _populated_store(tmp_path)
        points = get_score_history(store, "search")
        assert points[0].attempt == 1
        assert points[-1].attempt == 8


class TestFormatScoreHistory:
    def test_empty(self):
        result = format_score_history([], "search")
        assert "No history" in result

    def test_contains_header(self, tmp_path: Path):
        store = _populated_store(tmp_path)
        points = get_score_history(store, "search")
        result = format_score_history(points, "search")
        assert "Score history for 'search'" in result
        assert "8 attempts" in result

    def test_contains_scores(self, tmp_path: Path):
        store = _populated_store(tmp_path)
        points = get_score_history(store, "search")
        result = format_score_history(points, "search")
        assert "0.4500" in result
        assert "0.7200" in result
        assert "KEEP" in result
        assert "DISCARD" in result


# ---------------------------------------------------------------------------
# Hypothesis analysis
# ---------------------------------------------------------------------------

class TestAnalyzeHypotheses:
    def test_groups_by_hypothesis(self, tmp_path: Path):
        store = _populated_store(tmp_path)
        stats = analyze_hypotheses(store, "search")
        names = [s.hypothesis for s in stats]
        assert "add BM25 scoring" in names
        assert "add reranker" in names

    def test_counts_outcomes(self, tmp_path: Path):
        store = _populated_store(tmp_path)
        stats = analyze_hypotheses(store, "search")
        by_name = {s.hypothesis: s for s in stats}

        bm25 = by_name["add BM25 scoring"]
        assert bm25.keeps == 1
        assert bm25.attempts == 1

        cosine = by_name["try cosine similarity"]
        assert cosine.fails == 1
        assert cosine.keeps == 0

        tune = by_name["tune BM25 k1 parameter"]
        assert tune.discards == 1
        assert tune.keeps == 0

    def test_sorted_keeps_first(self, tmp_path: Path):
        store = _populated_store(tmp_path)
        stats = analyze_hypotheses(store, "search")
        # Kept hypotheses come first
        kept_indices = [i for i, s in enumerate(stats) if s.keeps > 0]
        not_kept_indices = [i for i, s in enumerate(stats) if s.keeps == 0]
        if kept_indices and not_kept_indices:
            assert max(kept_indices) < min(not_kept_indices)

    def test_empty(self, tmp_path: Path):
        store = ResultsStore(tmp_path)
        store.ensure_exists()
        stats = analyze_hypotheses(store, "search")
        assert stats == []


class TestFormatHypotheses:
    def test_empty(self):
        result = format_hypotheses([], "search")
        assert "No hypotheses" in result

    def test_sections(self, tmp_path: Path):
        store = _populated_store(tmp_path)
        stats = analyze_hypotheses(store, "search")
        result = format_hypotheses(stats, "search")
        assert "Successful" in result
        assert "No improvement" in result
        assert "Failed" in result
        assert "Keep rate" in result

    def test_keep_rate(self, tmp_path: Path):
        store = _populated_store(tmp_path)
        stats = analyze_hypotheses(store, "search")
        result = format_hypotheses(stats, "search")
        # 5 kept out of 8 unique hypotheses
        assert "5/8" in result


# ---------------------------------------------------------------------------
# Full audit report
# ---------------------------------------------------------------------------

class TestGenerateAuditReport:
    def test_empty_layer(self, tmp_path: Path):
        store = ResultsStore(tmp_path)
        store.ensure_exists()
        cfg = _scored_config()
        result = generate_audit_report(cfg, 0, store)
        assert "No experiment data" in result

    def test_scored_layer_report(self, tmp_path: Path):
        store = _populated_store(tmp_path)
        cfg = _scored_config()
        result = generate_audit_report(cfg, 0, store)

        assert "Audit Report: search" in result
        assert "Total attempts: 8" in result
        assert "Keeps: 5" in result
        assert "Score Progression" in result
        assert "First keep: 0.4500" in result
        assert "Best score: 0.7200" in result
        assert "Convergence" in result
        assert "Hypotheses" in result

    def test_includes_improvement(self, tmp_path: Path):
        store = _populated_store(tmp_path)
        cfg = _scored_config()
        result = generate_audit_report(cfg, 0, store)
        # Best (0.72) - First (0.45) = 0.27
        assert "+0.2700" in result

    def test_includes_gap_to_target(self, tmp_path: Path):
        store = _populated_store(tmp_path)
        cfg = _scored_config()
        result = generate_audit_report(cfg, 0, store)
        # Target 0.90 - Best 0.72 = 0.18
        assert "Gap to target" in result
        assert "0.18" in result

    def test_passfail_layer(self, tmp_path: Path):
        store = ResultsStore(tmp_path)
        store.append_now("api", "fix endpoint", "PASS", "KEEP")
        cfg = _passfail_config()
        result = generate_audit_report(cfg, 0, store)
        assert "Audit Report: api" in result
        assert "pass/fail" in result
        assert "Keeps: 1" in result

    def test_convergence_stats(self, tmp_path: Path):
        store = _populated_store(tmp_path)
        cfg = _scored_config()
        result = generate_audit_report(cfg, 0, store)
        assert "Attempts per keep" in result
        assert "Longest keep streak" in result
        assert "Current streak" in result

    def test_timeline(self, tmp_path: Path):
        store = _populated_store(tmp_path)
        cfg = _scored_config()
        result = generate_audit_report(cfg, 0, store)
        assert "First attempt:" in result
        assert "Last attempt:" in result


# ---------------------------------------------------------------------------
# MCP tool integration
# ---------------------------------------------------------------------------

async def _call_tool(name: str, args: dict) -> str:
    from fastmcp import Client
    from sorkit.server import mcp

    async with Client(mcp) as client:
        result = await client.call_tool(name, args)
    return result.content[0].text if result.content else ""


@pytest.mark.asyncio(loop_scope="function")
class TestAuditTools:
    async def test_sor_audit(self, tmp_path: Path):
        store = _populated_store(tmp_path)
        # Write a sor.yaml so the tool can load config
        import yaml
        cfg = _scored_config()
        from sorkit.config import save_config
        save_config(cfg, tmp_path)

        result = await _call_tool("sor_audit", {
            "layer": "search",
            "project_dir": str(tmp_path),
        })
        assert "Audit Report: search" in result

    async def test_sor_score_history(self, tmp_path: Path):
        store = _populated_store(tmp_path)
        from sorkit.config import save_config
        save_config(_scored_config(), tmp_path)

        result = await _call_tool("sor_score_history", {
            "layer": "search",
            "project_dir": str(tmp_path),
        })
        assert "Score history" in result
        assert "0.7200" in result

    async def test_sor_hypotheses(self, tmp_path: Path):
        store = _populated_store(tmp_path)
        from sorkit.config import save_config
        save_config(_scored_config(), tmp_path)

        result = await _call_tool("sor_hypotheses", {
            "layer": "search",
            "project_dir": str(tmp_path),
        })
        assert "Hypothesis analysis" in result
        assert "Successful" in result
        assert "Keep rate" in result

    async def test_audit_no_config(self, tmp_path: Path):
        result = await _call_tool("sor_audit", {
            "layer": "search",
            "project_dir": str(tmp_path),
        })
        assert "ERROR" in result

    async def test_audit_invalid_layer(self, tmp_path: Path):
        from sorkit.config import save_config
        save_config(_scored_config(), tmp_path)

        result = await _call_tool("sor_audit", {
            "layer": "nonexistent",
            "project_dir": str(tmp_path),
        })
        assert "ERROR" in result
