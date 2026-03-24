"""Shared test fixtures."""

from pathlib import Path

import pytest

# Minimal valid sor.yaml for testing
MINIMAL_SOR_YAML = """\
project_name: "Test Project"

always_frozen:
  - "tests/"
  - "sor.yaml"

defaults:
  test_runner: "python -m pytest"
  max_attempts: 20
  consecutive_failure_limit: 5
  plateau_limit: 5
  diminishing_threshold: 0.005
  diminishing_window: 5

layers:
  - name: "search"
    surface:
      - "src/search/query_builder.py"
      - "src/search/ranker.py"
    oracle:
      contracts: "tests/test_search_contract.py"
      scored: true
      scored_tests: "tests/test_search_relevance.py"
      metrics:
        - name: "relevance"
          extract: "RELEVANCE_SCORE"
          weight: 0.7
        - name: "accuracy"
          extract: "VALUE_ACCURACY"
          weight: 0.3
    thresholds:
      target_score: 0.90
      max_attempts: 30

  - name: "api"
    surface:
      - "src/api/main.py"
    oracle:
      contracts: "tests/test_api_*.py"
      scored: false
    thresholds:
      max_attempts: 15
"""


@pytest.fixture
def sor_project(tmp_path: Path) -> Path:
    """Create a temporary project directory with a valid sor.yaml."""
    (tmp_path / "sor.yaml").write_text(MINIMAL_SOR_YAML)
    return tmp_path
