# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

sorkit is a Python MCP server (`pip install sorkit`) implementing the Surface-Oracle-Ratchet pattern for autonomous code optimization. An AI agent edits designated files (surfaces), is evaluated by frozen tests (oracles), and advances via git commit on improvement / git reset on failure (ratchet).

## Commands

```bash
# Install (editable with dev deps)
pip install -e ".[dev]"

# Run all tests
python -m pytest

# Run a single test file
python -m pytest tests/test_config.py

# Run a single test by name
python -m pytest -k test_loads_layers

# Run with verbose output
python -m pytest -v

# Run the MCP server
sorkit

# Build for distribution
python -m build
```

## Architecture

The package lives in `src/sorkit/` with this data flow:

```
sor.yaml → config.py → server.py (9 MCP tools)
                          ↓
                  oracle.py (run tests, extract metrics)
                          ↓
                  ratchet.py (compare → git commit/reset → check stops)
                          ↓
                  results.py (append to results.tsv)
                          ↓
                  notify.py (file/Slack/email/desktop)
```

**config.py** — Dataclass model for `sor.yaml`. `load_config()` parses YAML into `SorConfig` with layers, each containing `OracleConfig`, `MetricConfig`, `ThresholdConfig`. `resolve_threshold()` cascades layer overrides to defaults. `resolve_layer_index()` accepts name or numeric index.

**server.py** — FastMCP server (`from fastmcp import FastMCP`). Nine `@mcp.tool()` functions. `sor_init` uses a two-call pattern: no config returns a template, with config saves and generates artifacts. `sor_ratchet` is the core loop tool.

**oracle.py** — Async subprocess runner. Contracts run first (`-x --tb=short -q`), scored tests add `-s` to capture `print()` output. `_extract_metric()` uses regex `^{PATTERN}:\s+(\S+)` to pull floats from stdout. Returns `OracleResult` with composite score.

**ratchet.py** — `ratchet_once()` is the convergence engine. Checks 7 stopping conditions: TARGET_MET, ALL_PASS, PLATEAU, DIMINISHING, MAX_ATTEMPTS, CONSECUTIVE_FAILURES, ORACLE_ERROR. Git operations use `asyncio.create_subprocess_exec`.

**init.py** — Generates `CLAUDE.md`, `.claude/skills/experiment-loop.md`, and `results.tsv` from config. `config_from_dict()` handles both template format (with `_value`/`_description` keys) and plain dicts.

**results.py** — `ResultsStore` reads/writes a TSV file. Methods like `get_best_score()`, `get_consecutive_failures()`, `get_consecutive_non_improvements()` drive stopping condition checks.

**frozen.py** — `get_frozen_paths()` computes the full frozen set: `always_frozen` + surfaces from all layers below the current one.

**audit.py** — Analysis tools over `ResultsStore`: score progression with running best, hypothesis grouping with keep/discard/fail counts, full audit reports with convergence estimates.

## Testing Patterns

- All tests are async-compatible (`asyncio_mode = "auto"` in pyproject.toml)
- Shared fixture `sor_project` (in `tests/conftest.py`) creates a tmp dir with a valid `sor.yaml`
- Server tests use `async with Client(mcp) as client` then `result = await client.call_tool(name, args)` — access output via `result.content[0].text`
- Oracle/ratchet tests mock `asyncio.create_subprocess_exec` to avoid real subprocess calls

## Example

`examples/sentiment/` is a self-contained demo: a naive sentiment classifier (~40% accuracy) that an agent optimizes against 50 labeled examples. Layer 1 is scored (classifier), Layer 2 is pass/fail (API stub). Run from that directory with `python -m pytest tests/ -s`.
