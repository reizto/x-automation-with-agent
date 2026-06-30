# X Automation

Automated X/Twitter scripts for Playwright-based posting, replies, quotes, video reposts, cookie health checks, and views tracking.

## Scripts

| Script | Description |
|---|---|
| `x_timeline_draft.py` | Reads timeline candidates and posts contextual quote/reply content |
| `x_reply_hunter.py` | Finds reply targets and posts concise contextual replies |
| `x_video_repost.py` | Downloads selected X videos and reposts with generated captions |
| `x_auto_post_tweet.py` | Research → draft → optional image → original X post |
| `x_cookie_health_check.py` | Verifies X cookie/session health |
| `x_views_tracker.py` | Tracks weekly view/impression snapshots |
| `*_wrapper.sh` / `*_worker.sh` | Cron-safe wrappers and detached workers |
| `x_stealth_browser.py` | Shared browser/session automation engine |
| `x_tg_notify.sh` | Optional Telegram notification helper via env vars |
| `box_helper.sh` | Compact box-format output helper |

## Requirements

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install playwright requests yt-dlp
python3 -m playwright install firefox chromium
```

System tools commonly needed:

```bash
sudo apt-get install -y xvfb ffmpeg
```

## Configuration

Set runtime values through environment variables. Do **not** commit cookies, tokens, DB files, or local profile paths.

```bash
export X_COOKIE_FILE="/secure/path/to/x_cookies.json"
export X_COOKIE_PERSISTENT="/secure/path/to/persistent_x_cookies.json"   # optional
export X_WEB_BEARER="<x-web-public-bearer-if-using-graphql-api>"          # optional
export ROUTER_DB_PATH="$HOME/.9router/db/data.sqlite"                    # optional
export LLM_API_URL="http://127.0.0.1:20128/v1"
export LLM_MODEL="OmbrO"
export TELEGRAM_BOT_TOKEN="<telegram-bot-token>"                         # optional
export X_TG_CHAT="<telegram-chat-id>"                                     # optional
export X_TG_THREAD="<telegram-thread-id>"                                 # optional
export YT_DLP_BIN="$(command -v yt-dlp)"                                  # optional
```

## Cron Pattern

Use wrappers for scheduled jobs; workers handle longer posting flows and self-notification.

```cron
# examples only — adjust to your account limits and active hours
3,36 6-22 * * *  bash scripts/x_reply_hunter_wrapper.sh
2,32 * * * *     bash scripts/x_timeline_draft_wrapper.sh
0,30 6-22 * * *  bash scripts/x_video_repost_wrapper.sh
37 6-21/5 * * *  bash scripts/x_auto_post_wrapper.sh
```

## Safety

- Never commit `X_COOKIE_FILE`, cookie JSON, `.env`, API keys, bot tokens, local DBs, or browser profiles.
- Keep account-specific IDs and Telegram destinations in environment variables.
- Validate with `python3 -m py_compile scripts/*.py` before pushing.
- For live automation, test one script manually before enabling cron.
