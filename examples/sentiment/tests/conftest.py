"""Shared fixtures for sentiment analysis tests."""

import json
from pathlib import Path

import pytest


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def golden_set():
    """Load the golden set of labeled examples."""
    with open(FIXTURES_DIR / "golden_set.json") as f:
        return json.load(f)
