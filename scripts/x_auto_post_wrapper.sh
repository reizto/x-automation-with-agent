#!/bin/bash
# X Auto Post Tweet wrapper. Cron (240s budget) calls this.
# Time gate stays here (lightweight). Throttle wait + post = detached worker,
# so a long throttle sleep (~900s) can't blow the cron watchdog → no false
# "timed out / script failed" alerts. Worker self-delivers its box to Telegram.
SCRIPT_DIR="${X_SCRIPT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
export TZ="Asia/Jakarta"

# Time gate: 06:00-23:00 WIB only
HOUR=$(date +%H)
[ "$HOUR" -lt 6 ] && exit 0
[ "$HOUR" -ge 23 ] && exit 0

# Skip this tick if a prior worker is still running (throttle wait / posting).
LOCK="/tmp/x_auto_post.lock"
if [ -f "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
    exit 0
fi

# Dispatch detached worker and return immediately (well within cron budget).
setsid bash "$SCRIPT_DIR/x_auto_post_worker.sh" >/dev/null 2>&1 < /dev/null &
echo "[$(date)] dispatched detached worker pid $!" >> /tmp/x_auto_post_bg.log
exit 0
