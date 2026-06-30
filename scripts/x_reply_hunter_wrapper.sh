#!/bin/bash
# Reply Hunter wrapper. Hermes cron now calls this on a native 33m interval.
# Throttle wait + post = detached worker, so a long throttle sleep can't blow
# the cron budget → no false "failed".
SCRIPT_DIR="${X_SCRIPT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"

# Time gate: 06:00-23:00 WIB only
export TZ="Asia/Jakarta"
HOUR=$(date +%H)
[ "$HOUR" -lt 6 ]  && { echo "[$(date)] skip - outside hours ($HOUR)" >> /tmp/x_reply_hunter_bg.log; exit 0; }
[ "$HOUR" -ge 23 ] && { echo "[$(date)] skip - outside hours ($HOUR)" >> /tmp/x_reply_hunter_bg.log; exit 0; }

# Guard: don't stack runs.
LOCK="/tmp/x_reply_hunter.lock"
if [ -f "$LOCK" ]; then
    LPID=$(cat "$LOCK" 2>/dev/null)
    if [ -n "$LPID" ] && kill -0 "$LPID" 2>/dev/null; then
        echo "[$(date)] skip - worker $LPID still running" >> /tmp/x_reply_hunter_bg.log
        exit 0
    fi
fi

# Detach heavy work so cron returns instantly.
setsid bash "$SCRIPT_DIR/x_reply_hunter_worker.sh" >/dev/null 2>&1 < /dev/null &
echo "[$(date)] dispatched detached worker pid $!" >> /tmp/x_reply_hunter_bg.log
exit 0
