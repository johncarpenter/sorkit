#!/bin/bash
# ratchet.sh — Generic ratchet: run oracle, evaluate, commit/reset, check stops
# Reads all thresholds and layer config from sor.yaml
#
# Usage: ./scripts/ratchet.sh <layer_number|layer_name> "<hypothesis>"
#
# Outputs to stdout (agent reads this):
#   KEEP score={X} prev={Y}
#   DISCARD score={X} best={Y}
#   DISCARD FAIL
#   STOP:{reason} score={X} attempts={N} kept={K}
#
# All oracle output goes to run.log (not stdout)

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
PARSE="${SCRIPT_DIR}/sor-parse.py"

LAYER_INPUT=$1
HYPOTHESIS="${2:-no hypothesis}"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
RESULTS_FILE="results.tsv"
RUN_LOG="run.log"
REPORTS_DIR="reports"

# ─── Resolve layer ────────────────────────────────────────────────────
if [[ "$LAYER_INPUT" =~ ^[0-9]+$ ]]; then
    LAYER_IDX=$LAYER_INPUT
else
    LAYER_IDX=$(python3 "$PARSE" layer_name_to_index "$LAYER_INPUT")
fi
LAYER_NAME=$(python3 "$PARSE" layer "$LAYER_IDX" name)
IS_SCORED=$(python3 "$PARSE" layer "$LAYER_IDX" scored)

# ─── Load thresholds (layer overrides > defaults) ─────────────────────
get_threshold() {
    local key=$1
    local val=$(python3 "$PARSE" layer "$LAYER_IDX" threshold "$key")
    if [ -z "$val" ]; then
        val=$(python3 "$PARSE" default "$key")
    fi
    echo "$val"
}

TARGET_SCORE=$(get_threshold target_score)
TARGET_SCORE=${TARGET_SCORE:-0.90}
PLATEAU_LIMIT=$(get_threshold plateau_limit)
PLATEAU_LIMIT=${PLATEAU_LIMIT:-5}
DIMINISHING_THRESHOLD=$(get_threshold diminishing_threshold)
DIMINISHING_THRESHOLD=${DIMINISHING_THRESHOLD:-0.005}
DIMINISHING_WINDOW=$(get_threshold diminishing_window)
DIMINISHING_WINDOW=${DIMINISHING_WINDOW:-5}
MAX_ATTEMPTS=$(get_threshold max_attempts)
MAX_ATTEMPTS=${MAX_ATTEMPTS:-20}
CONSECUTIVE_FAILURE_LIMIT=$(get_threshold consecutive_failure_limit)
CONSECUTIVE_FAILURE_LIMIT=${CONSECUTIVE_FAILURE_LIMIT:-5}

# Use layer index as the key in results.tsv for consistency
LAYER_KEY="$LAYER_IDX"

# ─── Initialize results.tsv if needed ─────────────────────────────────
if [ ! -f "$RESULTS_FILE" ]; then
    printf "timestamp\tlayer\thypothesis\tscore\toutcome\n" > "$RESULTS_FILE"
fi

mkdir -p "$REPORTS_DIR"

# ─── Helpers: query results.tsv ───────────────────────────────────────
count_layer_attempts() {
    grep -cP "^\S+\t${LAYER_KEY}\t" "$RESULTS_FILE" 2>/dev/null || echo 0
}

get_best_score() {
    grep -P "^\S+\t${LAYER_KEY}\t.*\tKEEP$" "$RESULTS_FILE" | \
        awk -F'\t' '{print $4}' | sort -rn | head -1
}

get_recent_keeps() {
    local n=$1
    grep -P "^\S+\t${LAYER_KEY}\t.*\tKEEP$" "$RESULTS_FILE" | \
        tail -n "$n" | awk -F'\t' '{print $4}'
}

get_consecutive_non_improvements() {
    local count=0
    grep -P "^\S+\t${LAYER_KEY}\t" "$RESULTS_FILE" | tac | while IFS=$'\t' read -r ts ly hyp sc out; do
        if [ "$out" = "KEEP" ]; then
            break
        fi
        count=$((count + 1))
        echo "$count"
    done | tail -1
}

get_consecutive_failures() {
    local count=0
    grep -P "^\S+\t${LAYER_KEY}\t" "$RESULTS_FILE" | tac | while IFS=$'\t' read -r ts ly hyp sc out; do
        if [ "$sc" = "FAIL" ] || [ "$sc" = "ERROR" ]; then
            count=$((count + 1))
            echo "$count"
        else
            break
        fi
    done | tail -1
}

record() {
    local score=$1
    local outcome=$2
    printf "%s\t%s\t%s\t%s\t%s\n" "$TIMESTAMP" "$LAYER_KEY" "$HYPOTHESIS" "$score" "$outcome" >> "$RESULTS_FILE"
}

stop_and_notify() {
    local reason=$1
    local score=$2
    local attempts=$(count_layer_attempts)
    local keeps=$(grep -P "^\S+\t${LAYER_KEY}\t.*\tKEEP$" "$RESULTS_FILE" | wc -l)

    record "$score" "STOP"
    printf "STOP:%s score=%s attempts=%s kept=%s\n" "$reason" "$score" "$attempts" "$keeps"

    # Fire notification
    if [ -x "${SCRIPT_DIR}/notify.sh" ]; then
        "${SCRIPT_DIR}/notify.sh" "$LAYER_NAME" "$score" "$attempts" "$reason" 2>/dev/null || true
    fi

    exit 0
}

# ─── Run the oracle ───────────────────────────────────────────────────
echo "Running oracle for ${LAYER_NAME} (layer ${LAYER_IDX})..."
if ! "${ROOT_DIR}/run_oracle.sh" "$LAYER_IDX" > "$RUN_LOG" 2>&1; then
    # Oracle failed — check if it's an oracle error vs test failure
    if grep -q "^ERROR\|^ORACLE_ERROR\|Traceback" "$RUN_LOG"; then
        if ! grep -q "FAIL\|AssertionError\|assert " "$RUN_LOG"; then
            record "ERROR" "DISCARD"
            CONSEC=$(get_consecutive_failures)
            CONSEC=${CONSEC:-0}
            if [ "$CONSEC" -ge "$CONSECUTIVE_FAILURE_LIMIT" ]; then
                stop_and_notify "ORACLE_ERROR" "ERROR"
            fi
            echo "DISCARD ERROR — oracle script crashed (not a test failure)"
            exit 1
        fi
    fi

    # Normal test failure
    git checkout -- . 2>/dev/null
    record "FAIL" "DISCARD"
    echo "DISCARD FAIL"

    CONSEC=$(get_consecutive_failures)
    CONSEC=${CONSEC:-0}
    if [ "$CONSEC" -ge "$CONSECUTIVE_FAILURE_LIMIT" ]; then
        stop_and_notify "CONSECUTIVE_FAILURES" "FAIL"
    fi

    ATTEMPTS=$(count_layer_attempts)
    if [ "$ATTEMPTS" -ge "$MAX_ATTEMPTS" ]; then
        BEST=$(get_best_score)
        stop_and_notify "MAX_ATTEMPTS" "${BEST:-FAIL}"
    fi

    exit 1
fi

# ─── Oracle passed — extract score ────────────────────────────────────

COMPOSITE=$(grep "^COMPOSITE:" "$RUN_LOG" | tail -1 | awk '{print $2}')

# ─── Pass/fail layers ─────────────────────────────────────────────────
if [ "$IS_SCORED" != "true" ] || [ -z "$COMPOSITE" ]; then
    git add -A
    git commit -m "${LAYER_NAME}: ${HYPOTHESIS}" --quiet
    record "PASS" "KEEP"
    echo "KEEP score=PASS"
    stop_and_notify "ALL_PASS" "PASS"
fi

# ─── Scored layers ────────────────────────────────────────────────────
PREV_BEST=$(get_best_score)
PREV_BEST=${PREV_BEST:-0}

IMPROVED=$(echo "$COMPOSITE > $PREV_BEST" | bc -l 2>/dev/null)

if [ "$IMPROVED" = "1" ]; then
    git add -A
    git commit -m "${LAYER_NAME}: ${HYPOTHESIS} | score=${COMPOSITE} (was ${PREV_BEST})" --quiet
    record "$COMPOSITE" "KEEP"
    echo "KEEP score=${COMPOSITE} prev=${PREV_BEST}"

    # Check: target met?
    TARGET_MET=$(echo "$COMPOSITE >= $TARGET_SCORE" | bc -l 2>/dev/null)
    if [ "$TARGET_MET" = "1" ]; then
        stop_and_notify "TARGET_MET" "$COMPOSITE"
    fi

    # Check: diminishing returns?
    RECENT_KEEPS=$(get_recent_keeps "$DIMINISHING_WINDOW")
    KEEP_COUNT=$(echo "$RECENT_KEEPS" | wc -l)

    if [ "$KEEP_COUNT" -ge "$DIMINISHING_WINDOW" ]; then
        SCORES_SORTED=$(echo "$RECENT_KEEPS" | sort -n)
        LOWEST=$(echo "$SCORES_SORTED" | head -1)
        HIGHEST=$(echo "$SCORES_SORTED" | tail -1)
        TOTAL_DELTA=$(echo "$HIGHEST - $LOWEST" | bc -l 2>/dev/null)

        IS_DIMINISHING=$(echo "$TOTAL_DELTA < $DIMINISHING_THRESHOLD" | bc -l 2>/dev/null)
        if [ "$IS_DIMINISHING" = "1" ]; then
            stop_and_notify "DIMINISHING" "$COMPOSITE"
        fi
    fi
else
    # No improvement — reset
    git checkout -- . 2>/dev/null
    record "$COMPOSITE" "DISCARD"
    echo "DISCARD score=${COMPOSITE} best=${PREV_BEST}"

    # Check: plateau?
    CONSEC_NO_IMPROVE=$(get_consecutive_non_improvements)
    CONSEC_NO_IMPROVE=${CONSEC_NO_IMPROVE:-0}
    if [ "$CONSEC_NO_IMPROVE" -ge "$PLATEAU_LIMIT" ]; then
        stop_and_notify "PLATEAU" "$PREV_BEST"
    fi
fi

# Check: max attempts?
ATTEMPTS=$(count_layer_attempts)
if [ "$ATTEMPTS" -ge "$MAX_ATTEMPTS" ]; then
    BEST=$(get_best_score)
    stop_and_notify "MAX_ATTEMPTS" "${BEST:-$COMPOSITE}"
fi
