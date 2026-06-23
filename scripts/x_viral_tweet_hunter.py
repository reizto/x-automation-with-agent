#!/usr/bin/env python3
"""
Viral Tweet Hunter - Finds viral non-Indonesian/non-crypto tweets, quotes/replies.
Target: 100K+ views, max 5 days old, non-Indonesian, non-crypto
Uses: x_stealth_browser.py with SINGLE browser session (no EPIPE)
"""
import json, time, random, re, sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, '/home/ubuntu/.hermes/scripts')
sys.path.insert(0, "/home/ubuntu")
from box_helper import box
from x_stealth_browser import (
    post_tweet, search_tweets, get_timeline_tweets,
    set_default_browser_type, close_browser, new_browser,
    load_cookies, stop_playwright,
)

set_default_browser_type("firefox")

STATE_FILE = "/tmp/x_viral_hunter_state.json"
MAX_QUOTES_PER_RUN = 1
MAX_REPLIES_PER_RUN = 1
MIN_VIEWS_THRESHOLD = 10000   # 10K views minimum (realistic for general tweets)

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
    "going viral", "viral tweet", "insane", "unbelievable", "crazy video",
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
    indonesian_count = len(INDONESIAN_REGEX.findall(text))
    english_words = len([w for w in text.split() if w.lower() not in ['the','a','an','is','are','was','be','to','of','and']])
    return 'id' if indonesian_count > english_words * 0.3 else 'en'

def generate_viral_reply(text, lang):
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
            "model": "Lemah",
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
        "unverified", "recycled viral", "i'd recommend", "i'd suggest", "i'd advise",
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
        _search_browser, _search_context = new_browser(headless=True, use_xvfb=True, browser_type="firefox")
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
    Only extracts ORIGINAL tweets (no replies, no quotes)."""
    try:
        tweets = page.evaluate("""
() => {
  const articles = document.querySelectorAll('article');
  const results = [];
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
      results.push({url: href, text: text.substring(0, 300)});
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

    log("✅ Logged in - Hunting viral tweets")

    all_tweets = []
    queries = random.sample(VIRAL_QUERIES, 1)

    # Search phase - reuses single browser
    for query in queries:
        log(f"🔍 Searching: {query}")
        try:
            tweets = get_search_fast(query, count=5)
            log(f"  Found {len(tweets)} tweets")
        except Exception as e:
            log(f"  Search error: {e}")
            tweets = []

        for tweet in tweets:
            try:
                url = tweet.get('url', '')
                text = tweet.get('text', '')

                if not text or not url or url in processed:
                    continue

                if is_indonesian(text):
                    results["skipped"] += 1
                    continue
                if is_crypto(text):
                    results["skipped"] += 1
                    continue

                log(f"  ✅ Passed filters - {text[:50]}...")
                all_tweets.append((tweet, url))
                processed.add(url)
            except:
                pass

    # Also check timeline
    log("📋 Checking timeline...")
    try:
        timeline = get_timeline_fast(count=5)
        for tweet in timeline:
            url = tweet.get('url', '')
            text = tweet.get('text', '')
            if text and url and url not in processed:
                if not is_indonesian(text) and not is_crypto(text):
                    log(f"  ✅ Timeline passed - {text[:50]}...")
                    all_tweets.append((tweet, url))
                    processed.add(url)
    except Exception as e:
        log(f"  Timeline error: {e}")

    # Check view counts before engaging (max 5 tweets: ~30s, leaves time for posting)
    log(f"📊 Checking views for {len(all_tweets)} candidates...")
    browser, context = init_search_browser()
    page = context.new_page()
    view_checked = []
    for tweet, tweet_url in all_tweets[:2]:
        text = tweet.get('text', '')
        views = _get_views_from_tweet_page(page, tweet_url)
        if views >= MIN_VIEWS_THRESHOLD:
            log(f"  ✅ {views:,} views - {text[:50]}...")
            view_checked.append((tweet, tweet_url, views))
        else:
            log(f"  ⏭ Skipping ({views:,} views < {MIN_VIEWS_THRESHOLD:,}) - {text[:50]}...")
        time.sleep(1)

    all_tweets = view_checked
    log(f"📊 {len(all_tweets)} tweets meet {MIN_VIEWS_THRESHOLD:,} view threshold")

    # Close search browser BEFORE posting - two concurrent Playwright instances = EPIPE on t3.micro
    page.close()
    close_search_browser()

    random.shuffle(all_tweets)

    # Engagement phase
    posted_links = []  # (action, target_url, our_url)
    for tweet, tweet_url, views in all_tweets[:1]:
        if results["quotes"] >= MAX_QUOTES_PER_RUN and results["replies"] >= MAX_REPLIES_PER_RUN:
            break

        action = random.choice(["quote", "reply"])
        text = tweet.get('text', '')
        lang = detect_language(text)
        interaction_text = generate_viral_reply(text, lang)

        # Skip if LLM failed (None = no fallback template)
        if not interaction_text:
            log(f"  ⏭️ Skipping — LLM failed to generate reply/quote")
            continue

        if action == "quote" and results["quotes"] < MAX_QUOTES_PER_RUN:
            success, our_url = post_tweet(interaction_text, quote_url=tweet_url)
            if success:
                results["quotes"] += 1
                posted_links.append(("🔁 Quote", tweet_url, our_url, f"{views:,}v"))

        elif action == "reply" and results["replies"] < MAX_REPLIES_PER_RUN:
            success, our_url = post_tweet(interaction_text, reply_to_url=tweet_url)
            if success:
                results["replies"] += 1
                posted_links.append(("↩️ Reply", tweet_url, our_url, f"{views:,}v"))

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
                make_telegram_notify("viral_hunter", [
                    ("Quotes", str(results['quotes'])),
                    ("Replies", str(results['replies'])),
                ], action="viral_hunter")
        except Exception:
            pass
        box("🦠 VIRAL HUNTER", {
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
        print(f"🦠 Viral Hunter — {ts}")
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
    
    stop_playwright()

if __name__ == "__main__":
    try:
        run()
    finally:
        close_search_browser()
        stop_playwright()