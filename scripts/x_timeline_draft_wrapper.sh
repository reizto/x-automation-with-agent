#!/bin/bash
# Timeline Auto Quote/Reply wrapper.
# Cron (no_agent, 120s hard limit) calls this. The throttle can sleep up to ~900s+,
# which blows the cron budget → SIGKILL → false "failed" notification.
# FIX: detach the real work into a background process and exit 0 immediately, so the
# cron returns well within budget. The actual post happens detached, logged to file.
SCRIPT_DIR="${X_SCRIPT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"

# Time gate: 06:00-23:00 WIB only
export TZ="Asia/Jakarta"
HOUR=$(date +%H)
[ "$HOUR" -lt 6 ]  && { echo "[$(date)] skip - outside hours ($HOUR)" >> /tmp/x_timeline_draft_bg.log; exit 0; }
[ "$HOUR" -ge 23 ] && { echo "[$(date)] skip - outside hours ($HOUR)" >> /tmp/x_timeline_draft_bg.log; exit 0; }

# Guard: don't stack runs. If a detached worker is still going, skip this tick.
LOCK="/tmp/x_timeline_draft.lock"
if [ -f "$LOCK" ]; then
    LPID=$(cat "$LOCK" 2>/dev/null)
    if [ -n "$LPID" ] && kill -0 "$LPID" 2>/dev/null; then
        echo "[$(date)] skip - worker $LPID still running" >> /tmp/x_timeline_draft_bg.log
        exit 0
    fi
fi

# Detach the real work so the cron call returns instantly (within its 120s budget).
setsid bash "$SCRIPT_DIR/x_timeline_draft_worker.sh" >/dev/null 2>&1 < /dev/null &
echo "[$(date)] dispatched detached worker pid $!" >> /tmp/x_timeline_draft_bg.log
exit 0
