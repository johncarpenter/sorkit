# My Project

## Development Method: Surface-Oracle-Ratchet

This project uses autonomous iterative development. Each layer has:
- A **mutation surface** (files the agent can edit)
- An **oracle** (automated tests that determine pass/fail)
- A **ratchet** (git commit on improvement, git reset on failure)

Run `./run_oracle.sh [layer]` to evaluate. See `.claude/skills/experiment-loop.md` for the protocol.

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
| 1 | search | `src/search/query_builder.py,src/search/ranker.py,src/search/embedder.py` | Scored (composite metric) |
| 2 | api | `src/api/main.py,src/api/schemas.py,src/api/auth.py` | Pass/fail |
| 3 | vba | `vba/ItemSearch.bas,vba/config.bas` | Pass/fail |

When working on Layer N, all layers < N are frozen.

## Stopping Thresholds

| Parameter | Value |
|-----------|-------|
| Layer 1 (search) max attempts | 30 |
| Layer 1 (search) target score | 0.9 |
| Layer 2 (api) max attempts | 15 |
| Layer 3 (vba) max attempts | 10 |
| Plateau limit | 5 consecutive non-improvements |
| Diminishing threshold | 0.005 (min delta over window) |
| Consecutive failure limit | 5 |

To adjust, edit the thresholds in `sor.yaml` and re-run `./scripts/sor-init.sh`.
