# sorkit — Surface-Oracle-Ratchet Toolkit

An MCP server that enables AI agents to autonomously iterate on code while a
human-authored test suite acts as the objective function. The agent can only edit
designated files ("surfaces"), is evaluated by frozen tests ("oracles"), and
advances only when it improves ("ratchet").

```
pip install sorkit
```

## Table of Contents

- [The Pattern](#the-pattern)
- [How It Works](#how-it-works)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Configuration Reference](#configuration-reference)
- [MCP Tools Reference](#mcp-tools-reference)
- [Writing Tests for the Oracle](#writing-tests-for-the-oracle)
- [Stopping Conditions](#stopping-conditions)
- [Notifications](#notifications)
- [Running the Example](#running-the-example)
- [Programmatic Usage](#programmatic-usage)
- [Requirements](#requirements)

---

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

## How It Works

sorkit implements autonomous code optimization in three interlocking parts:

### Surface
The **mutation surface** is the set of files the agent is allowed to edit. Everything else is frozen. This constrains the agent's search space to only the code you want optimized.

### Oracle
The **oracle** is your test suite. It comes in two flavors:

- **Pass/fail**: Contract tests that must all pass (e.g., "the API returns valid JSON"). The agent succeeds when all tests pass.
- **Scored**: Tests that print numeric metrics to stdout (e.g., `ACCURACY: 0.8500`). sorkit extracts these, computes a weighted composite score, and uses it to decide whether the agent improved.

### Ratchet
The **ratchet** ensures monotonic progress:

- If the agent's change **improves** the score → `git commit` (lock in the gain)
- If the agent's change **doesn't improve** → `git reset` (revert and try again)
- If a **stopping condition** is hit → notify the human and stop

This makes the process safe: the agent can experiment freely because bad changes are automatically reverted.

### Layers
Projects are divided into **layers**, worked bottom-up:

1. Complete Layer 1 (e.g., core algorithm) → it freezes
2. Complete Layer 2 (e.g., API wrapper) → it freezes
3. And so on...

Each layer has its own surface, oracle, and stopping criteria. Completed layers become read-only, so the agent can never break previous work.

---

## Installation

```bash
pip install sorkit
```

This installs the `sorkit` command-line tool and the MCP server.

### Development Install

```bash
git clone https://github.com/2lines/sorkit.git
cd sorkit
pip install -e ".[dev]"
```

---

## Quick Start

### Step 1: Add sorkit to your MCP client

For **Claude Code**, add to your project's `.claude/settings.json`:

```json
{
  "mcpServers": {
    "sorkit": {
      "command": "sorkit"
    }
  }
}
```

For **Claude Desktop**, add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "sorkit": {
      "command": "sorkit"
    }
  }
}
```

### Step 2: Initialize your project

Ask your agent to call `sor_init` with your project directory. It returns a config template. Fill in your layers, surfaces, and tests, then call `sor_init` again with the completed config.

Or create `sor.yaml` manually (see [Configuration Reference](#configuration-reference)).

### Step 3: Write your tests

Tests are the oracle — the source of truth. The agent can never modify them.

For **pass/fail layers**, write standard tests:

```python
def test_api_returns_dict():
    result = my_api.call("hello")
    assert isinstance(result, dict)
```

For **scored layers**, print metrics to stdout:

```python
def test_golden_set_accuracy(golden_set):
    correct = sum(1 for item in golden_set if predict(item) == item["label"])
    accuracy = correct / len(golden_set)
    print(f"ACCURACY: {accuracy:.4f}")
    assert accuracy > 0.1  # floor assertion to catch catastrophic regression
```

The metric name in `print()` must match the `extract` field in your `sor.yaml`.

### Step 4: Initialize git

sorkit uses git for the ratchet mechanism. Your project must be a git repository:

```bash
git init
git add -A
git commit -m "initial state"
```

### Step 5: Generate artifacts

```python
from pathlib import Path
from sorkit.config import load_config
from sorkit.init import generate_claude_md, generate_experiment_loop_skill, initialize_results_tsv

config = load_config(Path('.'))
generate_claude_md(config, Path('.'))
generate_experiment_loop_skill(config, Path('.'))
initialize_results_tsv(Path('.'))
```

This creates:
- `CLAUDE.md` — tells the agent what files are frozen, what it can edit, and what thresholds apply
- `.claude/skills/experiment-loop.md` — the experiment protocol the agent follows
- `results.tsv` — experiment history tracker

### Step 6: Let the agent run

The agent follows the experiment loop:

1. Read `CLAUDE.md` and test files to understand the problem
2. Form a hypothesis ("add negation handling should improve accuracy")
3. Edit only surface files
4. Call `sor_ratchet` with the layer name and hypothesis
5. Parse the output: `KEEP`, `DISCARD`, or `STOP`
6. Repeat until a stopping condition is hit

---

## Configuration Reference

### sor.yaml

```yaml
# Project identity
project_name: "My Search Engine"

# Paths the agent must NEVER modify
always_frozen:
  - "fixtures/"
  - "tests/"
  - "sor.yaml"
  - "CLAUDE.md"
  - ".claude/"
  - "results.tsv"

# Global defaults (layers can override any of these)
defaults:
  test_runner: "python -m pytest"       # command to run tests
  max_attempts: 20                       # hard ceiling per layer
  consecutive_failure_limit: 5           # stop after N consecutive crashes
  plateau_limit: 5                       # stop after N consecutive non-improvements
  diminishing_threshold: 0.005           # min delta over window to continue
  diminishing_window: 5                  # how many recent keeps to check

# Layers — worked bottom-up, each freezes when complete
layers:
  # Scored layer example
  - name: "indexer"
    surface:
      - "src/indexer.py"
      - "src/tokenizer.py"
    oracle:
      contracts: "tests/test_indexer_contract.py"   # must pass before scoring
      scored: true
      scored_tests: "tests/test_indexer_quality.py"  # prints metrics to stdout
      metrics:
        - name: "recall"
          extract: "RECALL_SCORE"    # matches "RECALL_SCORE: 0.8500" in stdout
          weight: 0.6                # contribution to composite score
        - name: "precision"
          extract: "PRECISION_SCORE"
          weight: 0.4
    thresholds:
      target_score: 0.85            # stop when composite >= this
      max_attempts: 25              # override default for this layer

  # Pass/fail layer example
  - name: "api"
    surface:
      - "src/api/routes.py"
    oracle:
      contracts: "tests/test_api_*.py"
      scored: false
    thresholds:
      max_attempts: 10
```

### Configuration Fields

| Field | Required | Description |
|-------|----------|-------------|
| `project_name` | Yes | Human-readable project name |
| `always_frozen` | Yes | Paths the agent must never modify |
| `defaults.test_runner` | No | Test command (default: `python -m pytest`) |
| `defaults.max_attempts` | No | Max iterations per layer (default: 20) |
| `defaults.consecutive_failure_limit` | No | Stop after N crashes (default: 5) |
| `defaults.plateau_limit` | No | Stop after N non-improvements (default: 5) |
| `defaults.diminishing_threshold` | No | Min score delta (default: 0.005) |
| `defaults.diminishing_window` | No | Recent keeps to check (default: 5) |

### Layer Fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Unique layer name |
| `surface` | Yes | List of mutable file paths |
| `oracle.contracts` | Yes | Test file/glob for contract tests |
| `oracle.scored` | Yes | `true` for metric-based, `false` for pass/fail |
| `oracle.scored_tests` | If scored | Test file that prints metrics |
| `oracle.metrics` | If scored | List of `{name, extract, weight}` |
| `thresholds.target_score` | No | Stop when composite >= this |
| `thresholds.max_attempts` | No | Override default max attempts |

### Metric Weights

Metric weights must sum to 1.0. The composite score is:

```
composite = sum(metric_value * metric_weight for each metric)
```

---

## MCP Tools Reference

### sor_init

Initialize SOR in a project directory.

```
sor_init(project_dir="/path/to/project")
→ Returns a config template (JSON)

sor_init(project_dir="/path/to/project", config={...filled template...})
→ Saves sor.yaml and generates CLAUDE.md, experiment-loop skill, results.tsv
```

### sor_add_layer

Add a new layer to an existing config.

```
sor_add_layer(
    project_dir="/path/to/project",
    name="api",
    surface=["src/api.py"],
    contracts="tests/test_api_contract.py",
    scored=false
)
```

### sor_run_oracle

Run the oracle without git side effects. Useful for checking current state.

```
sor_run_oracle(layer="indexer", project_dir=".")
→ "COMPOSITE: 0.7200 (indexer)\n\nMetrics:\n  recall: 0.85\n  precision: 0.55"
```

### sor_ratchet

The core tool. One iteration: oracle → compare → commit/reset → check stops.

```
sor_ratchet(layer="indexer", hypothesis="add TF-IDF weighting", project_dir=".")
```

Returns one of:
- `KEEP score=0.7800 prev=0.7200` — improvement, committed
- `DISCARD score=0.7000 best=0.7800` — no improvement, reverted
- `DISCARD FAIL` — tests failed, reverted
- `STOP:TARGET_MET score=0.8600 attempts=12 kept=7` — done!

### sor_status

Progress dashboard for one or all layers.

```
sor_status(project_dir=".")           # all layers
sor_status(layer="indexer", project_dir=".")  # one layer
```

Shows: attempt count, best score, keeps, last outcome, proximity warnings.

### sor_results

Query experiment history from results.tsv.

```
sor_results(layer="indexer", last_n=10, project_dir=".")
```

### sor_audit

Comprehensive audit report: summary, score progression, convergence analysis, improvement rate, estimated iterations to target, hypothesis breakdown.

```
sor_audit(layer="indexer", project_dir=".")
```

### sor_score_history

Score progression with running best for each attempt.

```
sor_score_history(layer="indexer", project_dir=".")
```

### sor_hypotheses

Which hypotheses worked and which didn't, grouped with keep rates.

```
sor_hypotheses(layer="indexer", project_dir=".")
```

---

## Writing Tests for the Oracle

### Contract Tests (Required for All Layers)

Contract tests enforce basic correctness. They run first — if any fail, scored tests are skipped.

```python
"""Contract tests — FROZEN, do not modify."""

from src.my_module import my_function

class TestContract:
    def test_returns_correct_type(self):
        result = my_function("input")
        assert isinstance(result, dict)

    def test_handles_empty_input(self):
        result = my_function("")
        assert result is not None

    def test_handles_edge_cases(self):
        result = my_function("!@#$%")
        assert isinstance(result, dict)
```

### Scored Tests (For Scored Layers)

Scored tests print metrics to stdout. The oracle extracts these using the `extract` pattern from your config.

```python
"""Scored tests — FROZEN, do not modify."""

import json
from src.classifier import classify

def test_golden_set_accuracy(golden_set):
    correct = 0
    total = len(golden_set)

    # Per-class tracking
    class_correct = {"positive": 0, "negative": 0, "neutral": 0}
    class_total = {"positive": 0, "negative": 0, "neutral": 0}

    for item in golden_set:
        predicted = classify(item["text"])
        expected = item["label"]
        class_total[expected] += 1
        if predicted == expected:
            correct += 1
            class_correct[expected] += 1

    accuracy = correct / total
    pos_recall = class_correct["positive"] / class_total["positive"]
    neg_recall = class_correct["negative"] / class_total["negative"]
    neu_recall = class_correct["neutral"] / class_total["neutral"]

    # These lines are extracted by the oracle
    print(f"ACCURACY: {accuracy:.4f}")
    print(f"POS_RECALL: {pos_recall:.4f}")
    print(f"NEG_RECALL: {neg_recall:.4f}")
    print(f"NEU_RECALL: {neu_recall:.4f}")

    # Print misclassifications so the agent can learn
    for item in golden_set:
        predicted = classify(item["text"])
        if predicted != item["label"]:
            print(f"  [{item['label']}→{predicted}] \"{item['text'][:60]}\"")

    # Floor assertion — prevent catastrophic regression
    assert accuracy > 0.2, f"Accuracy too low: {accuracy:.1%}"
```

**Key rules for scored tests:**

1. Print metric lines as `METRIC_NAME: <float>` — the name must match `extract` in sor.yaml
2. Include a floor assertion to catch catastrophic regressions
3. Print misclassifications/errors so the agent can learn from mistakes
4. The test file is frozen — the agent never modifies it

### Golden Sets

For scored layers, create a golden set of labeled examples:

```json
[
  {"text": "I love this product!", "label": "positive"},
  {"text": "Terrible quality", "label": "negative"},
  {"text": "It arrived on Tuesday", "label": "neutral"}
]
```

Use a conftest.py fixture to load it:

```python
# tests/conftest.py — FROZEN
import json
from pathlib import Path
import pytest

@pytest.fixture
def golden_set():
    path = Path(__file__).parent.parent / "fixtures" / "golden_set.json"
    with open(path) as f:
        return json.load(f)
```

---

## Stopping Conditions

The ratchet checks 7 stopping conditions after each iteration:

| Condition | Trigger | Applies To |
|-----------|---------|------------|
| `TARGET_MET` | Composite score >= target_score | Scored layers |
| `ALL_PASS` | All contract tests pass | Pass/fail layers |
| `PLATEAU` | N consecutive non-improvements | Scored layers |
| `DIMINISHING` | Score delta below threshold over window | Scored layers |
| `MAX_ATTEMPTS` | Hit the max_attempts ceiling | All layers |
| `CONSECUTIVE_FAILURES` | N consecutive test crashes | All layers |
| `ORACLE_ERROR` | Oracle infrastructure is broken | All layers |

When a stopping condition fires, sorkit sends notifications and returns a `STOP:{reason}` message.

---

## Notifications

sorkit notifies you when a layer completes. Set environment variables to enable channels:

```bash
# Slack webhook
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."

# Email (requires sendmail configured)
export NOTIFY_EMAIL="you@example.com"
```

**Always-on channels:**
- File log: `reports/notifications.log`
- Desktop notification: `osascript` on macOS, `notify-send` on Linux

---

## Running the Example

The `examples/sentiment/` directory contains a complete working example — a rule-based sentiment classifier that an agent can optimize from ~40% to 80-90% accuracy.

### What the Example Demonstrates

- **Layer 1** (scored): A naive sentiment classifier with only 12 words. The agent iteratively improves it, typically discovering negation handling, intensity modifiers, punctuation stripping, phrase matching, and more.
- **Layer 2** (pass/fail): An API wrapper stub. After Layer 1 reaches its target, the agent implements the API to satisfy 7 contract tests.

### Setup

```bash
cd examples/sentiment

# Initialize git (required for the ratchet)
git init
git add -A
git commit -m "initial"

# Install sorkit
pip install sorkit

# Generate CLAUDE.md and experiment-loop skill
python -c "
from pathlib import Path
from sorkit.config import load_config
from sorkit.init import generate_claude_md, generate_experiment_loop_skill, initialize_results_tsv

config = load_config(Path('.'))
generate_claude_md(config, Path('.'))
generate_experiment_loop_skill(config, Path('.'))
initialize_results_tsv(Path('.'))
print('Ready!')
"
```

### Check the Baseline

```bash
# Run contract tests (should all pass)
python -m pytest tests/test_classifier_contract.py -v

# Run scored tests to see baseline accuracy
python -m pytest tests/test_classifier_accuracy.py -s
```

Expected output:

```
ACCURACY: 0.4000
POS_RECALL: 0.2381
NEG_RECALL: 0.2353
NEU_RECALL: 0.9167

Results: 20/50 correct (40.0%)
```

### Run with the MCP Server

With sorkit added to your MCP client configuration:

```
Agent: sor_run_oracle(layer="classifier", project_dir="examples/sentiment")
→ COMPOSITE: 0.4000

Agent: [edits src/classifier.py — adds more positive/negative words]
Agent: sor_ratchet(layer="classifier", hypothesis="expand word lists", ...)
→ KEEP score=0.5200 prev=0.4000

Agent: [edits src/classifier.py — adds punctuation stripping]
Agent: sor_ratchet(layer="classifier", hypothesis="strip punctuation", ...)
→ KEEP score=0.6000 prev=0.5200

... (15-20 iterations later) ...

Agent: sor_ratchet(layer="classifier", hypothesis="tune neutral default", ...)
→ STOP:TARGET_MET score=0.8600 attempts=18 kept=11

Agent: [now implements src/api.py]
Agent: sor_ratchet(layer="api", hypothesis="implement analyze()", ...)
→ STOP:ALL_PASS score=PASS attempts=1 kept=1
```

### What the Agent Typically Discovers

Through iterative optimization, agents typically find these improvements:

1. **More words** — expanding positive/negative word lists
2. **Punctuation** — stripping `!`, `?`, `.` before matching
3. **Negation** — "not good" should flip sentiment
4. **Intensity** — "very", "extremely" as amplifiers
5. **Phrases** — multi-word patterns like "waste of money"
6. **Default bias** — tuning what to return when scores are tied
7. **Scoring refinements** — weighting certain matches higher

### The Golden Set

`fixtures/golden_set.json` contains 50 labeled examples:
- 20 positive (including tricks: "not bad", "despite negative reviews")
- 15 negative (including subtle: "not what I'd call good")
- 10 neutral (including mixed: "some features good, others lacking")
- 5 edge cases with negation and context

### Monitoring Progress

```
Agent: sor_status(project_dir="examples/sentiment")
→ Layer 1: classifier (scored)
    Attempts: 12/30
    Keeps: 7
    Best score: 0.7800 (target: 0.85)
    ...

Agent: sor_audit(layer="classifier", project_dir="examples/sentiment")
→ Full audit report with convergence analysis

Agent: sor_hypotheses(layer="classifier", project_dir="examples/sentiment")
→ Which approaches worked and which didn't
```

---

## Programmatic Usage

You can use sorkit as a Python library without the MCP server:

```python
import asyncio
from pathlib import Path
from sorkit.config import load_config
from sorkit.oracle import run_oracle
from sorkit.ratchet import ratchet_once

async def main():
    project = Path(".")
    config = load_config(project)

    # Check current score
    result = await run_oracle(config, layer_idx=0, project_dir=project)
    print(f"Composite: {result.composite}")
    print(f"Metrics: {result.metrics}")

    # Run one ratchet iteration
    ratchet_result = await ratchet_once(
        config, layer_idx=0,
        hypothesis="add TF-IDF weighting",
        project_dir=project,
    )
    print(ratchet_result.message)

asyncio.run(main())
```

### Key Classes

```python
from sorkit.config import load_config, SorConfig, validate_config
from sorkit.oracle import run_oracle, OracleResult
from sorkit.ratchet import ratchet_once, RatchetResult, RatchetOutcome, StopReason
from sorkit.results import ResultsStore
from sorkit.frozen import get_frozen_paths, is_path_frozen
from sorkit.audit import get_score_history, analyze_hypotheses, generate_audit_report
from sorkit.init import generate_config_template, validate_and_save_config
from sorkit.notify import send_notifications
```

---

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

## License

MIT
