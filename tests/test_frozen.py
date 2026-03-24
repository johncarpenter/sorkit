"""Tests for sorkit.frozen — frozen file computation."""

from pathlib import Path

import pytest

from sorkit.config import load_config
from sorkit.frozen import get_frozen_paths, is_path_frozen


class TestGetFrozenPaths:
    def test_layer_0_only_always_frozen(self, sor_project: Path):
        cfg = load_config(sor_project)
        frozen = get_frozen_paths(cfg, 0)
        assert "tests/" in frozen
        assert "sor.yaml" in frozen
        # No surface files from other layers
        assert "src/api/main.py" not in frozen

    def test_layer_1_includes_layer_0_surface(self, sor_project: Path):
        cfg = load_config(sor_project)
        frozen = get_frozen_paths(cfg, 1)
        assert "tests/" in frozen
        assert "sor.yaml" in frozen
        # Layer 0 surface is frozen
        assert "src/search/query_builder.py" in frozen
        assert "src/search/ranker.py" in frozen
        # Layer 1 surface is NOT frozen
        assert "src/api/main.py" not in frozen


class TestIsPathFrozen:
    def test_exact_match(self):
        assert is_path_frozen("sor.yaml", ["sor.yaml"]) is True

    def test_directory_match(self):
        assert is_path_frozen("tests/test_foo.py", ["tests/"]) is True

    def test_directory_without_slash(self):
        assert is_path_frozen("tests/test_foo.py", ["tests"]) is True

    def test_not_frozen(self):
        assert is_path_frozen("src/main.py", ["tests/", "sor.yaml"]) is False

    def test_partial_name_no_match(self):
        # "test_extra/" should not match "tests/"
        assert is_path_frozen("test_extra/foo.py", ["tests/"]) is False

    def test_nested_directory(self):
        assert is_path_frozen(".claude/skills/foo.md", [".claude/"]) is True

    def test_empty_frozen_list(self):
        assert is_path_frozen("anything.py", []) is False
