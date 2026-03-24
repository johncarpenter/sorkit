# Skill: Autonomous Experiment Loop

## When to Use
When implementing any layer of this project autonomously.
This skill defines the experiment protocol — how to iterate, evaluate, and ratchet.

## Protocol

### Before You Start

1. Read `CLAUDE.md` to confirm which layer you're working on
2. Read the oracle tests for your layer (see the contracts/scored_tests in sor.yaml)
3. Read the current mutation surface files to understand the starting state
4. Check `results.tsv` for previous experiment history (if any)

### Experiment Loop

Each iteration follows this exact sequence. Do not deviate.

#### Step 1: Plan the Change

Before editing any code, write a one-line hypothesis:

```
HYPOTHESIS: [what you're changing] should [expected effect] because [reasoning]
```

#### Step 2: Implement

Edit ONLY files in the current layer's mutation surface (see CLAUDE.md).
Do NOT touch frozen files. Do NOT touch files from other layers.
Keep changes atomic — one idea per iteration.

#### Step 3: Run the Ratchet

```bash
./scripts/ratchet.sh <layer_number> "brief hypothesis description"
```

The ratchet will:
- Run the oracle
- Compare scores to previous best
- Git commit if improved, git reset if not
- Check all stopping conditions
- Notify if a stopping condition is hit

#### Step 4: Parse the Output

The ratchet prints exactly one of:
- `KEEP score={X} prev={Y}` — improvement, committed
- `DISCARD score={X} best={Y}` — no improvement, reverted
- `DISCARD FAIL` — tests failed, reverted
- `STOP:{reason} score={X} attempts={N} kept={K}` — stopping condition hit

#### Step 5: Decide Next Experiment

Review `results.tsv` to see what you've tried. Pick a different approach.
Do NOT repeat a failed hypothesis with minor variations more than once.

If you have 3+ consecutive failures, read the test output more carefully:
```bash
tail -n 50 run.log
```

### Stopping Conditions

Stop the loop and report to the human if you see any `STOP:` output:
- `TARGET_MET` — scored layer reached its target composite score
- `ALL_PASS` — pass/fail layer succeeded
- `PLATEAU` — too many consecutive non-improvements
- `DIMINISHING` — improvements too small to matter
- `MAX_ATTEMPTS` — hard ceiling reached
- `CONSECUTIVE_FAILURES` — too many crashes in a row
- `ORACLE_ERROR` — the oracle itself is broken (needs human fix)

### Results TSV Format

Tab-separated, appended by the ratchet:

```
timestamp	layer	hypothesis	score	outcome
2026-03-12T10:30:00	0	hybrid BM25+cosine 0.6/0.4	0.72	KEEP
2026-03-12T10:35:00	0	pure cosine similarity	0.65	DISCARD
```
