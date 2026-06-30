#!/bin/bash
# x_tg_notify.sh — shared Telegram sender for detached X workers.
# Usage:  x_tg_notify "<text>"
# Reads TELEGRAM_BOT_TOKEN from environment. Sends to the configured X-jobs chat+thread,
# wrapped in a code block so it renders compact (user preference).
# Detached workers no longer produce cron stdout, so they self-deliver here.

X_TG_CHAT="${X_TG_CHAT:-}"
X_TG_THREAD="${X_TG_THREAD:-}"

x_tg_notify() {
    local TEXT="$1"
    [ -z "$TEXT" ] && return 0
    local TOKEN
    TOKEN="${TELEGRAM_BOT_TOKEN:-}"
    [ -z "$TOKEN" ] && { echo "[x_tg_notify] no token" >> /tmp/x_tg_notify.log; return 1; }
    [ -z "$X_TG_CHAT" ] && { echo "[x_tg_notify] no X_TG_CHAT" >> /tmp/x_tg_notify.log; return 1; }
    # wrap in code block for compact monospace rendering
    local MSG
    MSG=$(printf '```\n%s\n```' "$TEXT")
    curl -s -m 15 -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
        --data-urlencode "chat_id=${X_TG_CHAT}" \
        --data-urlencode "message_thread_id=${X_TG_THREAD}" \
        --data-urlencode "parse_mode=Markdown" \
        --data-urlencode "text=${MSG}" \
        >> /tmp/x_tg_notify.log 2>&1
    echo "" >> /tmp/x_tg_notify.log
}
