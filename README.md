# X Automation — @mhucex

Automated X/Twitter scripts for account **@mhucex** running on AWS EC2 VPS.

## Scripts

| Script | Description |
|--------|-------------|
| `x_timeline_draft.py` | Fetches For You timeline, generates contextual quote tweets & replies via LLM |
| `x_viral_tweet_hunter.py` | Hunts viral tweets (50k+ views), generates replies/quotes |
| `x_auto_post_tweet.py` | Auto-posts original tweets with AI-generated image (research → draft → image → post) |
| `x_timeline_draft_wrapper.sh` | Cron wrapper for timeline script — formats output for Telegram delivery |
| `x_viral_hunter_wrapper.sh` | Cron wrapper for viral hunter |
| `box_helper.sh` | Shared helper for box-formatted terminal output |

## Architecture

```
Cron (hourly)
    ↓
wrapper.sh (timeout 90s)
    ↓
xvfb-run + Python script
    ↓
Playwright (Firefox headless) → X/Twitter
    ↓
LLM (9router OmbrO combo) → generate quote/reply text
    ↓
Image Gen (CF Workers AI → Pollinations fallback) → attach image
    ↓
Post tweet/reply/quote
    ↓
Box output → Telegram via Hermes cron delivery
```

## Cron Schedule

```
0  * * * *  Timeline Auto Quote/Reply  (top of hour)
30 * * * *  Viral Tweet Hunter         (half hour)
0  3 * * *  Cookie Health Check        (daily 03:00 WIB)
```

## Setup

### Requirements

```bash
# Python packages
pip install playwright requests

# Install Firefox for Playwright
python3 -m playwright install firefox
```

### Config (per script)

Each script reads config from top of file:

```python
LLM_API_KEY  = "<from 9router DB>"
LLM_MODEL    = "OmbrO"  # 9router combo
LLM_BASE_URL = "http://127.0.0.1:20128/v1"
COOKIE_FILE  = "/path/to/x_cookies.json"  # NOT committed
```

### Cookie File

Obtain X/Twitter cookies via browser extension (EditThisCookie / Cookie-Editor), save as JSON.
**Never commit cookie files to this repo.**

## LLM Integration

Uses [9router](https://github.com/reizto/9router) as local LLM proxy.

**OmbrO combo** (round-robin, 13 models):
- `openrouter/meta-llama/llama-3.3-70b-instruct` (~417ms)
- `general/gpt-oss-120b` (~458ms)
- `hugingface/meta-llama/Llama-3.3-70B-Instruct` (~487ms)
- `openrouter/openai/gpt-4o` (~705ms)
- `openrouter/google/gemini-2.5-flash` (~1037ms)
- `openrouter/openai/gpt-4o-mini` (~1081ms)
- `tokenrouter/openai/gpt-5.2` (~1125ms)
- `openrouter/deepseek/deepseek-chat` (~1449ms)
- `openrouter/anthropic/claude-opus-4-5` (~1581ms)
- `virtuals/openai-gpt-52` (~1632ms)
- `tokenrouter/anthropic/claude-sonnet-4.6` (~2045ms)
- `virtuals/anthropic-claude-sonnet-4-6` (~2266ms)
- `blues/gpt-4o` (~2460ms)

## Image Generation

**Provider chain (x_auto_post_tweet.py):**
1. 🥇 CF Workers AI — Flux-1-schnell (23 accounts rotating)
2. 🥈 Pollinations AI — free, no auth (`image.pollinations.ai`)

## Posting Behavior

- **LLM fail** → skip post (no fallback template)
- **Tone** → assertive, opinionated, substantive — no hype/filler
- **Language** → English only for public posts
- **Source link** → always included for news/research posts
- **View threshold** → 50k minimum for viral hunter

## Notes

- `xvfb-run` required (headless display for Firefox/Playwright)
- Wrapper `timeout 90s` — must complete before Hermes cron watchdog (120s)
- Random internal delay (3-15s) to avoid predictable patterns
