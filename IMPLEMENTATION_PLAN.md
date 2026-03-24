# Sorkit MCP Server — Implementation Plan

Convert sorkit from a bash scaffold kit into a Python MCP server distributed via PyPI (`pip install sorkit`).

## Package Structure

```
sorkit/
├── pyproject.toml
├── README.md
├── LICENSE.md
├── src/sorkit/
│   ├── __init__.py          # Version, public API
│   ├── __main__.py          # `python -m sorkit` / `sorkit` CLI entry
│   ├── server.py            # FastMCP server + all tool registrations
│   ├── config.py            # sor.yaml dataclasses, load/save/validate
│   ├── oracle.py            # Test runner, metric extraction, composite scoring
│   ├── ratchet.py           # Git commit/reset, score comparison, stopping conditions
│   ├── results.py           # results.tsv read/write/query
│   ├── frozen.py            # Frozen file computation per layer
│   ├── init.py              # sor.yaml generation, CLAUDE.md + skill codegen
│   └── notify.py            # Notifications (Slack, email, desktop, file)
└── tests/
    ├── conftest.py
    ├── test_config.py
    ├── test_oracle.py
    ├── test_ratchet.py
    ├── test_results.py
    ├── test_frozen.py
    ├── test_init.py
    ├── test_notify.py
    └── test_server.py
```

## MCP Tools

| Tool | Purpose |
|------|---------|
| `sor_init` | Build sor.yaml interactively — returns template on first call, accepts filled config on second |
| `sor_add_layer` | Add a layer to existing config |
| `sor_run_oracle` | Run oracle for a layer, return COMPOSITE score or PASS/FAIL |
| `sor_ratchet` | One iteration: oracle → compare → commit/reset → check stops |
| `sor_status` | Progress summary: attempts, best score, keeps, proximity to stops |
| `sor_results` | Query results.tsv history |

The LLM drives the experiment loop by calling `sor_ratchet` repeatedly, following the generated experiment-loop skill. For pass/fail layers the loop is trivial (one KEEP = done). For scored layers the LLM formulates a new hypothesis each iteration.

## Key Design Decisions

- **Project dir**: Every tool accepts optional `project_dir` (defaults to cwd)
- **Interactive config**: `sor_init()` returns a template; `sor_init(config={...})` saves it. The LLM is the interactive layer.
- **No bash**: All arithmetic in Python (no `bc`), all subprocess via `asyncio.create_subprocess_exec`
- **Cross-platform**: `pathlib.Path`, platform-detected notifications, no shell=True
- **Frozen files**: Advisory via CLAUDE.md + `sor_status`. Optional guard hook still generated for Claude Code users.
- **Minimal deps**: `fastmcp` + `pyyaml` only. Slack webhook via `urllib.request`.

---

## Stage 1: Config Data Model
**Goal**: Dataclasses for sor.yaml + load/save/validate
**Files**: `src/sorkit/config.py`
**Details**:
- `SorConfig`, `LayerConfig`, `OracleConfig`, `MetricConfig`, `ThresholdConfig`, `DefaultConfig` dataclasses
- `load_config(project_dir) -> SorConfig` — parse sor.yaml
- `save_config(config, project_dir)` — write sor.yaml
- `resolve_threshold(config, layer_idx, key)` — layer override > default
- `resolve_layer_index(config, name_or_index) -> int`
- Validation: weights sum to 1.0 for scored layers, unique layer names, non-empty surfaces
**Success Criteria**: Round-trip existing sor.yaml without data loss
**Tests**: Load/save/validate, threshold resolution, error cases
**Status**: Complete

## Stage 2: Results TSV + Frozen Files
**Goal**: Port results tracking and frozen file computation
**Files**: `src/sorkit/results.py`, `src/sorkit/frozen.py`
**Details**:
- `ResultEntry` dataclass + `ResultsStore` class:
  - `append()`, `count_layer_attempts()`, `get_best_score()`, `get_recent_keeps()`
  - `get_consecutive_non_improvements()`, `get_consecutive_failures()`
  - `get_all_entries()`, `get_keep_count()`
- `get_frozen_paths(config, layer_idx) -> list[str]` — always_frozen + surfaces from layers < idx
- `is_path_frozen(path, frozen_paths) -> bool`
**Success Criteria**: Queries match bash script behavior. Frozen paths match `sor-parse.py frozen_for`.
**Tests**: Append/query round-trips, consecutive counting, edge cases, frozen path generation
**Status**: Complete

## Stage 3: Oracle Runner
**Goal**: Port `run_oracle.sh` — run tests, extract metrics, compute composite
**Files**: `src/sorkit/oracle.py`
**Details**:
- `OracleResult` dataclass: `passed`, `scored`, `composite`, `metrics`, `output`, `error`, `error_message`
- `async run_oracle(config, layer_idx, project_dir) -> OracleResult`:
  1. Run contract tests via subprocess (`test_runner` + contracts glob + `-x --tb=short -q`)
  2. If fail → return failed result
  3. If not scored → return passed
  4. Run scored_tests, extract metrics via `^{extract}:\s+(\S+)` regex, compute weighted composite
- Distinguish test failure vs oracle error (infrastructure crash)
**Success Criteria**: Correct metric extraction and composite math. Handles failures and errors.
**Tests**: Dummy test files in tmp_path, contract pass/fail, metric extraction, error classification
**Status**: Complete

## Stage 4: Ratchet Engine
**Goal**: Port `ratchet.sh` — single iteration with git commit/reset and all 8 stopping conditions
**Files**: `src/sorkit/ratchet.py`
**Depends On**: Stages 1, 2, 3
**Details**:
- `RatchetOutcome` enum: KEEP, DISCARD, STOP
- `StopReason` enum: TARGET_MET, ALL_PASS, PLATEAU, DIMINISHING, MAX_ATTEMPTS, CONSECUTIVE_FAILURES, ORACLE_ERROR
- `RatchetResult` dataclass: outcome, score, prev_best, stop_reason, attempts, keeps, message
- `async ratchet_once(config, layer_idx, hypothesis, project_dir) -> RatchetResult`:
  1. Run oracle
  2. Oracle error → reset, record, check consecutive failures
  3. Test failure → reset, record, check consecutive failures + max attempts
  4. Pass/fail layer passed → commit, record, STOP(ALL_PASS)
  5. Scored layer improved → commit, record, check TARGET_MET + DIMINISHING
  6. Scored layer not improved → reset, record, check PLATEAU
  7. Check MAX_ATTEMPTS always
- Git via `asyncio.create_subprocess_exec("git", ..., cwd=project_dir)`
**Success Criteria**: Commits on improvement, resets otherwise. All 8 stops trigger correctly.
**Tests**: Git repo fixture, improvement/non-improvement, each stopping condition
**Status**: Complete

## Stage 5: Notifications
**Goal**: Port `notify.sh` — multi-channel notifications on stop conditions
**Files**: `src/sorkit/notify.py`
**Details**:
- `async send_notifications(config, layer_name, score, attempts, stop_reason, project_dir)`
- Channels: file (always), Slack (SLACK_WEBHOOK_URL), email (NOTIFY_EMAIL), desktop (platform-detected)
- Each channel independent — one failing doesn't block others
- Message includes: project name, layer, status, score, attempts, keeps
**Success Criteria**: Notifications fire on stop. Channels work independently.
**Tests**: Mock subprocess/HTTP, verify message format
**Status**: Complete

## Stage 6: Init / Codegen
**Goal**: Port `sor-init.sh` — generate config template, CLAUDE.md, experiment-loop skill
**Files**: `src/sorkit/init.py`
**Details**:
- `generate_config_template() -> dict` — JSON template with defaults + descriptions
- `validate_and_save_config(config_dict, project_dir) -> SorConfig`
- `generate_claude_md(config, project_dir)` — frozen files table, mutation surfaces table, thresholds table
- `generate_experiment_loop_skill(project_dir)` — .claude/skills/experiment-loop.md
- `initialize_results_tsv(project_dir)`
- `add_layer(config, layer_dict, project_dir) -> SorConfig`
**Success Criteria**: Generated CLAUDE.md matches current sor-init.sh output format
**Tests**: Generate from known config, verify structure, add layer round-trip
**Status**: Complete

## Stage 7: MCP Server + Tools
**Goal**: Wire everything as FastMCP server with all tools
**Files**: `src/sorkit/server.py`, `src/sorkit/__init__.py`, `src/sorkit/__main__.py`
**Depends On**: Stages 1–6
**Details**:
- `sor_init(project_dir, config=None)` — template if no config, save+generate if config provided
- `sor_add_layer(project_dir, name, surface, contracts, scored, ...)` — add layer to existing config
- `sor_run_oracle(layer, project_dir=".")` — run oracle, return formatted result
- `sor_ratchet(layer, hypothesis, project_dir=".")` — one iteration, return KEEP/DISCARD/STOP format
- `sor_status(layer=None, project_dir=".")` — progress summary
- `sor_results(layer=None, last_n=20, project_dir=".")` — results history table
- Entry: `python -m sorkit` or `sorkit` CLI command
**Success Criteria**: All tools callable via MCP. Server starts correctly.
**Tests**: FastMCP test client, call each tool, verify responses
**Status**: Complete

## Stage 8: Packaging + PyPI
**Goal**: Package for `pip install sorkit`
**Files**: `pyproject.toml`, `README.md`, `LICENSE.md`
**Details**:
- Build system: hatchling
- Dependencies: `fastmcp>=2.0`, `pyyaml>=6.0`
- Optional: `httpx` for Slack (use `urllib.request` by default)
- Console script: `sorkit` → `sorkit.__main__:main`
- Python >=3.10
- `src/` layout
**Success Criteria**: `pip install .` works, `sorkit` command starts server
**Tests**: Build wheel, install in fresh venv, verify startup
**Status**: Complete

## Sequencing

```
Stage 1 (config) ──┬── Stage 2 (results + frozen)
                   ├── Stage 3 (oracle)
                   ├── Stage 5 (notify)
                   └── Stage 6 (init/codegen)
                        │
Stages 2+3 ────────── Stage 4 (ratchet)
                        │
Stages 1-6 ────────── Stage 7 (MCP server)
                        │
Stage 7 ───────────── Stage 8 (packaging)
```

Stages 2, 3, 5, 6 can run in parallel after Stage 1.
