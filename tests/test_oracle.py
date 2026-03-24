"""Tests for sorkit.oracle — test execution, metric extraction, composite scoring."""

from __future__ import annotations

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
from sorkit.oracle import OracleResult, _extract_metric, run_oracle


# ---------------------------------------------------------------------------
# Helpers to build test projects with real pytest files
# ---------------------------------------------------------------------------

def _make_config(
    *,
    contracts: str = "test_contract.py",
    scored: bool = False,
    scored_tests: str = "",
    metrics: list[MetricConfig] | None = None,
) -> SorConfig:
    return SorConfig(
        project_name="test",
        always_frozen=[],
        defaults=DefaultConfig(),
        layers=[
            LayerConfig(
                name="layer0",
                surface=["src/main.py"],
                oracle=OracleConfig(
                    contracts=contracts,
                    scored=scored,
                    scored_tests=scored_tests,
                    metrics=metrics or [],
                ),
                thresholds=ThresholdConfig(),
            )
        ],
    )


def _write_test_file(project_dir: Path, filename: str, content: str) -> None:
    (project_dir / filename).write_text(content)


# ---------------------------------------------------------------------------
# Metric extraction (unit tests, no subprocess)
# ---------------------------------------------------------------------------

class TestExtractMetric:
    def test_extracts_value(self):
        output = "some output\nRELEVANCE_SCORE: 0.85\nmore output"
        assert _extract_metric(output, "RELEVANCE_SCORE") == 0.85

    def test_takes_last_match(self):
        output = "RELEVANCE_SCORE: 0.50\nRELEVANCE_SCORE: 0.85"
        assert _extract_metric(output, "RELEVANCE_SCORE") == 0.85

    def test_returns_none_when_missing(self):
        output = "no metrics here"
        assert _extract_metric(output, "RELEVANCE_SCORE") is None

    def test_returns_none_for_non_numeric(self):
        output = "RELEVANCE_SCORE: not_a_number"
        assert _extract_metric(output, "RELEVANCE_SCORE") is None

    def test_handles_integer(self):
        output = "VALUE_ACCURACY: 1"
        assert _extract_metric(output, "VALUE_ACCURACY") == 1.0

    def test_handles_negative(self):
        output = "SCORE: -0.5"
        assert _extract_metric(output, "SCORE") == -0.5


# ---------------------------------------------------------------------------
# Oracle integration tests (run real pytest subprocesses)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
class TestRunOracleContracts:
    async def test_passing_contracts(self, tmp_path: Path):
        _write_test_file(tmp_path, "test_contract.py", "def test_ok(): assert True\n")
        cfg = _make_config(contracts="test_contract.py")
        result = await run_oracle(cfg, 0, tmp_path)
        assert result.passed is True
        assert result.scored is False

    async def test_failing_contracts(self, tmp_path: Path):
        _write_test_file(tmp_path, "test_contract.py", "def test_fail(): assert False\n")
        cfg = _make_config(contracts="test_contract.py")
        result = await run_oracle(cfg, 0, tmp_path)
        assert result.passed is False
        assert result.error is False  # test failure, not oracle error

    async def test_oracle_error_import(self, tmp_path: Path):
        _write_test_file(
            tmp_path,
            "test_contract.py",
            "import nonexistent_module_xyz\ndef test_ok(): pass\n",
        )
        cfg = _make_config(contracts="test_contract.py")
        result = await run_oracle(cfg, 0, tmp_path)
        assert result.passed is False
        assert result.error is True


@pytest.mark.asyncio(loop_scope="function")
class TestRunOracleScored:
    async def test_scored_extracts_metrics(self, tmp_path: Path):
        _write_test_file(tmp_path, "test_contract.py", "def test_ok(): assert True\n")
        _write_test_file(
            tmp_path,
            "test_score.py",
            (
                "def test_score(capsys):\n"
                "    print('RELEVANCE_SCORE: 0.80')\n"
                "    print('VALUE_ACCURACY: 0.90')\n"
                "    assert True\n"
            ),
        )
        cfg = _make_config(
            contracts="test_contract.py",
            scored=True,
            scored_tests="test_score.py",
            metrics=[
                MetricConfig(name="relevance", extract="RELEVANCE_SCORE", weight=0.7),
                MetricConfig(name="accuracy", extract="VALUE_ACCURACY", weight=0.3),
            ],
        )
        result = await run_oracle(cfg, 0, tmp_path)
        assert result.passed is True
        assert result.scored is True
        assert result.metrics["relevance"] == 0.80
        assert result.metrics["accuracy"] == 0.90
        # composite = 0.80*0.7 + 0.90*0.3 = 0.56 + 0.27 = 0.83
        assert result.composite == 0.83

    async def test_scored_missing_metric(self, tmp_path: Path):
        _write_test_file(tmp_path, "test_contract.py", "def test_ok(): assert True\n")
        _write_test_file(
            tmp_path,
            "test_score.py",
            "def test_score(capsys):\n    print('RELEVANCE_SCORE: 0.80')\n    assert True\n",
        )
        cfg = _make_config(
            contracts="test_contract.py",
            scored=True,
            scored_tests="test_score.py",
            metrics=[
                MetricConfig(name="relevance", extract="RELEVANCE_SCORE", weight=0.7),
                MetricConfig(name="accuracy", extract="VALUE_ACCURACY", weight=0.3),
            ],
        )
        result = await run_oracle(cfg, 0, tmp_path)
        assert result.passed is False
        assert result.error is True
        assert "VALUE_ACCURACY" in (result.error_message or "")

    async def test_scored_contracts_fail_skips_scoring(self, tmp_path: Path):
        _write_test_file(tmp_path, "test_contract.py", "def test_fail(): assert False\n")
        _write_test_file(
            tmp_path,
            "test_score.py",
            "def test_score(capsys):\n    print('RELEVANCE_SCORE: 0.80')\n    assert True\n",
        )
        cfg = _make_config(
            contracts="test_contract.py",
            scored=True,
            scored_tests="test_score.py",
            metrics=[
                MetricConfig(name="relevance", extract="RELEVANCE_SCORE", weight=1.0),
            ],
        )
        result = await run_oracle(cfg, 0, tmp_path)
        assert result.passed is False
        assert result.composite is None  # never got to scoring

    async def test_composite_rounding(self, tmp_path: Path):
        _write_test_file(tmp_path, "test_contract.py", "def test_ok(): assert True\n")
        _write_test_file(
            tmp_path,
            "test_score.py",
            (
                "def test_score(capsys):\n"
                "    print('A: 0.333')\n"
                "    print('B: 0.667')\n"
                "    assert True\n"
            ),
        )
        cfg = _make_config(
            contracts="test_contract.py",
            scored=True,
            scored_tests="test_score.py",
            metrics=[
                MetricConfig(name="a", extract="A", weight=0.5),
                MetricConfig(name="b", extract="B", weight=0.5),
            ],
        )
        result = await run_oracle(cfg, 0, tmp_path)
        assert result.passed is True
        # (0.333*0.5 + 0.667*0.5) = 0.5
        assert result.composite == 0.5
