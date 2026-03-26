# Sentiment Analyzer

## Development Method: Surface-Oracle-Ratchet

This project uses autonomous iterative development. Each layer has:
- A **mutation surface** (files the agent can edit)
- An **oracle** (automated tests that determine pass/fail)
- A **ratchet** (git commit on improvement, git reset on failure)

Use `sor_run_oracle` to evaluate. See `.claude/skills/experiment-loop.md` for the protocol.

## Frozen Files (DO NOT MODIFY)

```
  fixtures/
  tests/
  sor.yaml
  CLAUDE.md
  .claude/
  results.tsv
```

## Mutation Surfaces (per layer)

| Layer | Name | Mutable Files | Oracle Type |
|-------|------|--------------|-------------|
| 1 | classifier | `src/classifier.py` | Scored (composite metric) |
| 2 | api | `src/api.py` | Pass/fail |

When working on Layer N, all layers < N are frozen.

## Stopping Thresholds

| Parameter | Value |
|-----------|-------|
| Layer 1 (classifier) max attempts | 30 |
| Layer 1 (classifier) target score | 0.85 |
| Layer 2 (api) max attempts | 10 |
| Plateau limit | 5 consecutive non-improvements |
| Diminishing threshold | 0.005 (min delta over window) |
| Consecutive failure limit | 5 |

To adjust, edit the thresholds in `sor.yaml` and regenerate with `sor_init`.
