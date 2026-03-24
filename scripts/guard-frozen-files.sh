#!/bin/bash
# guard-frozen-files.sh — Generic write guard using sor.yaml
# PreToolUse hook: blocks writes to frozen files
# Exit 0 = allow, Exit 2 = block
#
# Set CURRENT_LAYER env var to the 0-indexed layer being worked on.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PARSE="${SCRIPT_DIR}/sor-parse.py"

# Read the tool input from stdin (Claude Code hook protocol)
INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tool_input',{}).get('file_path',''))" 2>/dev/null)

if [ -z "$FILE_PATH" ]; then
    exit 0  # Can't determine file, allow
fi

CURRENT_LAYER="${CURRENT_LAYER:-0}"

# Get all frozen paths for this layer from sor.yaml
FROZEN_PATHS=$(python3 "$PARSE" frozen_for "$CURRENT_LAYER" 2>/dev/null)

if [ -z "$FROZEN_PATHS" ]; then
    exit 0  # No config or no frozen paths, allow
fi

while IFS= read -r pattern; do
    if [[ "$FILE_PATH" == *"$pattern"* ]]; then
        echo "BLOCKED: $FILE_PATH is frozen (matches pattern: ${pattern})" >&2
        exit 2
    fi
done <<< "$FROZEN_PATHS"

exit 0  # Allow the write
