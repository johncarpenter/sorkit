#!/bin/bash
# sor-init.sh — Generate CLAUDE.md and .claude/skills/ from sor.yaml
# Usage: ./scripts/sor-init.sh
#
# Creates:
#   CLAUDE.md                         — Agent instructions
#   .claude/skills/experiment-loop.md — Generic experiment protocol
#   results.tsv                       — Initialized if missing
#
# Run this once after editing sor.yaml, then freeze CLAUDE.md.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PARSE="${SCRIPT_DIR}/sor-parse.py"

PROJECT_NAME=$(python3 "$PARSE" project_name)
LAYER_COUNT=$(python3 "$PARSE" layer_count)

# ─── Generate CLAUDE.md ───────────────────────────────────────────────

cat > CLAUDE.md << 'HEADER'
# ${PROJECT_NAME}

## Development Method: Surface-Oracle-Ratchet

This project uses autonomous iterative development. Each layer has:
- A **mutation surface** (files the agent can edit)
- An **oracle** (automated tests that determine pass/fail)
- A **ratchet** (git commit on improvement, git reset on failure)

Run `./run_oracle.sh [layer]` to evaluate. See `.claude/skills/experiment-loop.md` for the protocol.

HEADER

# Rewrite the header with actual project name (heredoc doesn't expand)
cat > CLAUDE.md << EOF
# ${PROJECT_NAME}

## Development Method: Surface-Oracle-Ratchet

This project uses autonomous iterative development. Each layer has:
- A **mutation surface** (files the agent can edit)
- An **oracle** (automated tests that determine pass/fail)
- A **ratchet** (git commit on improvement, git reset on failure)

Run \`./run_oracle.sh [layer]\` to evaluate. See \`.claude/skills/experiment-loop.md\` for the protocol.

## Frozen Files (DO NOT MODIFY)

\`\`\`
$(python3 "$PARSE" always_frozen | sed 's/^/  /')
\`\`\`

## Mutation Surfaces (per layer)

| Layer | Name | Mutable Files | Oracle Type |
|-------|------|--------------|-------------|
EOF

for (( i=0; i<LAYER_COUNT; i++ )); do
    name=$(python3 "$PARSE" layer "$i" name)
    surface=$(python3 "$PARSE" layer "$i" surface | tr '\n' ', ' | sed 's/,$//')
    scored=$(python3 "$PARSE" layer "$i" scored)
    if [ "$scored" = "true" ]; then
        oracle_type="Scored (composite metric)"
    else
        oracle_type="Pass/fail"
    fi
    echo "| $((i+1)) | ${name} | \`${surface}\` | ${oracle_type} |" >> CLAUDE.md
done

cat >> CLAUDE.md << 'EOF'

When working on Layer N, all layers < N are frozen.

## Stopping Thresholds

EOF

echo "| Parameter | Value |" >> CLAUDE.md
echo "|-----------|-------|" >> CLAUDE.md

for (( i=0; i<LAYER_COUNT; i++ )); do
    name=$(python3 "$PARSE" layer "$i" name)
    max=$(python3 "$PARSE" layer "$i" threshold max_attempts)
    scored=$(python3 "$PARSE" layer "$i" scored)
    echo "| Layer $((i+1)) ($name) max attempts | ${max} |" >> CLAUDE.md
    if [ "$scored" = "true" ]; then
        target=$(python3 "$PARSE" layer "$i" threshold target_score)
        echo "| Layer $((i+1)) ($name) target score | ${target} |" >> CLAUDE.md
    fi
done

plateau=$(python3 "$PARSE" default plateau_limit)
diminishing=$(python3 "$PARSE" default diminishing_threshold)
fail_limit=$(python3 "$PARSE" default consecutive_failure_limit)

cat >> CLAUDE.md << EOF
| Plateau limit | ${plateau} consecutive non-improvements |
| Diminishing threshold | ${diminishing} (min delta over window) |
| Consecutive failure limit | ${fail_limit} |

To adjust, edit the thresholds in \`sor.yaml\` and re-run \`./scripts/sor-init.sh\`.
EOF

echo ""
echo "Generated: CLAUDE.md"

# ─── Generate experiment-loop skill ───────────────────────────────────

mkdir -p .claude/skills

cat > .claude/skills/experiment-loop.md << 'SKILL_EOF'
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
SKILL_EOF

echo "Generated: .claude/skills/experiment-loop.md"

# ─── Initialize results.tsv ───────────────────────────────────────────

if [ ! -f results.tsv ]; then
    printf "timestamp\tlayer\thypothesis\tscore\toutcome\n" > results.tsv
    echo "Generated: results.tsv"
fi

echo ""
echo "Done. Review CLAUDE.md, then add any project-specific context (tech stack, Docker, etc)."
echo "The generated files are a starting point — customize them for your project."
