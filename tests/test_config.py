"""Tests for sorkit.config — data model, load/save, validation."""

from pathlib import Path

import pytest
import yaml

from sorkit.config import (
    ConfigError,
    DefaultConfig,
    LayerConfig,
    MetricConfig,
    OracleConfig,
    SorConfig,
    ThresholdConfig,
    load_config,
    resolve_layer_index,
    resolve_threshold,
    save_config,
    validate_config,
)


class TestLoadConfig:
    def test_loads_project_name(self, sor_project: Path):
        cfg = load_config(sor_project)
        assert cfg.project_name == "Test Project"

    def test_loads_always_frozen(self, sor_project: Path):
        cfg = load_config(sor_project)
        assert "tests/" in cfg.always_frozen
        assert "sor.yaml" in cfg.always_frozen

    def test_loads_defaults(self, sor_project: Path):
        cfg = load_config(sor_project)
        assert cfg.defaults.test_runner == "python -m pytest"
        assert cfg.defaults.max_attempts == 20
        assert cfg.defaults.plateau_limit == 5

    def test_loads_layers(self, sor_project: Path):
        cfg = load_config(sor_project)
        assert len(cfg.layers) == 2
        assert cfg.layers[0].name == "search"
        assert cfg.layers[1].name == "api"

    def test_loads_surface(self, sor_project: Path):
        cfg = load_config(sor_project)
        assert "src/search/query_builder.py" in cfg.layers[0].surface
        assert "src/search/ranker.py" in cfg.layers[0].surface

    def test_loads_scored_oracle(self, sor_project: Path):
        cfg = load_config(sor_project)
        oracle = cfg.layers[0].oracle
        assert oracle.scored is True
        assert oracle.contracts == "tests/test_search_contract.py"
        assert oracle.scored_tests == "tests/test_search_relevance.py"
        assert len(oracle.metrics) == 2
        assert oracle.metrics[0].name == "relevance"
        assert oracle.metrics[0].weight == 0.7
        assert oracle.metrics[1].extract == "VALUE_ACCURACY"

    def test_loads_unscored_oracle(self, sor_project: Path):
        cfg = load_config(sor_project)
        oracle = cfg.layers[1].oracle
        assert oracle.scored is False
        assert oracle.metrics == []

    def test_loads_layer_thresholds(self, sor_project: Path):
        cfg = load_config(sor_project)
        assert cfg.layers[0].thresholds.target_score == 0.90
        assert cfg.layers[0].thresholds.max_attempts == 30
        assert cfg.layers[1].thresholds.max_attempts == 15

    def test_missing_sor_yaml_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path)

    def test_empty_sor_yaml_raises(self, tmp_path: Path):
        (tmp_path / "sor.yaml").write_text("")
        with pytest.raises(ValueError, match="Invalid sor.yaml"):
            load_config(tmp_path)


class TestSaveConfig:
    def test_round_trip(self, sor_project: Path):
        original = load_config(sor_project)
        save_config(original, sor_project)
        reloaded = load_config(sor_project)

        assert reloaded.project_name == original.project_name
        assert reloaded.always_frozen == original.always_frozen
        assert reloaded.defaults.test_runner == original.defaults.test_runner
        assert reloaded.defaults.max_attempts == original.defaults.max_attempts
        assert len(reloaded.layers) == len(original.layers)

        for orig_layer, new_layer in zip(original.layers, reloaded.layers):
            assert new_layer.name == orig_layer.name
            assert new_layer.surface == orig_layer.surface
            assert new_layer.oracle.scored == orig_layer.oracle.scored
            assert new_layer.oracle.contracts == orig_layer.oracle.contracts
            if orig_layer.oracle.scored:
                assert len(new_layer.oracle.metrics) == len(orig_layer.oracle.metrics)
                for om, nm in zip(orig_layer.oracle.metrics, new_layer.oracle.metrics):
                    assert nm.name == om.name
                    assert nm.extract == om.extract
                    assert nm.weight == om.weight

    def test_saved_yaml_is_valid(self, sor_project: Path):
        cfg = load_config(sor_project)
        save_config(cfg, sor_project)
        raw = yaml.safe_load((sor_project / "sor.yaml").read_text())
        assert raw["project_name"] == "Test Project"
        assert isinstance(raw["layers"], list)


class TestResolveThreshold:
    def test_layer_override(self, sor_project: Path):
        cfg = load_config(sor_project)
        # Layer 0 overrides max_attempts to 30
        assert resolve_threshold(cfg, 0, "max_attempts") == 30

    def test_falls_back_to_default(self, sor_project: Path):
        cfg = load_config(sor_project)
        # Layer 0 doesn't override consecutive_failure_limit
        assert resolve_threshold(cfg, 0, "consecutive_failure_limit") == 5

    def test_layer_1_override(self, sor_project: Path):
        cfg = load_config(sor_project)
        assert resolve_threshold(cfg, 1, "max_attempts") == 15

    def test_layer_1_default(self, sor_project: Path):
        cfg = load_config(sor_project)
        assert resolve_threshold(cfg, 1, "plateau_limit") == 5


class TestResolveLayerIndex:
    def test_by_index(self, sor_project: Path):
        cfg = load_config(sor_project)
        assert resolve_layer_index(cfg, "0") == 0
        assert resolve_layer_index(cfg, "1") == 1

    def test_by_name(self, sor_project: Path):
        cfg = load_config(sor_project)
        assert resolve_layer_index(cfg, "search") == 0
        assert resolve_layer_index(cfg, "api") == 1

    def test_case_insensitive(self, sor_project: Path):
        cfg = load_config(sor_project)
        assert resolve_layer_index(cfg, "SEARCH") == 0
        assert resolve_layer_index(cfg, "Api") == 1

    def test_invalid_name_raises(self, sor_project: Path):
        cfg = load_config(sor_project)
        with pytest.raises(ValueError, match="No layer named"):
            resolve_layer_index(cfg, "nonexistent")

    def test_out_of_range_index_raises(self, sor_project: Path):
        cfg = load_config(sor_project)
        with pytest.raises(ValueError, match="out of range"):
            resolve_layer_index(cfg, "99")


class TestValidateConfig:
    def test_valid_config_no_errors(self, sor_project: Path):
        cfg = load_config(sor_project)
        errors = validate_config(cfg)
        assert errors == []

    def test_no_layers(self):
        cfg = SorConfig(
            project_name="empty",
            always_frozen=[],
            defaults=DefaultConfig(),
            layers=[],
        )
        errors = validate_config(cfg)
        assert any("No layers" in e for e in errors)

    def test_duplicate_layer_names(self):
        layer = LayerConfig(
            name="dup",
            surface=["a.py"],
            oracle=OracleConfig(contracts="tests/test.py"),
        )
        cfg = SorConfig(
            project_name="test",
            always_frozen=[],
            defaults=DefaultConfig(),
            layers=[layer, layer],
        )
        errors = validate_config(cfg)
        assert any("duplicate" in e for e in errors)

    def test_empty_surface(self):
        layer = LayerConfig(
            name="empty",
            surface=[],
            oracle=OracleConfig(contracts="tests/test.py"),
        )
        cfg = SorConfig(
            project_name="test",
            always_frozen=[],
            defaults=DefaultConfig(),
            layers=[layer],
        )
        errors = validate_config(cfg)
        assert any("surface is empty" in e for e in errors)

    def test_scored_without_tests(self):
        layer = LayerConfig(
            name="bad",
            surface=["a.py"],
            oracle=OracleConfig(contracts="tests/test.py", scored=True),
        )
        cfg = SorConfig(
            project_name="test",
            always_frozen=[],
            defaults=DefaultConfig(),
            layers=[layer],
        )
        errors = validate_config(cfg)
        assert any("scored_tests" in e for e in errors)

    def test_weights_dont_sum_to_one(self):
        layer = LayerConfig(
            name="bad",
            surface=["a.py"],
            oracle=OracleConfig(
                contracts="tests/test.py",
                scored=True,
                scored_tests="tests/test_score.py",
                metrics=[
                    MetricConfig(name="a", extract="A", weight=0.5),
                    MetricConfig(name="b", extract="B", weight=0.3),
                ],
            ),
        )
        cfg = SorConfig(
            project_name="test",
            always_frozen=[],
            defaults=DefaultConfig(),
            layers=[layer],
        )
        errors = validate_config(cfg)
        assert any("weights sum to" in e for e in errors)

    def test_no_contracts(self):
        layer = LayerConfig(
            name="notest",
            surface=["a.py"],
            oracle=OracleConfig(contracts=""),
        )
        cfg = SorConfig(
            project_name="test",
            always_frozen=[],
            defaults=DefaultConfig(),
            layers=[layer],
        )
        errors = validate_config(cfg)
        assert any("no contract tests" in e for e in errors)
