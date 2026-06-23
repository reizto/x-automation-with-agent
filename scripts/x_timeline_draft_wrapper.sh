#!/bin/bash
# Timeline Auto Quote/Reply wrapper - auto-post with RANDOM delay (background)
# Cron calls this → exits immediately → actual work runs detached later
SCRIPT_DIR="/home/ubuntu/.hermes/scripts"

# Human gate: aktif 06-23 WIB, skip 25%
export TZ="Asia/Jakarta"

# No random delay in wrapper (cron watchdog 120s)
LOG_FILE="/tmp/x_timeline_draft_$(date +%Y%m%d_%H%M%S).log"
timeout 90 xvfb-run -a /home/ubuntu/.hermes/hermes-agent/venv/bin/python3 "$SCRIPT_DIR/x_timeline_draft.py" >"$LOG_FILE" 2>&1
RESULT=$?

STATE="/tmp/x_timeline_draft_state.json"
if [ -f "$STATE" ]; then
    QUOTES=$(grep -o '"quotes":\s*[[:digit:]]*' "$STATE" | grep -o '[[:digit:]]*' | tail -1)
    REPLIES=$(grep -o '"replies":\s*[[:digit:]]*' "$STATE" | grep -o '[[:digit:]]*' | tail -1)
fi
QUOTES=${QUOTES:-0}
REPLIES=${REPLIES:-0}
TS=$(date '+%Y-%m-%d %H:%M:%S')

source "$SCRIPT_DIR/box_helper.sh"

if [ "$RESULT" -eq 0 ]; then
    STATUS="✅ Posted"
else
    STATUS="❌ Failed (exit $RESULT)"
fi

box "🚀 TIMELINE AUTO-POST" \
    "🕐 Time    : $TS" \
    "📊 Status  : $STATUS" \
    "🔁 Quotes  : $QUOTES" \
    "↩️  Replies : $REPLIES" | tee -a "/tmp/x_timeline_draft_bg.log"

exit $RESULT
