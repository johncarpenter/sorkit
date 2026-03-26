# Sentiment Analyzer — sorkit Example

A rule-based sentiment classifier optimized autonomously using the
Surface-Oracle-Ratchet pattern.

## What This Demonstrates

An AI agent iteratively improves a naive sentiment classifier by:
1. Editing only `src/classifier.py` (the mutation surface)
2. Being scored against 50 labeled examples (the oracle)
3. Committing improvements, resetting failures (the ratchet)

The starter classifier gets ~40% accuracy with just 6 positive and 6 negative
words. The agent discovers negation handling, intensity modifiers, punctuation
patterns, and more — typically reaching 80-90% accuracy within 15-20 iterations.

## Layers

| # | Name | Type | Surface | Target |
|---|------|------|---------|--------|
| 1 | classifier | Scored | `src/classifier.py` | 0.85 composite |
| 2 | api | Pass/fail | `src/api.py` | All contracts pass |

## Metrics (Layer 1)

| Metric | Weight | What it measures |
|--------|--------|-----------------|
| ACCURACY | 0.5 | Overall accuracy on 50 examples |
| POS_RECALL | 0.2 | Recall on positive examples |
| NEG_RECALL | 0.2 | Recall on negative examples |
| NEU_RECALL | 0.1 | Recall on neutral examples |

## Quick Start

```bash
# From this directory:
cd examples/sentiment

# Initialize git (required for the ratchet)
git init && git add -A && git commit -m "initial"

# Generate CLAUDE.md and experiment-loop skill
pip install sorkit
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

# Check the starting accuracy
python -m pytest tests/test_classifier_accuracy.py -s
```

## Running with sorkit MCP Server

With sorkit installed as an MCP server, the agent can:

```
1. Call sor_run_oracle(layer="classifier", project_dir="examples/sentiment")
   → See starting accuracy (~40%)

2. Edit src/classifier.py with an improvement hypothesis

3. Call sor_ratchet(layer="classifier", hypothesis="add more positive words", ...)
   → KEEP score=0.5200 prev=0.4000  (improved!)

4. Repeat until STOP:TARGET_MET or STOP:PLATEAU

5. Move to layer 2: Call sor_ratchet(layer="api", hypothesis="implement analyze()", ...)
   → STOP:ALL_PASS  (contracts satisfied!)
```

## The Golden Set

`fixtures/golden_set.json` contains 50 labeled examples:
- 20 positive (including negation tricks: "not bad", "despite negative reviews")
- 15 negative (including subtle: "not what I'd call good")
- 10 neutral (including mixed: "some features good, others lacking")
- 5 tricky edge cases with negation and context

The scored test prints misclassifications so the agent can learn from its mistakes.

## What the Agent Typically Discovers

Iteration by iteration, agents typically find:

1. **More words** — expanding the positive/negative word lists
2. **Punctuation** — stripping `!`, `?`, `.` before matching
3. **Negation** — "not good" should flip sentiment
4. **Intensity** — "very", "extremely", "absolutely" as amplifiers
5. **Phrases** — multi-word patterns like "waste of money"
6. **Default bias** — tuning what to return when scores are tied
7. **Scoring refinements** — weighting certain matches higher
