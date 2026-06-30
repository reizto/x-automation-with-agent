#!/bin/bash
# Viral Tweet Hunter wrapper - auto-post with RANDOM delay (background)
# Cron calls this → exits immediately → actual work runs detached later
SCRIPT_DIR="${X_SCRIPT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"

# --- Human gate: aktif 06-23 WIB, skip 15% ---
export TZ="Asia/Jakarta"

# No random delay in wrapper (cron watchdog 120s)
LOG_FILE="/tmp/x_viral_hunter_$(date +%Y%m%d_%H%M%S).log"
timeout 70 xvfb-run -a ${PYTHON:-python3} "$SCRIPT_DIR/x_viral_tweet_hunter.py" \
    --no-header-box >"$LOG_FILE" 2>&1
RESULT=$?

STATE="/tmp/x_viral_hunter_state.json"
if [ -f "$STATE" ]; then
    QUOTES=$(grep -o '"quotes":\s*[[:digit:]]*' "$STATE" | grep -o '[[:digit:]]*' | tail -1)
    REPLIES=$(grep -o '"replies":\s*[[:digit:]]*' "$STATE" | grep -o '[[:digit:]]*' | tail -1)
fi
QUOTES=${QUOTES:-0}
REPLIES=${REPLIES:-0}
TS=$(date '+%Y-%m-%d %H:%M:%S')

source "$SCRIPT_DIR/box_helper.sh"

if [ "$RESULT" -eq 0 ]; then
    STATUS="✅ Success"
else
    STATUS="❌ Failed (exit $RESULT)"
fi

{
    box "🦠 VIRAL HUNTER" \
        "🕐 Time    : $TS" \
        "📊 Status  : $STATUS" \
        "🔁 Quotes  : $QUOTES" \
        "↩️  Replies : $REPLIES"
    
    if [ -s "$LOG_FILE" ]; then
        grep -E "Target :|Posted :" "$LOG_FILE" | head -6
    fi
} | tee -a "/tmp/x_viral_hunter_bg.log"

exit $RESULT
