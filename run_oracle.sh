#!/bin/bash
# run_oracle.sh — Generic oracle runner for Surface-Oracle-Ratchet
# Reads layer definitions from sor.yaml via sor-parse.py
#
# Usage: ./run_oracle.sh <layer_number|layer_name|all>
# Exit 0 = pass, Exit 1 = fail
# Prints COMPOSITE (scored layers) or PASS/FAIL to stdout
#
# Requires: python3, pyyaml, pytest (or whatever test_runner is configured)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PARSE="${SCRIPT_DIR}/scripts/sor-parse.py"
LAYER_INPUT=${1:-all}

# ─── Resolve layer input to 0-indexed number ──────────────────────────
resolve_layer() {
    local input=$1
    if [[ "$input" =~ ^[0-9]+$ ]]; then
        echo "$input"
    else
        python3 "$PARSE" layer_name_to_index "$input"
    fi
}

# ─── Run tests for a single layer ─────────────────────────────────────
run_layer() {
    local idx=$1
    local name=$(python3 "$PARSE" layer "$idx" name)
    local test_runner=$(python3 "$PARSE" default test_runner)
    test_runner=${test_runner:-"python -m pytest"}
    local contracts=$(python3 "$PARSE" layer "$idx" contracts)
    local is_scored=$(python3 "$PARSE" layer "$idx" scored)

    echo "=== Layer $((idx+1)): ${name} Oracle ==="

    # Step 1: Run contract tests (must pass)
    if [ -n "$contracts" ]; then
        echo "--- Running: ${name} contracts ---"
        if ! ${test_runner} ${contracts} -x --tb=short -q 2>&1; then
            echo "CONTRACTS_FAILED"
            exit 1
        fi
        echo "PASS: ${name} contracts"
    fi

    # Step 2: If scored, run scored tests and extract metrics
    if [ "$is_scored" = "true" ]; then
        local scored_tests=$(python3 "$PARSE" layer "$idx" scored_tests)
        echo "--- Running: ${name} scoring ---"
        SCORED_OUTPUT=$(${test_runner} ${scored_tests} -x --tb=short -q 2>&1)
        echo "$SCORED_OUTPUT"

        # Extract each metric and compute weighted composite
        local composite="0"
        local metric_count=0
        while IFS=: read -r mname mextract mweight; do
            val=$(echo "$SCORED_OUTPUT" | grep "^${mextract}:" | tail -1 | awk '{print $2}')
            if [ -z "$val" ]; then
                echo "ERROR: Could not extract metric '${mname}' (pattern: ${mextract})"
                exit 1
            fi
            echo "METRIC_${mname}: ${val} (weight=${mweight})"
            composite=$(echo "scale=4; ${composite} + ${val} * ${mweight}" | bc -l)
            metric_count=$((metric_count + 1))
        done < <(python3 "$PARSE" layer "$idx" metrics)

        if [ "$metric_count" -eq 0 ]; then
            echo "ERROR: No metrics defined for scored layer"
            exit 1
        fi

        echo "COMPOSITE: ${composite}"
        exit 0
    fi

    # Step 3: Non-scored layer — contracts passing is enough
    echo "PASS"
    exit 0
}

# ─── Main dispatch ─────────────────────────────────────────────────────
case "$LAYER_INPUT" in
    all)
        echo "=== Full Oracle Run (all layers) ==="
        LAYER_COUNT=$(python3 "$PARSE" layer_count)
        FAILED=0
        for (( i=0; i<LAYER_COUNT; i++ )); do
            echo ""
            if ! "$0" "$i"; then
                FAILED=1
                echo "Layer $((i+1)): FAILED"
            else
                echo "Layer $((i+1)): PASSED"
            fi
        done
        if [ $FAILED -eq 1 ]; then
            echo "FAIL: One or more layers failed"
            exit 1
        else
            echo "PASS: All layers green"
            exit 0
        fi
        ;;
    *)
        IDX=$(resolve_layer "$LAYER_INPUT")
        run_layer "$IDX"
        ;;
esac
