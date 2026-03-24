"""Tests for sorkit.results — TSV tracking and querying."""

from pathlib import Path

import pytest

from sorkit.results import HEADER, ResultEntry, ResultsStore


@pytest.fixture
def store(tmp_path: Path) -> ResultsStore:
    return ResultsStore(tmp_path)


class TestEnsureExists:
    def test_creates_file_with_header(self, store: ResultsStore):
        store.ensure_exists()
        assert store.path.exists()
        assert store.path.read_text().strip() == HEADER

    def test_idempotent(self, store: ResultsStore):
        store.ensure_exists()
        store.ensure_exists()
        assert store.path.read_text().count(HEADER) == 1


class TestAppend:
    def test_appends_entry(self, store: ResultsStore):
        store.append(ResultEntry("2024-01-01T00:00:00", "search", "test hyp", "0.75", "KEEP"))
        lines = store.path.read_text().splitlines()
        assert len(lines) == 2  # header + 1 entry
        assert "search" in lines[1]
        assert "0.75" in lines[1]
        assert "KEEP" in lines[1]

    def test_append_creates_file(self, store: ResultsStore):
        store.append(ResultEntry("2024-01-01T00:00:00", "search", "hyp", "0.5", "KEEP"))
        assert store.path.exists()

    def test_append_now(self, store: ResultsStore):
        entry = store.append_now("search", "my hypothesis", "0.80", "KEEP")
        assert entry.layer == "search"
        assert entry.timestamp  # non-empty
        entries = store.get_all_entries()
        assert len(entries) == 1


class TestGetAllEntries:
    def test_empty_file(self, store: ResultsStore):
        store.ensure_exists()
        assert store.get_all_entries() == []

    def test_no_file(self, store: ResultsStore):
        assert store.get_all_entries() == []

    def test_returns_all(self, store: ResultsStore):
        store.append_now("search", "h1", "0.5", "KEEP")
        store.append_now("api", "h2", "PASS", "KEEP")
        assert len(store.get_all_entries()) == 2

    def test_filter_by_layer(self, store: ResultsStore):
        store.append_now("search", "h1", "0.5", "KEEP")
        store.append_now("api", "h2", "PASS", "KEEP")
        store.append_now("search", "h3", "0.6", "KEEP")
        assert len(store.get_all_entries("search")) == 2
        assert len(store.get_all_entries("api")) == 1


class TestCountLayerAttempts:
    def test_counts_all_outcomes(self, store: ResultsStore):
        store.append_now("search", "h1", "0.5", "KEEP")
        store.append_now("search", "h2", "0.5", "DISCARD")
        store.append_now("search", "h3", "FAIL", "DISCARD FAIL")
        assert store.count_layer_attempts("search") == 3

    def test_zero_for_unknown_layer(self, store: ResultsStore):
        store.ensure_exists()
        assert store.count_layer_attempts("unknown") == 0


class TestGetBestScore:
    def test_returns_best_keep(self, store: ResultsStore):
        store.append_now("search", "h1", "0.50", "KEEP")
        store.append_now("search", "h2", "0.50", "DISCARD")
        store.append_now("search", "h3", "0.70", "KEEP")
        store.append_now("search", "h4", "0.60", "KEEP")
        assert store.get_best_score("search") == 0.70

    def test_none_when_no_keeps(self, store: ResultsStore):
        store.append_now("search", "h1", "FAIL", "DISCARD FAIL")
        assert store.get_best_score("search") is None

    def test_none_when_empty(self, store: ResultsStore):
        assert store.get_best_score("search") is None

    def test_ignores_non_numeric_keeps(self, store: ResultsStore):
        store.append_now("api", "h1", "PASS", "KEEP")
        assert store.get_best_score("api") is None


class TestGetKeepCount:
    def test_counts_keeps(self, store: ResultsStore):
        store.append_now("search", "h1", "0.5", "KEEP")
        store.append_now("search", "h2", "0.5", "DISCARD")
        store.append_now("search", "h3", "0.7", "KEEP")
        assert store.get_keep_count("search") == 2


class TestGetRecentKeeps:
    def test_returns_last_n(self, store: ResultsStore):
        store.append_now("search", "h1", "0.50", "KEEP")
        store.append_now("search", "h2", "0.60", "KEEP")
        store.append_now("search", "h3", "0.60", "DISCARD")
        store.append_now("search", "h4", "0.70", "KEEP")
        recent = store.get_recent_keeps("search", 2)
        assert recent == [0.60, 0.70]

    def test_returns_all_if_fewer(self, store: ResultsStore):
        store.append_now("search", "h1", "0.50", "KEEP")
        recent = store.get_recent_keeps("search", 5)
        assert recent == [0.50]


class TestConsecutiveNonImprovements:
    def test_counts_from_tail(self, store: ResultsStore):
        store.append_now("search", "h1", "0.50", "KEEP")
        store.append_now("search", "h2", "0.50", "DISCARD")
        store.append_now("search", "h3", "0.50", "DISCARD")
        assert store.get_consecutive_non_improvements("search") == 2

    def test_zero_when_last_is_keep(self, store: ResultsStore):
        store.append_now("search", "h1", "0.50", "DISCARD")
        store.append_now("search", "h2", "0.60", "KEEP")
        assert store.get_consecutive_non_improvements("search") == 0

    def test_all_non_improvements(self, store: ResultsStore):
        store.append_now("search", "h1", "0.50", "DISCARD")
        store.append_now("search", "h2", "0.50", "DISCARD")
        assert store.get_consecutive_non_improvements("search") == 2

    def test_empty(self, store: ResultsStore):
        assert store.get_consecutive_non_improvements("search") == 0


class TestConsecutiveFailures:
    def test_counts_from_tail(self, store: ResultsStore):
        store.append_now("search", "h1", "0.50", "KEEP")
        store.append_now("search", "h2", "FAIL", "DISCARD FAIL")
        store.append_now("search", "h3", "FAIL", "DISCARD FAIL")
        assert store.get_consecutive_failures("search") == 2

    def test_zero_when_last_is_not_fail(self, store: ResultsStore):
        store.append_now("search", "h1", "FAIL", "DISCARD FAIL")
        store.append_now("search", "h2", "0.50", "KEEP")
        assert store.get_consecutive_failures("search") == 0

    def test_oracle_error(self, store: ResultsStore):
        store.append_now("search", "h1", "0.50", "KEEP")
        store.append_now("search", "h2", "FAIL", "ORACLE_ERROR")
        assert store.get_consecutive_failures("search") == 1

    def test_empty(self, store: ResultsStore):
        assert store.get_consecutive_failures("search") == 0
