# sorkit — Surface-Oracle-Ratchet MCP Server

An MCP server that enables AI agents to autonomously iterate on code while a
human-authored test suite acts as the objective function. The agent can only edit
designated files ("surfaces"), is evaluated by frozen tests ("oracles"), and
advances only when it improves ("ratchet").

```
pip install sorkit
```

## The Pattern

```
Human writes tests + golden data  →  frozen (agent can't touch)
Agent edits code  →  surface (agent's playground)
Tests run automatically  →  oracle (pass/fail + optional score)
Score improves?  →  git commit (ratchet forward)
Score doesn't?   →  git reset (try again)
Stopping condition?  →  notify human, stop
```

Layers are worked bottom-up. Each completed layer freezes before the next starts,
so the agent can never regress previous work.

## Quick Start

### 1. Install

```bash
pip install sorkit
```

### 2. Add to your MCP client

For Claude Code, add to your project's `.claude/settings.json`:

```json
{
  "mcpServers": {
    "sorkit": {
      "command": "sorkit"
    }
  }
}
```

### 3. Initialize

Ask your agent to call `sor_init` with your project directory. It will return
a config template. Fill in your layers, surfaces, and tests, then call
`sor_init` again with the completed config:

```yaml
project_name: "My Search Engine"

always_frozen:
  - "fixtures/"
  - "tests/"
  - "sor.yaml"

defaults:
  test_runner: "python -m pytest"
  max_attempts: 20
  plateau_limit: 5

layers:
  - name: "indexer"
    surface:
      - "src/indexer.py"
      - "src/tokenizer.py"
    oracle:
      contracts: "tests/test_indexer_contract.py"
      scored: true
      scored_tests: "tests/test_indexer_quality.py"
      metrics:
        - name: "recall"
          extract: "RECALL_SCORE"
          weight: 0.6
        - name: "precision"
          extract: "PRECISION_SCORE"
          weight: 0.4
    thresholds:
      target_score: 0.85
      max_attempts: 25

  - name: "api"
    surface:
      - "src/api/routes.py"
    oracle:
      contracts: "tests/test_api_*.py"
      scored: false
    thresholds:
      max_attempts: 10
```

This generates `sor.yaml`, `CLAUDE.md`, `.claude/skills/experiment-loop.md`,
and `results.tsv`.

### 4. Write your tests

Tests are the oracle. For scored layers, print metrics to stdout:

```python
def test_golden_set(golden_items, search_engine):
    recall = compute_recall(golden_items, search_engine)
    precision = compute_precision(golden_items, search_engine)

    print(f"RECALL_SCORE: {recall:.4f}")
    print(f"PRECISION_SCORE: {precision:.4f}")

    assert recall > 0.1, "Recall catastrophically low"
```

### 5. Let the agent run

The agent calls `sor_ratchet` in a loop, following the experiment-loop skill:

1. Read CLAUDE.md and the test files
2. Form a hypothesis
3. Edit only surface files
4. Call `sor_ratchet` with the layer and hypothesis
5. Parse the output (KEEP/DISCARD/STOP)
6. Repeat until a stopping condition hits

## MCP Tools

| Tool | Purpose |
|------|---------|
| `sor_init` | Initialize SOR config — returns template or saves filled config |
| `sor_add_layer` | Add a new layer to existing config |
| `sor_run_oracle` | Run oracle without git side effects (check current state) |
| `sor_ratchet` | One iteration: oracle → compare → commit/reset → check stops |
| `sor_status` | Progress dashboard: attempts, scores, proximity to stops |
| `sor_results` | Query experiment history from results.tsv |

## Stopping Conditions

The ratchet checks 7 stopping conditions after each iteration:

| Condition | Trigger |
|-----------|---------|
| `TARGET_MET` | Scored layer hit its target composite score |
| `ALL_PASS` | Pass/fail layer contracts passed |
| `PLATEAU` | Too many consecutive non-improvements |
| `DIMINISHING` | Recent improvements below threshold |
| `MAX_ATTEMPTS` | Hard ceiling on iterations |
| `CONSECUTIVE_FAILURES` | Too many test crashes in a row |
| `ORACLE_ERROR` | Oracle infrastructure broken |

## Notifications

Set environment variables for notifications when layers complete:

```bash
export SLACK_WEBHOOK_URL="https://hooks.slack.com/..."
export NOTIFY_EMAIL="you@example.com"
```

Always writes to `reports/notifications.log` as a fallback. Desktop
notifications via `osascript` (macOS) or `notify-send` (Linux).

## Requirements

- Python 3.10+
- Git (for commit/reset ratchet)
- Your test runner (pytest by default, configurable)

## Key Principles

- **The golden set is sacred.** Tests are frozen so the agent can't game the oracle.
- **One idea per iteration.** Atomic changes make the ratchet meaningful.
- **Layers freeze bottom-up.** Completed layers become read-only.
- **Single composite score.** One clear optimization target per scored layer.
- **The agent stops itself.** Plateau detection prevents infinite loops.
