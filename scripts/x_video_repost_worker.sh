#!/bin/bash
# X Video Repost WORKER — runs detached (no cron 120s limit).
# Dispatched by x_video_repost_wrapper.sh. Does throttle wait + actual post.
SCRIPT_DIR="${X_SCRIPT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
export TZ="Asia/Jakarta"

LOCK="/tmp/x_video_repost.lock"
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

# Cross-cron throttle: may sleep up to ~900s+ — fine, we're detached.
source "$SCRIPT_DIR/x_throttle.sh"
x_throttle_wait "VideoRepost"

LOG_FILE="/tmp/x_video_repost_$(date +%Y%m%d_%H%M%S).log"
timeout --kill-after=10 120 xvfb-run -a ${PYTHON:-python3} "$SCRIPT_DIR/x_video_repost.py" --auto >"$LOG_FILE" 2>&1
RESULT=$?

x_throttle_done

source "$SCRIPT_DIR/box_helper.sh"
source "$SCRIPT_DIR/x_tg_notify.sh"
if [ "$RESULT" -eq 0 ]; then STATUS="✅ Success"; else STATUS="❌ Failed (exit $RESULT)"; fi
TS=$(date '+%Y-%m-%d %H:%M:%S')

CAPTION=$(grep -oP '✏️  Condensed: \K.*' "$LOG_FILE" | tail -1 || echo "")
SELECTED=$(grep -oP '🎯 Selected: \K.*' "$LOG_FILE" | tail -1 || echo "")
POST_URL=$(grep -oP '📤 Post.*: \K.*' "$LOG_FILE" | tail -1 || echo "")
VIEWS=$(grep -oP '🎯 Selected:.*\(views: \K[^)]+' "$LOG_FILE" | tail -1 || echo "")

BOX=$(box "🎬 VIDEO REPOST" \
    "🕐 Time    : $TS" \
    "📊 Status  : $STATUS" \
    "👁️  Views   : ${VIEWS:-N/A}" \
    "✏️  Caption : ${CAPTION:-(none)}" \
    "📤 Post    : ${POST_URL:-N/A}")
[ -n "$SELECTED" ] && BOX="${BOX}
   🔗 Source  : $SELECTED"
echo "$BOX" >> /tmp/x_video_repost_bg.log
x_tg_notify "$BOX"

# Cleanup old logs
find /tmp -name "x_video_repost_*.log" -mtime +1 -delete 2>/dev/null
