#!/usr/bin/env python3
"""
X Video Repost — Download video from any tweet, repost to @mhucex with caption.
Pipeline: yt-dlp download → ffmpeg compress (if needed) → Playwright upload+post
"""
import os, sys, time, random, json, re, subprocess
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from box_helper import box

CRYPTO_PATTERNS = [
    r'\b(bitcoin|crypto|btc|eth|binance|trading|airdrops|defi|nft|web3)\b',
    r'\b(ripple|solana|cardano|polkadot|doge|shiba|pepe|meme coin)\b',
]
CRYPTO_REGEX = re.compile('|'.join(CRYPTO_PATTERNS), re.IGNORECASE)

def is_crypto(text):
    return bool(CRYPTO_REGEX.search(text))

MEDIA_DIR = "/tmp/x_video_repost"
Path(MEDIA_DIR).mkdir(exist_ok=True)

MAX_VIDEO_SIZE_MB = 80  # X limit ~512MB but keep small for speed


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def download_video(tweet_url, cookies_file=None):
    """Download video from tweet using yt-dlp"""
    yt_dlp = os.environ.get("YT_DLP_BIN") or shutil.which("yt-dlp") or "yt-dlp"
    out_template = f"{MEDIA_DIR}/vid_%(id)s.%(ext)s"

    cmd = [
        yt_dlp,
        "--no-playlist",
        "-f", f"best[filesize<{MAX_VIDEO_SIZE_MB}M]/best[height<=720]",
        "--merge-output-format", "mp4",
        "-o", out_template,
        tweet_url,
        "--no-warnings",
    ]

    # Add cookies if available (for age-restricted/private)
    if cookies_file and os.path.exists(cookies_file):
        cmd.extend(["--cookies", cookies_file])

    log(f"⬇️  Downloading: {tweet_url}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            log(f"⚠️  yt-dlp stderr: {result.stderr[:200]}")
            return None
    except subprocess.TimeoutExpired:
        log("❌ Download timeout (120s)")
        return None

    # Find the downloaded file
    for f in sorted(Path(MEDIA_DIR).glob("vid_*.mp4"), key=lambda x: x.stat().st_mtime, reverse=True):
        if time.time() - f.stat().st_mtime < 180:  # Created in last 3 min
            size_mb = f.stat().st_size / 1024 / 1024
            if 0.01 < size_mb < MAX_VIDEO_SIZE_MB:
                log(f"✅ Downloaded: {f.name} ({size_mb:.1f}MB)")
                return str(f)
            else:
                f.unlink()
                log(f"❌ File too large/small: {size_mb:.1f}MB")

    log("❌ No video file found after download")
    return None


def compress_video(input_path, max_mb=50):
    """Compress video with ffmpeg if too large"""
    size_mb = Path(input_path).stat().st_size / 1024 / 1024
    if size_mb <= max_mb:
        return input_path

    log(f"📦 Compressing {size_mb:.1f}MB → target {max_mb}MB...")
    out_path = input_path.replace(".mp4", "_compressed.mp4")

    # Calculate target bitrate based on duration
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", input_path],
        capture_output=True, text=True
    )
    try:
        duration = float(probe.stdout.strip())
        target_bitrate = int((max_mb * 8 * 1024) / duration * 0.9)  # 90% of target
        target_bitrate = max(target_bitrate, 200000)  # minimum 200k
    except:
        target_bitrate = 1000000

    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-c:v", "libx264", "-preset", "fast", "-b:v", str(target_bitrate),
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        out_path, "-loglevel", "error"
    ]

    try:
        subprocess.run(cmd, timeout=180, check=True)
        if os.path.exists(out_path):
            new_size = Path(out_path).stat().st_size / 1024 / 1024
            log(f"✅ Compressed: {new_size:.1f}MB")
            os.unlink(input_path)
            return out_path
    except Exception as e:
        log(f"⚠️  Compression failed: {e}")

    return input_path


def get_original_text(tweet_url):
    """Scrape original tweet text for caption rewriting using yt-dlp metadata"""
    # Strip trailing path suffixes like /analytics, /photo/1 that break yt-dlp
    tweet_url = re.sub(r'/(analytics|photo|video)(/\d+)?/?$', '', tweet_url)
    # Use yt-dlp to get tweet text without opening a browser
    try:
        result = subprocess.run(
            [os.environ.get("YT_DLP_BIN") or shutil.which("yt-dlp") or "yt-dlp", "--no-playlist", "--no-download", "-j", tweet_url],
            capture_output=True, text=True, timeout=30, encoding="utf-8"
        )
        if result.returncode == 0 and result.stdout.strip():
            import json as _json
            # yt-dlp -j may emit one JSON object per line; take the first valid object
            first_line = result.stdout.strip().splitlines()[0]
            info = _json.loads(first_line)
            desc = info.get("description", "")
            if desc:
                return desc.strip()[:500]
    except Exception as e:
        log(f"⚠️  yt-dlp metadata failed: {e}")
    return ""


def condense_caption(original_text, source_url):
    """Condense original tweet text into a denser, more substantive caption via LLM"""
    # Strip any t.co links from original text
    original_text = re.sub(r'https?://t\.co/\S+', '', original_text).strip()
    if not original_text:
        return ""
    try:
        import requests, sqlite3
        conn = sqlite3.connect(os.environ.get('ROUTER_DB_PATH', os.path.expanduser('~/.9router/db/data.sqlite')))
        cursor = conn.cursor()
        cursor.execute("SELECT key FROM apiKeys WHERE isActive=1 LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        if not row:
            return original_text[:100]
        api_key = row[0]

        # --- CJK language rotation (East Asia growth strategy) ---
        # Bias caption ke bahasa Asia Timur — audiens JP/KR/CN/RU lebih
        # apresiatif terhadap impresi/effort. Rotasi terbobot: JP paling sering.
        LANG_POOL = [
            ("Japanese", "日本語", 0.40),
            ("Korean",   "한국어", 0.25),
            ("Chinese (Simplified)", "简体中文", 0.20),
            ("English",  "English", 0.15),
        ]
        names  = [l[0] for l in LANG_POOL]
        labels = {l[0]: l[1] for l in LANG_POOL}
        weights = [l[2] for l in LANG_POOL]
        target_lang = random.choices(names, weights=weights, k=1)[0]
        target_label = labels[target_lang]
        log(f"🌏 Caption target language: {target_lang} ({target_label})")

        prompt = f"""Rewrite this tweet into ONE short human/emotional caption WRITTEN IN {target_lang}.
Style target:
- simple, understated, slightly emotional or ambiguous
- sounds like a real person reacting to a moment/event
- let the video carry the meaning
- avoid analysis, marketing, hype, jokes, hashtags, quotes, emoji
- max 75 characters

Good English examples:
The cherry blossoms are gone. I couldn't host the event as planned.
I thought it would last longer than this.
Some moments end before anyone is ready.

Original: {original_text}

Output ONLY one caption in {target_lang}."""

        r = requests.post(
            "http://52.76.29.219:20128/v1/chat/completions",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            json={
                "model": "OmbrO",
                "messages": [
                    {"role": "system", "content": f"You write short viral video captions in {target_lang} ({target_label}). Style: human, understated, emotional or ambiguous, one sentence, max 75 chars. Let the video carry the meaning. No analysis, no hype, no hashtags, no quotes, no emoji, no explanation. Output ONLY the caption in {target_lang}."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.8,
                "max_tokens": 80,
            },
            timeout=15,
        )
        # OmbrO sends UTF-8 but requests mis-guesses latin-1 → mojibake on
        # non-Latin text (e.g. Japanese 久保建英). Force UTF-8 before .text.
        r.encoding = "utf-8"
        raw = r.text.strip()
        try:
            # OmbrO appends a stray "data: [DONE]" after the JSON object, so a
            # plain json.loads throws "Extra data". raw_decode reads the first
            # valid object and ignores trailing junk.
            resp, _ = json.JSONDecoder().raw_decode(raw)
        except (json.JSONDecodeError, ValueError):
            import re as _re
            match = _re.search(r'\{.*\}', raw, _re.DOTALL)
            if match:
                resp = json.loads(match.group())
            else:
                raise ValueError(f"Cannot parse LLM response: {raw[:200]}")

        content = ""
        if "choices" in resp and resp["choices"]:
            choice = resp["choices"][0]
            msg = choice.get("message", {})
            content = str(msg.get("content", "")).strip()
            if not content:
                content = str(msg.get("reasoning_content", "")).strip()
        content = content.strip('"').strip("'").strip()
        content = content.split("\n")[0].strip()
        # Guard: caption harus substantive. Kalau LLM balikin kosong / cuma
        # URL / 1-2 huruf (sisa unicode-drop CJK), JANGAN post itu — fallback
        # ke teks asli yang udah kebukti utuh.
        import re as _re2
        meaningful = _re2.sub(r'https?://\S+|@\w+|[\s\W_]+', '', content)
        if len(meaningful) < 8:
            log(f"⚠️  Caption degenerate ({content!r}), fallback ke teks asli")
            return original_text[:100]
        return content[:120]
    except Exception as e:
        log(f"⚠️  LLM caption failed: {e}")
        return original_text[:100]


def post_video(tweet_url, video_path, caption=""):
    """Post video to @mhucex via stealth browser engine"""
    from x_stealth_browser import post_tweet

    log(f"📤 Posting video to @mhucex...")
    
    # Use post_tweet with video_path — stealth browser handles everything
    success, result = post_tweet(caption, video_path=video_path, headless=True)
    
    if not success:
        log(f"❌ Post failed: {result}")
        return False, None
    
    # result is either URL or error message
    if result and '/status/' in str(result):
        log(f"✅ Posted: {result}")
        return True, result
    else:
        log(f"✅ Post submitted (URL unknown)")
        return True, None


def repost_video(source_url, caption=None):
    """Full pipeline: download video from tweet → auto-rewrite caption → repost → delete video"""
    start = time.time()
    results = {"downloaded": False, "posted": False, "video_path": None, "post_url": None, "caption": None}

    # Step 1: Download video
    video_path = download_video(source_url)
    if not video_path:
        log("❌ Cannot proceed without video")
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        box("🎬 VIDEO REPOST", {
            "🕐 Time": ts,
            "📊 Status": "❌ Download Failed",
            "🔗 Source": source_url,
        })
        return results

    results["downloaded"] = True
    results["video_path"] = video_path

    # Step 2: Compress if needed
    video_path = compress_video(video_path)

    # Step 3: Auto-rewrite caption from original tweet text
    if caption is None:
        log("📝 Fetching original tweet text...")
        original_text = get_original_text(source_url)
        if original_text:
            log(f"📝 Original: {original_text[:80]}...")
            caption = condense_caption(original_text, source_url)
            log(f"✏️  Condensed: {caption}")
        else:
            log("⚠️  No original text found, posting without caption")
            caption = ""
    results["caption"] = caption

    # Step 4: Post to @mhucex
    success, post_url = post_video(source_url, video_path, caption)
    results["posted"] = success
    results["post_url"] = post_url

    # Step 5: Delete video file after posting (success or fail)
    try:
        if results["video_path"] and os.path.exists(results["video_path"]):
            os.unlink(results["video_path"])
            log(f"🗑️  Video deleted: {results['video_path']}")
        # Also clean compressed version if different
        compressed = results["video_path"].replace(".mp4", "_compressed.mp4")
        if os.path.exists(compressed):
            os.unlink(compressed)
    except Exception as e:
        log(f"⚠️  Delete failed: {e}")

    elapsed = time.time() - start
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    status = "✅ Posted" if success else "❌ Post Failed"
    box("🎬 VIDEO REPOST", {
        "🕐 Time": ts,
        "📊 Status": status,
        "🔗 Source": source_url,
        "✏️  Caption": caption[:50] if caption else "(none)",
        "📤 Post": post_url or "N/A",
        "⏱️  Elapsed": f"{elapsed:.0f}s",
    })

    # Exit with error code if post failed (so wrapper reports correctly)
    if not success:
        sys.exit(1)

    return results


def auto_video_repost():
    """Auto mode: scan timeline for tweets with video → pick best → repost"""
    from x_stealth_browser import load_cookies, new_browser
    from playwright.sync_api import sync_playwright

    STATE_FILE = "/tmp/x_video_repost_state.json"
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
    except:
        state = {"processed": [], "last_run": None}

    processed = set(state.get("processed", []))

    log("🔍 Scanning timeline for video tweets...")

    pw = None
    browser = None
    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
        )
        load_cookies(context)
        page = context.new_page()
        page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(4000)

        # Scroll to load more tweets
        for _ in range(3):
            page.mouse.wheel(0, 800)
            page.wait_for_timeout(1500)

        # Find tweets with video indicators
        video_tweets = page.evaluate("""
        () => {
            const articles = document.querySelectorAll('article');
            const results = [];
            articles.forEach(el => {
                const innerText = el.innerText || '';
                // Skip replies/quotes
                if (innerText.includes('Membalas') || innerText.includes('Kutipan')) return;
                // Check for video indicator (play button, video thumbnail)
                const hasVideo = el.querySelector('[data-testid="videoPlayer"]') ||
                                 el.querySelector('video') ||
                                 el.querySelector('[aria-label*="Play"]') ||
                                 el.querySelector('[d*="M11.5"]'); // SVG play icon path
                if (!hasVideo) return;
                const link = el.querySelector('a[href*="/status/"]');
                if (!link) return;
                let href = link.getAttribute('href');
                if (!href.startsWith('http')) href = 'https://x.com' + href;
                // Get view count
                const viewLink = el.querySelector('a[href*="/analytics"]');
                const views = viewLink ? viewLink.innerText.trim() : '';
                // Get text content for filtering
                const textEl = el.querySelector('[lang]') || el;
                const text = textEl.innerText || '';
                results.push({url: href, views: views, text: text.substring(0, 300)});
            });
            return results;
        }
        """)

        context.close()
        browser.close()
        pw.stop()
        pw = None

    except Exception as e:
        log(f"❌ Timeline scan failed: {e}")
        try:
            if pw:
                context.close()
                browser.close()
                pw.stop()
        except:
            pass
        return None

    # Filter: remove already processed + crypto tweets
    new_tweets = [t for t in video_tweets if t["url"] not in processed]
    crypto_filtered = []
    for t in new_tweets:
        if is_crypto(t.get("text", "")):
            log(f"  ⏭️ Crypto filtered: {t.get('text', '')[:50]}...")
        else:
            crypto_filtered.append(t)
    new_tweets = crypto_filtered
    log(f"📊 Found {len(video_tweets)} video tweets, {len(new_tweets)} new (crypto filtered)")

    if not new_tweets:
        log("⏭️  No new video tweets, skipping")
        return None

    # Pick a random one from new tweets
    target = random.choice(new_tweets)
    log(f"🎯 Selected: {target['url']} (views: {target['views']})")

    # Repost it
    result = repost_video(target["url"])

    # Save state
    processed.add(target["url"])
    state["processed"] = list(processed)[-100:]
    state["last_run"] = datetime.now().isoformat()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

    return result


if __name__ == "__main__":
    if "--auto" in sys.argv:
        # Time gate: 06:00-23:00 WIB
        import os as _os
        _os.environ.setdefault("TZ", "Asia/Jakarta")
        hour = int(datetime.now().strftime("%H"))
        if hour < 6 or hour >= 23:
            sys.exit(0)
        auto_video_repost()
    elif len(sys.argv) >= 2 and sys.argv[1] != "--auto":
        source = sys.argv[1]
        caption = sys.argv[2] if len(sys.argv) > 2 else None
        repost_video(source, caption)
    else:
        print("Usage:")
        print("  python3 x_video_repost.py <tweet_url> [caption]  — repost specific tweet")
        print("  python3 x_video_repost.py --auto                 — auto-scan timeline & repost")
        sys.exit(1)
