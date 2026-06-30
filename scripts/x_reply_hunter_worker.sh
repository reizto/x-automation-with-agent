#!/bin/bash
# Reply Hunter WORKER — runs detached (no cron 120s limit).
# Dispatched by x_reply_hunter_wrapper.sh. Does throttle wait + actual post.
SCRIPT_DIR="${X_SCRIPT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
export TZ="Asia/Jakarta"

LOCK="/tmp/x_reply_hunter.lock"
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

# Cross-cron throttle: may sleep up to ~900s+ — fine, we're detached.
source "$SCRIPT_DIR/x_throttle.sh"
x_throttle_wait "ReplyHunter"

LOG_FILE="/tmp/x_reply_hunter_$(date +%Y%m%d_%H%M%S).log"
export X_RUN_DEADLINE=135
timeout --kill-after=10 150 xvfb-run -a ${PYTHON:-python3} "$SCRIPT_DIR/x_reply_hunter.py" >"$LOG_FILE" 2>&1
RESULT=$?

x_throttle_done

QUOTES=$(grep -oP 'SUMMARY: \K.*' "$LOG_FILE" | grep -oP '"quotes":\s*\K[0-9]+' | tail -1 || echo "0")
REPLIES=$(grep -oP 'SUMMARY: \K.*' "$LOG_FILE" | grep -oP '"replies":\s*\K[0-9]+' | tail -1 || echo "0")
QUOTES=${QUOTES:-0}
REPLIES=${REPLIES:-0}
TS=$(date '+%Y-%m-%d %H:%M:%S')

source "$SCRIPT_DIR/box_helper.sh"
source "$SCRIPT_DIR/x_tg_notify.sh"
if [ "$RESULT" -eq 0 ]; then STATUS="✅ Success"; else STATUS="❌ Failed (exit $RESULT)"; fi

BOX=$(box "🦠 REPLY HUNTER" \
    "🕐 Time    : $TS" \
    "📊 Status  : $STATUS" \
    "🔁 Quotes  : $QUOTES" \
    "↩️  Replies : $REPLIES")
if [ -s "$LOG_FILE" ]; then
    EXTRA=$(grep -E "🎯 Target|✅ Posted" "$LOG_FILE" | head -6)
    [ -n "$EXTRA" ] && BOX="${BOX}
${EXTRA}"
fi
echo "$BOX" >> /tmp/x_reply_hunter_bg.log
x_tg_notify "$BOX"
