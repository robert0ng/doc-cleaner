#!/bin/bash
# Cron wrapper for fetch_gmail.py.
# Scheduled by launchd to run only on days 7–15 at 11:00.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$SCRIPT_DIR/output/fetch_gmail.log"

mkdir -p "$SCRIPT_DIR/output"

{
    echo "=== $(date '+%Y-%m-%d %H:%M:%S') ==="
    source "$SCRIPT_DIR/.venv/bin/activate"
    cd "$SCRIPT_DIR"
    OUTPUT=$(python fetch_gmail.py --config config.json 2>&1)
    EXIT_CODE=$?
    echo "$OUTPUT"
    echo "=== Done (exit $EXIT_CODE) ==="
    echo ""
} >> "$LOG" 2>&1

if [ "$EXIT_CODE" -ne 0 ]; then
    osascript -e "display notification \"fetch_gmail.py failed (exit $EXIT_CODE). Check output/fetch_gmail.log\" with title \"Doc-Cleaner Error\" sound name \"Basso\""
elif echo "$OUTPUT" | grep -q "Downloaded:"; then
    COUNT=$(echo "$OUTPUT" | grep -c "Downloaded:")
    osascript -e "display notification \"${COUNT} new statement(s) downloaded. Run doc-cleaner to update charts.\" with title \"Doc-Cleaner\" sound name \"Glass\""
fi
