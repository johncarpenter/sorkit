#!/bin/bash
# notify.sh — Generic notification when a layer completes or stops
# Usage: ./scripts/notify.sh <layer_name> <score> <attempts> <stop_reason>
#
# Channels (via env vars):
#   SLACK_WEBHOOK_URL  — posts to Slack
#   NOTIFY_EMAIL       — sends via local mail command
#   NOTIFY_FILE        — appends to file (always enabled as fallback)

LAYER_NAME=$1
SCORE=$2
ATTEMPTS=$3
STOP_REASON=$4
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
NOTIFY_FILE="${NOTIFY_FILE:-reports/notifications.log}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PARSE="${SCRIPT_DIR}/sor-parse.py"
PROJECT_NAME=$(python3 "$PARSE" project_name 2>/dev/null || echo "SOR Project")

# ─── Build the message ────────────────────────────────────────────────

case $STOP_REASON in
    TARGET_MET|ALL_PASS)   STATUS="COMPLETE";        EMOJI="✅" ;;
    PLATEAU|DIMINISHING)   STATUS="CONVERGED";       EMOJI="📊" ;;
    MAX_ATTEMPTS)          STATUS="CEILING HIT";     EMOJI="⏱️"  ;;
    CONSECUTIVE_FAILURES|ORACLE_ERROR) STATUS="NEEDS ATTENTION"; EMOJI="🚨" ;;
    *)                     STATUS="STOPPED";         EMOJI="⏹️"  ;;
esac

# Count keeps from results.tsv (if it exists)
KEEPS=0
if [ -f results.tsv ]; then
    LAYER_IDX=$(python3 "$PARSE" layer_name_to_index "$LAYER_NAME" 2>/dev/null || echo "")
    if [ -n "$LAYER_IDX" ]; then
        KEEPS=$(grep -P "^\S+\t${LAYER_IDX}\t.*\tKEEP$" results.tsv 2>/dev/null | wc -l)
    fi
fi

MESSAGE="${EMOJI} ${PROJECT_NAME} — ${LAYER_NAME} ${STATUS}
Reason: ${STOP_REASON}
Score: ${SCORE}
Attempts: ${ATTEMPTS} (${KEEPS} kept)
Time: ${TIMESTAMP}"

# ─── File notification (always) ───────────────────────────────────────
mkdir -p "$(dirname "$NOTIFY_FILE")"
echo "---" >> "$NOTIFY_FILE"
echo "$MESSAGE" >> "$NOTIFY_FILE"
echo "" >> "$NOTIFY_FILE"

# ─── Slack notification ───────────────────────────────────────────────
if [ -n "${SLACK_WEBHOOK_URL:-}" ]; then
    JSON_MESSAGE=$(echo "$MESSAGE" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))")
    curl -sf -X POST "$SLACK_WEBHOOK_URL" \
        -H "Content-Type: application/json" \
        -d "{\"text\": ${JSON_MESSAGE}}" \
        2>/dev/null || echo "WARNING: Slack notification failed"
fi

# ─── Email notification ───────────────────────────────────────────────
if [ -n "${NOTIFY_EMAIL:-}" ] && command -v mail &>/dev/null; then
    echo "$MESSAGE" | mail -s "${EMOJI} ${PROJECT_NAME}: ${LAYER_NAME} ${STATUS}" "$NOTIFY_EMAIL" \
        2>/dev/null || echo "WARNING: Email notification failed"
fi

# ─── Desktop notification (macOS/Linux) ───────────────────────────────
if command -v osascript &>/dev/null; then
    osascript -e "display notification \"${LAYER_NAME}: ${STATUS} (${SCORE})\" with title \"${PROJECT_NAME}\"" 2>/dev/null || true
elif command -v notify-send &>/dev/null; then
    notify-send "${PROJECT_NAME}" "${LAYER_NAME}: ${STATUS} (${SCORE})" 2>/dev/null || true
fi

echo "Notification sent: ${STATUS}"
