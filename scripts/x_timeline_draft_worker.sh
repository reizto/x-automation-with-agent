#!/bin/bash
# Timeline Auto Quote/Reply WORKER — runs detached (no cron 120s limit).
# Dispatched by x_timeline_draft_wrapper.sh. Does throttle wait + actual post.
SCRIPT_DIR="${X_SCRIPT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
export TZ="Asia/Jakarta"

LOCK="/tmp/x_timeline_draft.lock"
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

# Cross-cron throttle: may sleep up to ~900s+ — fine here, we're detached.
source "$SCRIPT_DIR/x_throttle.sh"
x_throttle_wait "TimelineQuote"

# Internal deadline keeps the python run bounded even though we're detached.
# Raised 105→135 / 120→160 (28 Jun): slow X navigation was tripping exit 124.
# Safe to exceed cron's 120s budget — worker is detached (setsid), not cron-bound.
LOG_FILE="/tmp/x_timeline_draft_$(date +%Y%m%d_%H%M%S).log"
export X_RUN_DEADLINE=135
timeout --kill-after=10 160 xvfb-run -a ${PYTHON:-python3} "$SCRIPT_DIR/x_timeline_draft.py" >"$LOG_FILE" 2>&1
RESULT=$?

# Mark throttle — we just posted (or tried)
x_throttle_done

# Parse the FRESH per-run SUMMARY line emitted by python (NOT the stale state
# file — that holds counts from the last SUCCESSFUL run and lies on a 0-post run).
SUMMARY=$(grep -oP 'SUMMARY: \K.*' "$LOG_FILE" | tail -1)
QUOTES=$(echo "$SUMMARY" | grep -oP '"quotes":\s*\K[0-9]+' | tail -1)
REPLIES=$(echo "$SUMMARY" | grep -oP '"replies":\s*\K[0-9]+' | tail -1)
QUOTES=${QUOTES:-0}
REPLIES=${REPLIES:-0}
TS=$(date '+%Y-%m-%d %H:%M:%S')

source "$SCRIPT_DIR/box_helper.sh"
source "$SCRIPT_DIR/x_tg_notify.sh"
# Truth: "Posted" ONLY if something actually landed this run. exit 2 = deadline
# hit with 0 posts; exit 124 = SIGKILL; both are failures, not success.
TOTAL=$(( QUOTES + REPLIES ))
if [ "$RESULT" -eq 0 ] && [ "$TOTAL" -gt 0 ]; then
    STATUS="✅ Posted"
elif [ "$TOTAL" -gt 0 ]; then
    STATUS="✅ Posted (exit $RESULT)"
else
    STATUS="⚠️ Nothing landed (exit $RESULT)"
fi

BOX=$(box "🚀 TIMELINE AUTO-POST" \
    "🕐 Time    : $TS" \
    "📊 Status  : $STATUS" \
    "🔁 Quotes  : $QUOTES" \
    "↩️  Replies : $REPLIES")
echo "$BOX" >> /tmp/x_timeline_draft_bg.log
x_tg_notify "$BOX"
