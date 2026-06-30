#!/usr/bin/env python3
"""
Reply Hunter - Finds and replies to non-Indonesian/non-crypto tweets, quotes/replies.
Target: 100K+ views, max 5 days old, non-Indonesian, non-crypto
Uses: x_stealth_browser.py with SINGLE browser session (no EPIPE)
"""
import json, time, random, re, sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from box_helper import box
from x_stealth_browser import (
    post_tweet, search_tweets, get_timeline_tweets,
    set_default_browser_type, new_browser,
    load_cookies, stop_playwright,
)

set_default_browser_type("chromium")  # Chrome for better non-Latin (Japanese/Chinese/Korean) support

STATE_FILE = "/tmp/x_reply_hunter_state.json"
MAX_QUOTES_PER_RUN = 0      # DISABLED - Quote only for timeline_draft
MAX_REPLIES_PER_RUN = 2     # Reply only from timeline
MIN_VIEWS_THRESHOLD = 30000   # 30K views minimum (lowered from 50K for more targets)

# Use OmbrO combo (8 models, round-robin via 9router)
LLM_MODEL = "OmbrO"

def _get_llm_key():
    """Get API key from 9router SQLite DB"""
    import sqlite3
    try:
        conn = sqlite3.connect(os.environ.get('ROUTER_DB_PATH', os.path.expanduser('~/.9router/db/data.sqlite')))
        cursor = conn.cursor()
        cursor.execute("SELECT key FROM apiKeys WHERE isActive=1 LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        if row:
            return row[0]
    except Exception as e:
        print(f"⚠️ Failed to get API key: {e}")
    return None

INDONESIAN_PATTERNS = [
    r'\b(aku|saya|kamu|lu|lo|gue|gua|dia|mereka|kita|kami)\b',
    r'\b(Indonesia|indonesia|Jakarta|Surabaya|Bandung|Bali|Medan|Jogja)\b',
    r'\b(nasi padang|sate|rendang|indomie|soto|bakso|warteg)\b',
    r'\b(anjir|bulol|baper|cewekcowok|receh|garing)\b',
]
INDONESIAN_REGEX = re.compile('|'.join(INDONESIAN_PATTERNS), re.IGNORECASE)

CRYPTO_PATTERNS = [
    r'\b(bitcoin|crypto|btc|eth|binance|trading|airdrops|defi|nft|web3)\b',
    r'\b(ripple|solana|cardano|polkadot|doge|shiba|pepe|meme coin)\b',
]
CRYPTO_REGEX = re.compile('|'.join(CRYPTO_PATTERNS), re.IGNORECASE)

VIRAL_QUERIES = [
    "going reply", "reply tweet", "insane", "unbelievable", "crazy video",
    "breaking", "amazing", "wow", "omg", "trending now", "must watch",
    "this is crazy", "you won't believe", "absolutely insane",
]

try:
    from emoji_notify import make_telegram_notify
    HAS_NOTIFY = True
except ImportError:
    HAS_NOTIFY = False

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except:
        return {"processed": [], "quotes": 0, "replies": 0, "last_run": None}

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)

def is_indonesian(text):
    return bool(INDONESIAN_REGEX.search(text))

def is_crypto(text):
    return bool(CRYPTO_REGEX.search(text))

def detect_language(text):
    # Script-based detection first: Hangul / Kana / Han pick the right native
    # prompt so Chinese & Korean tweets get Chinese/Korean replies, not English.
    import re as _re
    if _re.search(r'[\uAC00-\uD7AF\u1100-\u11FF]', text):
        return 'ko'  # Hangul
    if _re.search(r'[\u3040-\u309F\u30A0-\u30FF]', text):
        return 'ja'  # Hiragana/Katakana (Japanese)
    if _re.search(r'[\u4E00-\u9FFF\u3400-\u4DBF]', text):
        return 'zh'  # Han characters (no kana) → treat as Chinese
    indonesian_count = len(INDONESIAN_REGEX.findall(text))
    english_words = len([w for w in text.split() if w.lower() not in ['the','a','an','is','are','was','be','to','of','and']])
    return 'id' if indonesian_count > english_words * 0.3 else 'en'

def generate_reply_reply(text, lang):
    """Generate contextual reply via LLM (9router/Claude), fallback to template."""
    text_preview = text[:200].replace('\n', ' ').strip()
    lang_sys = {
        'en': "You are a sharp, opinionated person on X with varied takes. Output ONLY the reply — no preamble, no explanation. Write 1-2 punchy sentences (max 200 chars). State a clear opinion, push back, or add context. Vary your phrasing: rhetorical questions, counterintuitive angles, or call out the unspoken implication. No filler phrases ('the story here', 'people don't realize', 'the framing matters'). No hype words, no hashtags. Be fresh every time.",
        'id': "Kamu orang yang tegas di X. Keluarkan HANYA teks balasannya — tanpa pembuka, tanpa tanda kutip, tanpa alternatif, tanpa penjelasan. SATU kalimat tegas di bawah 120 karakter. Nyatakan pendapat jelas atau insight nyata tentang tweet ini. Tanpa kata-kata hype kosong, tanpa hashtag.",
        'ja': "あなたはXで率直な意見を持つ人。返信テキストのみ出力（前置き・引用符・代替案・説明なし）。120文字以内の断定的な1文。明確な意見や本質的な洞察を述べる。空虚な称賛・ハッシュタグ禁止。",
        'ko': "당신은 X에서 직설적인 사람. 답변 텍스트만 출력(설명·따옴표·대안 없이). 120자 이내 단호한 한 문장. 명확한 의견이나 진짜 인사이트를 말할 것. 공허한 칭찬·해시태그 금지.",
        'zh': "你是X上直接表达观点的人。只输出回复本身（无前言、引号、备选、解释）。120字以内一句有力的话。说清楚你的立场或真正的见解。不要空洞的赞美，无标签。",
    }
    try:
        import requests, re as _re, sqlite3, os
        # Fetch active API key from 9Router
        try:
            conn = sqlite3.connect(os.path.expanduser("~/.9router/db/data.sqlite"))
            row = conn.execute("SELECT key FROM apiKeys WHERE isActive=1 LIMIT 1").fetchone()
            conn.close()
            api_key = row[0] if row else ""
        except Exception:
            api_key = ""
        
        payload = {
            "model": "OmbrO",
            "messages": [
                {"role": "system", "content": lang_sys.get(lang, lang_sys['en'])},
                {"role": "user", "content": f"Tweet:\n{text_preview}\n\nYour reply:"}
            ],
            "max_tokens": 200,
            "temperature": 0.95,
            "stream": False,
        }
        headers = {"Content-Type": "application/json"}
        # Use 9Router local (direct IP, not ombro.my.id which blocks AWS)
        HERMES_URL = "http://127.0.0.1:20128/v1"
        HERMES_KEY = _get_llm_key()  # fetched dynamically from 9router DB
        headers["Authorization"] = f"Bearer {HERMES_KEY}"
        r = requests.post(
            f"{HERMES_URL}/chat/completions",
            headers=headers,
            json=payload, timeout=18,
        )
        r.raise_for_status()
        content = str(r.json()['choices'][0]['message']['content'])
        # Strip thinking tags
        import re as _re
        content = _re.sub(r'<think>.*?</think>', '', content, flags=_re.DOTALL).strip()
        clean = _clean_llm_reply(content)
        if clean and len(clean) > 3:
            log(f"🤖 LLM reply: {clean[:80]}")
            return clean[:280]
        raise Exception("empty LLM content")
    except Exception as e:
        log(f"⚠️ LLM reply failed ({e}) — skipping post")
        return None


def _clean_llm_reply(content):
    """Strip meta-preamble, pick first sentence, reject refusal/meta-commentary."""
    import re as _re
    text = content.strip()
    # Drop common meta preambles ("Here's a reply...", "Balasan:", etc.)
    text = _re.sub(r"(?is)^(here'?s?\s|here are\s|berikut\s|ini\s(balasan|reply)|balasan\s|reply:?\s|sure[,!]?\s).*?[:\n]", "", text, count=1).strip()
    # Prefer markdown quote line, else first non-empty line
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    quoted = [l.lstrip('> ').strip() for l in lines if l.lstrip().startswith('>')]
    candidates = quoted if quoted else lines
    if not candidates:
        return ""
    reply = candidates[0]
    reply = reply.strip('"').strip("'").strip('*').lstrip('-').lstrip('•').strip()
    reply = _re.sub(r'^\*+|\*+$', '', reply).strip()
    # Reject meta/refusal commentary — model talking ABOUT replying instead of replying
    meta_signals = [
        "i'd skip", "i would skip", "fact-check", "fact check", "i can't", "i cannot",
        "i won't", "as an ai", "i'd keep it", "i would keep", "if you want to post",
        "unverified", "recycled reply", "i'd recommend", "i'd suggest", "i'd advise",
        "i'm not able", "rather not", "amplifying",
    ]
    low = reply.lower()
    if any(s in low for s in meta_signals):
        return ""
    # Keep only the first sentence to stay short & punchy
    parts = _re.split(r'(?<=[.!?。！？])\s+', reply, maxsplit=1)
    first = parts[0].strip() if parts else reply
    # If first sentence is too short (just an interjection), keep up to 200 chars of original
    if len(first) < 15 and len(reply) > len(first):
        first = reply[:200].strip()
    return first[:240]

# Global browser for search (single session, reused, no EPIPE)
_search_browser = None
_search_context = None

def init_search_browser():
    """Init browser ONCE, reuse for all searches, close at end."""
    global _search_browser, _search_context
    if _search_browser is None:
        log("Starting browser for searches...")
        _search_browser, _search_context = new_browser(headless=True, browser_type="firefox")
        log("Browser started.")
    return _search_browser, _search_context

def close_search_browser():
    global _search_browser, _search_context
    if _search_browser:
        try:
            _search_browser.close()
        except:
            pass
        _search_browser = None
        _search_context = None

def _parse_view_count(text: str) -> int:
    """Parse Indonesian/English view counts: '137 rb'=137K, '1.2M'=1.2M, '14\xa0rb'=14K, '8 Tayangan'=8"""
    import re
    text = text.replace('\n', ' ').replace('\xa0', ' ').strip()
    # Pattern 1: number + K/M/RB/JT suffix (with optional views/tayangan)
    m = re.match(r'([\d.,]+)\s*(rb|jt|K|M)\b', text, re.IGNORECASE)
    if m:
        num = float(m.group(1).replace(',', '.'))
        unit = m.group(2).lower()
        if unit in ('rb', 'k'): return int(num * 1000)
        if unit in ('jt', 'm'): return int(num * 1_000_000)
    # Pattern 2: plain number with "views" or "Tayangan" suffix
    m2 = re.match(r'([\d,]+)\s*(views?|tayangan)', text, re.IGNORECASE)
    if m2:
        return int(m2.group(1).replace(',', ''))
    return 0

def _get_views_from_tweet_page(page, tweet_url: str) -> int:
    """Extract view count from tweet page via analytics link in article."""
    try:
        page.goto(tweet_url, timeout=8000, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        page.mouse.wheel(0, 200)
        page.wait_for_timeout(1000)

        result = page.evaluate("""
() => {
  const article = document.querySelector('article');
  if (!article) return '';
  const viewLink = article.querySelector('a[href*="/analytics"]');
  if (viewLink) return viewLink.innerText.trim();
  
  // Fallback: search all divs for view-like text
  const divs = article.querySelectorAll('div');
  for (const d of divs) {
    const t = d.innerText.trim();
    if (/^\\d+\\s*(rb|jt|K|M|tayangan)?$/i.test(t) && t.length < 20) return t;
  }
  return '';
}
""")
        return _parse_view_count(result)
    except:
        return 0

def _extract_tweets_via_js(page) -> list:
    """Extract tweets using JS (reliable, bypasses locator quirks).
    Only extracts ORIGINAL tweets (no replies, no quotes).
    Also captures engagement signals (replies/reposts/likes/views) so callers
    can prioritize high-exposure tweets for follower growth."""
    try:
        tweets = page.evaluate("""
() => {
  const articles = document.querySelectorAll('article');
  const results = [];
  const parseNum = (s) => {
    if (!s) return 0;
    s = s.replace(/,/g, '').trim();
    let m = s.match(/([\\d.]+)\\s*([KMrbjt]+)?/i);
    if (!m) return 0;
    let n = parseFloat(m[1]);
    const suf = (m[2] || '').toLowerCase();
    if (suf.includes('m') || suf.includes('jt')) n *= 1e6;
    else if (suf.includes('k') || suf.includes('rb')) n *= 1e3;
    return Math.round(n);
  };
  // Detect the GOLD (verified-organization) checkmark on a tweet author.
  // X uses identical aria-label ("Akun terverifikasi") for ALL badges — the
  // real differentiator is COLOR: blue individual = rgb(29,155,240) (b≈240);
  // gold org / gray gov use an SVG gradient → computed color stays dark (low b).
  const isGoldVerified = (el) => {
    const nameBlock = el.querySelector('[data-testid="User-Name"]') || el;
    const icon = nameBlock.querySelector('svg[data-testid="icon-verified"]');
    if (!icon) return false;  // unverified individual — keep
    const m = (getComputedStyle(icon).color || '').match(/rgba?\\(([^)]+)\\)/);
    if (m) {
      const b = parseFloat(m[1].split(',')[2]);
      if (b < 180) return true;  // non-blue verified = org/gov → skip
    }
    return false;
  };
  articles.forEach(el => {
    const innerText = el.innerText || '';
    // Skip replies ("Membalas") and quotes ("Kutipan")
    if (innerText.includes('Membalas') || innerText.includes('Kutipan')) return;
    const link = el.querySelector('a[href*="/status/"]');
    const textEl = el.querySelector('[lang]');
    const text = textEl ? textEl.innerText : innerText;
    if (link && text.trim()) {
      let href = link.getAttribute('href');
      if (!href.startsWith('http')) href = 'https://x.com' + href;
      const goldVerified = isGoldVerified(el);
      // Engagement: the action bar buttons carry aria-labels with counts.
      let likes = 0, replies = 0, reposts = 0, views = 0;
      const grp = el.querySelector('[role="group"]');
      if (grp) {
        const lbl = (grp.getAttribute('aria-label') || '').toLowerCase();
        // aria-label like "12 replies, 30 reposts, 450 likes, 12000 views"
        const rep = lbl.match(/([\\d.,]+)\\s*(repl|balas)/);
        const rt  = lbl.match(/([\\d.,]+)\\s*(repost|retweet)/);
        const lk  = lbl.match(/([\\d.,]+)\\s*(like|suka)/);
        const vw  = lbl.match(/([\\d.,]+)\\s*(view|tayang)/);
        if (rep) replies = parseNum(rep[1]);
        if (rt)  reposts = parseNum(rt[1]);
        if (lk)  likes   = parseNum(lk[1]);
        if (vw)  views   = parseNum(vw[1]);
      }
      results.push({url: href, text: text.substring(0, 300),
                    likes, replies, reposts, views, goldVerified});
    }
  });
  return results;
}
""")
        return tweets
    except:
        return []

def get_timeline_fast(count=10):
    """Get tweets from home timeline using JS extraction."""
    browser, context = init_search_browser()
    page = context.new_page()
    try:
        page.goto("https://x.com/home", timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        page.mouse.wheel(0, 800)
        page.wait_for_timeout(1000)
        tweets = _extract_tweets_via_js(page)
        return tweets[:count]
    finally:
        page.close()

def get_search_fast(query, count=5):
    """Search tweets using JS extraction."""
    browser, context = init_search_browser()
    page = context.new_page()
    try:
        page.goto(f"https://x.com/search?q={query}&f=live", timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        page.mouse.wheel(0, 800)
        page.wait_for_timeout(1000)
        tweets = _extract_tweets_via_js(page)
        return tweets[:count]
    finally:
        page.close()

def run():
    state = load_state()
    state["last_run"] = datetime.now().isoformat()
    processed = set(state.get("processed", []))
    results = {"quotes": 0, "replies": 0, "skipped": 0}

    log("✅ REPLY-ONLY MODE - Hunting timeline tweets")

    all_tweets = []

    # Timeline ONLY - no search (search disabled for reply-only mode)
    log("📋 Scanning timeline for reply targets...")
    try:
        timeline = get_timeline_fast(count=15)
        for tweet in timeline:
            url = tweet.get('url', '')
            text = tweet.get('text', '')
            # Normalize to clean tweet permalink: strip /photo/N, /analytics, query/fragment
            m = re.search(r'(https?://(?:x|twitter)\.com/[^/]+/status/\d+)', url)
            if m:
                url = m.group(1)
                tweet['url'] = url
            if text and url and url not in processed:
                if tweet.get('goldVerified'):
                    log(f"  🟡 Skip centang kuning (org) - {text[:40]}...")
                    continue
                if not is_indonesian(text) and not is_crypto(text):
                    log(f"  ✅ Timeline target - {text[:50]}...")
                    all_tweets.append((tweet, url))
                    processed.add(url)
    except Exception as e:
        log(f"  Timeline error: {e}")

    # NO view count check - reply directly to timeline tweets
    log(f"📊 {len(all_tweets)} candidates from timeline (no view filter)")
    browser, context = init_search_browser()
    # Close search browser BEFORE posting - two concurrent Playwright instances = EPIPE on t3.micro
    close_search_browser()

    # GROWTH: reply to the highest-exposure tweet, not a random one. More eyeballs
    # on the parent tweet = more profile clicks on our reply = more follows.
    # Score = views + weighted engagement (likes/reposts/replies carry intent).
    def _exposure(item):
        tw = item[0]
        return (tw.get('views', 0)
                + tw.get('likes', 0) * 10
                + tw.get('reposts', 0) * 20
                + tw.get('replies', 0) * 5)
    all_tweets.sort(key=_exposure, reverse=True)
    # Keep a little randomness among the top tier so we're not 100% predictable:
    # shuffle only within the top 5, then take the best.
    top = all_tweets[:5]
    random.shuffle(top)
    top.sort(key=_exposure, reverse=True)
    all_tweets = top + all_tweets[5:]
    if all_tweets:
        _t = all_tweets[0][0]
        log(f"🎯 Top target exposure: {_exposure(all_tweets[0])} "
            f"(👁{_t.get('views',0)} ♥{_t.get('likes',0)} 🔁{_t.get('reposts',0)})")

    # Engagement phase - REPLY ONLY MODE (no quotes)
    posted_links = []  # (action, target_url, our_url)
    for tweet, tweet_url in all_tweets[:1]:
        if results["replies"] >= MAX_REPLIES_PER_RUN:
            break

        # Force reply mode (no random quote/reply)
        action = "reply"
        text = tweet.get('text', '')
        lang = detect_language(text)
        interaction_text = generate_reply_reply(text, lang)

        # Skip if LLM failed (None = no fallback template)
        if not interaction_text:
            log(f"  ⏭️ Skipping — LLM failed to generate reply")
            continue

        if action == "reply" and results["replies"] < MAX_REPLIES_PER_RUN:
            # Retry up to 2 times on EPIPE/browser crash
            success = False
            our_url = ""
            for attempt in range(3):
                try:
                    log(f"Posting reply (attempt {attempt+1}/3)...")
                    success, our_url = post_tweet(interaction_text, reply_to_url=tweet_url)
                    if success:
                        results["replies"] += 1
                        log(f"✅ Reply posted: {our_url}")
                        posted_links.append(("↩️ Reply", tweet_url, our_url, "timeline"))
                        break
                    else:
                        log(f"⚠️ Post failed (attempt {attempt+1}/3): {our_url}")
                except Exception as e:
                    err = str(e)
                    if 'EPIPE' in err or 'write EPIPE' in err:
                        log(f"⚠️ EPIPE detected (attempt {attempt+1}/3) - retrying in 3s...")
                        if attempt < 2:
                            time.sleep(3)
                            continue
                    log(f"❌ Error (attempt {attempt+1}/3): {e}")
                    our_url = str(e)
                    break
            if not success:
                log(f"❌ Reply failed after 3 attempts: {our_url}")

        time.sleep(random.uniform(2, 4))

    state["processed"] = list(processed)[-50:]
    state["quotes"] = state.get("quotes", 0) + results["quotes"]
    state["replies"] = state.get("replies", 0) + results["replies"]
    save_state(state)

    # Parse CLI flag
    no_header_box = False
    if "--no-header-box" in sys.argv:
        no_header_box = True
        sys.argv.remove("--no-header-box")

    # Output ringkas
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if not no_header_box:
        # box_helper ━━━ format
        try:
            if HAS_NOTIFY:
                make_telegram_notify("reply_hunter", [
                    ("Quotes", str(results['quotes'])),
                    ("Replies", str(results['replies'])),
                ], action="reply_hunter")
        except Exception:
            pass
        box("🦠 REPLY HUNTER", {
            "🕐 Time    ": ts,
            "🔁 Quotes  ": str(results['quotes']),
            "↩️  Replies ": str(results['replies']),
            "⏭️  Skip    ": str(results['skipped']),
            "📊 Total   ": f"{state['quotes']}Q / {state['replies']}R",
        })
        if posted_links:
            for act, target, ours, views in posted_links:
                label = "🔁 Quote" if "Quote" in act else "↩️  Reply"
                print(f"{label} ({views})")
                print(f"   🎯 Target : {target}")
                print(f"   ✅ Posted : {ours}")
        else:
            print("❌ No posts this run")
    else:
        # legacy freeform output (wrapper already printed box header)
        print(f"🦠 Reply Hunter — {ts}")
        print(f"Quotes  : {results['quotes']}")
        print(f"Replies : {results['replies']}")
        print(f"Skip    : {results['skipped']}")
        print(f"Total   : {state['quotes']}Q / {state['replies']}R")
        if posted_links:
            for act, target, ours, views in posted_links:
                label = "🔁 Quote" if "Quote" in act else "↩️  Reply"
                print(f"{label} ({views})")
                print(f"   Target : {target}")
                print(f"   Posted : {ours}")
        else:
            print("No posts this run")
    
    # JSON summary for wrapper parsing (must be last line)
    print(f'SUMMARY: {{"quotes": {results["quotes"]}, "replies": {results["replies"]}, "skip": {results["skipped"]}}}')

    stop_playwright()

if __name__ == "__main__":
    import os, signal
    _deadline = int(os.getenv("X_RUN_DEADLINE", "0"))
    if _deadline > 0:
        def _on_deadline(signum, frame):
            # Raising through Playwright's C driver is unreliable, and closing the
            # browser here can block until SIGKILL. Just force a clean exit code so
            # the cron wrapper logs success, not exit 124. OS reaps child processes.
            log(f"⏰ Deadline {_deadline}s reached — graceful clean exit")
            os._exit(0)
        signal.signal(signal.SIGALRM, _on_deadline)
        signal.alarm(_deadline)
    try:
        run()
    finally:
        try:
            signal.alarm(0)
        except Exception:
            pass
        close_search_browser()
        stop_playwright()