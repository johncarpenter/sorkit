"""Tests for sorkit.server — MCP tool integration tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sorkit.server import mcp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def call_tool(name: str, args: dict) -> str:
    """Call an MCP tool via FastMCP's in-process client."""
    from fastmcp import Client

    async with Client(mcp) as client:
        result = await client.call_tool(name, args)
    # result is a list of content blocks; extract text
    return result.content[0].text if result.content else ""


def _git_init(project_dir: Path) -> None:
    subprocess.run(["git", "init"], cwd=project_dir, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=project_dir, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=project_dir, capture_output=True)
    (project_dir / ".gitkeep").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=project_dir, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial", "--quiet"], cwd=project_dir, capture_output=True)


# ---------------------------------------------------------------------------
# sor_init
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
class TestSorInit:
    async def test_returns_template_without_config(self, tmp_path: Path):
        result = await call_tool("sor_init", {"project_dir": str(tmp_path)})
        assert "Fill in this template" in result
        assert "project_name" in result
        assert "layers" in result

    async def test_creates_artifacts_with_config(self, tmp_path: Path):
        config = {
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
        result = await call_tool("sor_init", {
            "project_dir": str(tmp_path),
            "config": config,
        })
        assert "Initialized SOR" in result
        assert (tmp_path / "sor.yaml").exists()
        assert (tmp_path / "CLAUDE.md").exists()

    async def test_invalid_config_returns_error(self, tmp_path: Path):
        config = {
            "project_name": "Bad",
            "always_frozen": [],
            "defaults": {},
            "layers": [],
        }
        result = await call_tool("sor_init", {
            "project_dir": str(tmp_path),
            "config": config,
        })
        assert "ERROR" in result


# ---------------------------------------------------------------------------
# sor_add_layer
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
class TestSorAddLayer:
    async def test_adds_layer(self, sor_project: Path):
        result = await call_tool("sor_add_layer", {
            "project_dir": str(sor_project),
            "name": "vba",
            "surface": ["vba/main.bas"],
            "contracts": "tests/test_vba.py",
        })
        assert "Added layer 'vba'" in result

    async def test_no_config_returns_error(self, tmp_path: Path):
        result = await call_tool("sor_add_layer", {
            "project_dir": str(tmp_path),
            "name": "test",
            "surface": ["a.py"],
            "contracts": "tests/test.py",
        })
        assert "ERROR" in result


# ---------------------------------------------------------------------------
# sor_run_oracle
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
class TestSorRunOracle:
    async def test_passing_contracts(self, tmp_path: Path):
        # Set up a project with passing tests
        (tmp_path / "sor.yaml").write_text(
            "project_name: Test\n"
            "always_frozen: []\n"
            "defaults:\n  test_runner: 'python -m pytest'\n"
            "layers:\n"
            "  - name: api\n"
            "    surface: [src/api.py]\n"
            "    oracle:\n"
            "      contracts: test_contract.py\n"
            "      scored: false\n"
        )
        (tmp_path / "test_contract.py").write_text("def test_ok(): assert True\n")

        result = await call_tool("sor_run_oracle", {
            "layer": "api",
            "project_dir": str(tmp_path),
        })
        assert "PASS" in result

    async def test_invalid_layer_returns_error(self, sor_project: Path):
        result = await call_tool("sor_run_oracle", {
            "layer": "nonexistent",
            "project_dir": str(sor_project),
        })
        assert "ERROR" in result


# ---------------------------------------------------------------------------
# sor_ratchet
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
class TestSorRatchet:
    async def test_keep_on_pass(self, tmp_path: Path):
        # Set up git + passing test
        _git_init(tmp_path)
        (tmp_path / "sor.yaml").write_text(
            "project_name: Test\n"
            "always_frozen: []\n"
            "defaults:\n  test_runner: 'python -m pytest'\n"
            "layers:\n"
            "  - name: api\n"
            "    surface: [src/api.py]\n"
            "    oracle:\n"
            "      contracts: test_contract.py\n"
            "      scored: false\n"
        )
        (tmp_path / "test_contract.py").write_text("def test_ok(): assert True\n")
        (tmp_path / "src").mkdir(exist_ok=True)
        (tmp_path / "src" / "api.py").write_text("# api\n")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "setup", "--quiet"], cwd=tmp_path, capture_output=True)

        result = await call_tool("sor_ratchet", {
            "layer": "api",
            "hypothesis": "make it work",
            "project_dir": str(tmp_path),
        })
        assert "STOP:ALL_PASS" in result

    async def test_discard_on_fail(self, tmp_path: Path):
        _git_init(tmp_path)
        (tmp_path / "sor.yaml").write_text(
            "project_name: Test\n"
            "always_frozen: []\n"
            "defaults:\n  test_runner: 'python -m pytest'\n"
            "layers:\n"
            "  - name: api\n"
            "    surface: [src/api.py]\n"
            "    oracle:\n"
            "      contracts: test_contract.py\n"
            "      scored: false\n"
        )
        (tmp_path / "test_contract.py").write_text("def test_fail(): assert False\n")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "setup", "--quiet"], cwd=tmp_path, capture_output=True)

        result = await call_tool("sor_ratchet", {
            "layer": "api",
            "hypothesis": "bad change",
            "project_dir": str(tmp_path),
        })
        assert "DISCARD FAIL" in result


# ---------------------------------------------------------------------------
# sor_status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
class TestSorStatus:
    async def test_all_layers(self, sor_project: Path):
        result = await call_tool("sor_status", {
            "project_dir": str(sor_project),
        })
        assert "Test Project" in result
        assert "search" in result
        assert "api" in result

    async def test_single_layer(self, sor_project: Path):
        result = await call_tool("sor_status", {
            "layer": "search",
            "project_dir": str(sor_project),
        })
        assert "search" in result
        assert "scored" in result

    async def test_no_config_returns_error(self, tmp_path: Path):
        result = await call_tool("sor_status", {
            "project_dir": str(tmp_path),
        })
        assert "ERROR" in result


# ---------------------------------------------------------------------------
# sor_results
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
class TestSorResults:
    async def test_no_results(self, sor_project: Path):
        # Initialize results.tsv
        from sorkit.results import ResultsStore
        store = ResultsStore(sor_project)
        store.ensure_exists()

        result = await call_tool("sor_results", {
            "project_dir": str(sor_project),
        })
        assert "No results" in result

    async def test_with_results(self, sor_project: Path):
        from sorkit.results import ResultsStore
        store = ResultsStore(sor_project)
        store.append_now("search", "test hypothesis", "0.75", "KEEP")
        store.append_now("search", "another try", "0.70", "DISCARD")

        result = await call_tool("sor_results", {
            "project_dir": str(sor_project),
        })
        assert "2 entries" in result
        assert "test hypothesis" in result

    async def test_filter_by_layer(self, sor_project: Path):
        from sorkit.results import ResultsStore
        store = ResultsStore(sor_project)
        store.append_now("search", "s1", "0.75", "KEEP")
        store.append_now("api", "a1", "PASS", "KEEP")

        result = await call_tool("sor_results", {
            "layer": "search",
            "project_dir": str(sor_project),
        })
        assert "1 entries" in result
        assert "layer: search" in result
