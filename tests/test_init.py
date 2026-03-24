"""Tests for sorkit.init — config template, CLAUDE.md generation, skill codegen."""

from __future__ import annotations

from pathlib import Path

import pytest

from sorkit.config import ConfigError, load_config
from sorkit.init import (
    add_layer,
    config_from_dict,
    generate_claude_md,
    generate_config_template,
    generate_experiment_loop_skill,
    initialize_results_tsv,
    validate_and_save_config,
)


class TestGenerateConfigTemplate:
    def test_returns_dict(self):
        template = generate_config_template()
        assert isinstance(template, dict)

    def test_has_required_keys(self):
        template = generate_config_template()
        assert "project_name" in template
        assert "always_frozen" in template
        assert "defaults" in template
        assert "layers" in template

    def test_defaults_have_descriptions(self):
        template = generate_config_template()
        defaults = template["defaults"]
        assert "_description" in defaults
        assert "_description" in defaults["test_runner"]

    def test_layers_have_examples(self):
        template = generate_config_template()
        layers = template["layers"]
        assert "_example_layer" in layers
        assert "_example_scored_layer" in layers


class TestConfigFromDict:
    def test_plain_dict(self):
        raw = {
            "project_name": "Test",
            "always_frozen": ["tests/"],
            "defaults": {"test_runner": "pytest", "max_attempts": 10},
            "layers": [
                {
                    "name": "api",
                    "surface": ["src/api.py"],
                    "oracle": {"contracts": "tests/test_api.py", "scored": False},
                }
            ],
        }
        result = config_from_dict(raw)
        assert result["project_name"] == "Test"
        assert result["always_frozen"] == ["tests/"]
        assert result["defaults"]["test_runner"] == "pytest"
        assert len(result["layers"]) == 1

    def test_template_format(self):
        raw = {
            "project_name": {"_value": "Template Project", "_description": "..."},
            "always_frozen": {"_value": ["tests/", "sor.yaml"], "_description": "..."},
            "defaults": {
                "_description": "...",
                "test_runner": {"_value": "npm test", "_description": "..."},
                "max_attempts": {"_value": 15, "_description": "..."},
            },
            "layers": {
                "_description": "...",
                "_value": [
                    {
                        "name": "core",
                        "surface": ["src/core.py"],
                        "oracle": {"contracts": "tests/test_core.py", "scored": False},
                    }
                ],
            },
        }
        result = config_from_dict(raw)
        assert result["project_name"] == "Template Project"
        assert result["always_frozen"] == ["tests/", "sor.yaml"]
        assert result["defaults"]["test_runner"] == "npm test"
        assert result["defaults"]["max_attempts"] == 15
        assert len(result["layers"]) == 1


class TestValidateAndSaveConfig:
    def test_creates_all_artifacts(self, tmp_path: Path):
        config_dict = {
            "project_name": "Test Project",
            "always_frozen": ["tests/", "sor.yaml"],
            "defaults": {"test_runner": "python -m pytest", "max_attempts": 20},
            "layers": [
                {
                    "name": "api",
                    "surface": ["src/api.py"],
                    "oracle": {"contracts": "tests/test_api.py", "scored": False},
                }
            ],
        }
        config = validate_and_save_config(config_dict, tmp_path)
        assert (tmp_path / "sor.yaml").exists()
        assert (tmp_path / "CLAUDE.md").exists()
        assert (tmp_path / ".claude" / "skills" / "experiment-loop.md").exists()
        assert (tmp_path / "results.tsv").exists()
        assert config.project_name == "Test Project"

    def test_invalid_config_raises(self, tmp_path: Path):
        config_dict = {
            "project_name": "Bad",
            "always_frozen": [],
            "defaults": {},
            "layers": [],  # no layers = invalid
        }
        with pytest.raises(ConfigError):
            validate_and_save_config(config_dict, tmp_path)


class TestGenerateClaudeMd:
    def test_contains_project_name(self, sor_project: Path):
        cfg = load_config(sor_project)
        generate_claude_md(cfg, sor_project)
        content = (sor_project / "CLAUDE.md").read_text()
        assert "# Test Project" in content

    def test_contains_frozen_files(self, sor_project: Path):
        cfg = load_config(sor_project)
        generate_claude_md(cfg, sor_project)
        content = (sor_project / "CLAUDE.md").read_text()
        assert "tests/" in content
        assert "sor.yaml" in content

    def test_contains_mutation_surface_table(self, sor_project: Path):
        cfg = load_config(sor_project)
        generate_claude_md(cfg, sor_project)
        content = (sor_project / "CLAUDE.md").read_text()
        assert "| Layer | Name | Mutable Files | Oracle Type |" in content
        assert "| 1 | search |" in content
        assert "| 2 | api |" in content
        assert "Scored (composite metric)" in content
        assert "Pass/fail" in content

    def test_contains_thresholds_table(self, sor_project: Path):
        cfg = load_config(sor_project)
        generate_claude_md(cfg, sor_project)
        content = (sor_project / "CLAUDE.md").read_text()
        assert "| Parameter | Value |" in content
        assert "Layer 1 (search) max attempts | 30" in content
        assert "Layer 1 (search) target score | 0.9" in content
        assert "Layer 2 (api) max attempts | 15" in content
        assert "Plateau limit" in content

    def test_contains_sor_description(self, sor_project: Path):
        cfg = load_config(sor_project)
        generate_claude_md(cfg, sor_project)
        content = (sor_project / "CLAUDE.md").read_text()
        assert "Surface-Oracle-Ratchet" in content
        assert "mutation surface" in content


class TestGenerateExperimentLoopSkill:
    def test_creates_skill_file(self, sor_project: Path):
        cfg = load_config(sor_project)
        generate_experiment_loop_skill(cfg, sor_project)
        path = sor_project / ".claude" / "skills" / "experiment-loop.md"
        assert path.exists()

    def test_skill_content(self, sor_project: Path):
        cfg = load_config(sor_project)
        generate_experiment_loop_skill(cfg, sor_project)
        content = (sor_project / ".claude" / "skills" / "experiment-loop.md").read_text()
        assert "Autonomous Experiment Loop" in content
        assert "HYPOTHESIS:" in content
        assert "KEEP score=" in content
        assert "STOP:" in content
        assert "TARGET_MET" in content


class TestInitializeResultsTsv:
    def test_creates_if_missing(self, tmp_path: Path):
        initialize_results_tsv(tmp_path)
        path = tmp_path / "results.tsv"
        assert path.exists()
        assert "timestamp" in path.read_text()

    def test_idempotent(self, tmp_path: Path):
        initialize_results_tsv(tmp_path)
        initialize_results_tsv(tmp_path)
        content = (tmp_path / "results.tsv").read_text()
        assert content.count("timestamp") == 1


class TestAddLayer:
    def test_adds_layer(self, sor_project: Path):
        cfg = load_config(sor_project)
        assert len(cfg.layers) == 2

        new_layer = {
            "name": "vba",
            "surface": ["vba/main.bas"],
            "oracle": {"contracts": "tests/test_vba.py", "scored": False},
        }
        updated = add_layer(cfg, new_layer, sor_project)
        assert len(updated.layers) == 3
        assert updated.layers[2].name == "vba"

        # Verify persisted
        reloaded = load_config(sor_project)
        assert len(reloaded.layers) == 3

    def test_invalid_layer_rejected(self, sor_project: Path):
        cfg = load_config(sor_project)
        bad_layer = {
            "name": "search",  # duplicate name
            "surface": ["src/dup.py"],
            "oracle": {"contracts": "tests/test_dup.py", "scored": False},
        }
        with pytest.raises(ConfigError):
            add_layer(cfg, bad_layer, sor_project)
        # Config should be unchanged
        assert len(cfg.layers) == 2

    def test_regenerates_claude_md(self, sor_project: Path):
        cfg = load_config(sor_project)
        generate_claude_md(cfg, sor_project)

        new_layer = {
            "name": "vba",
            "surface": ["vba/main.bas"],
            "oracle": {"contracts": "tests/test_vba.py", "scored": False},
        }
        add_layer(cfg, new_layer, sor_project)

        content = (sor_project / "CLAUDE.md").read_text()
        assert "| 3 | vba |" in content
