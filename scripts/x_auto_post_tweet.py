#!/usr/bin/env python3
"""
X Auto Post — cronjob pipeline:
  1. last30days research (ambil topik random dari trending)
  2. Generate image via multi-provider fallback chain
  3. Post tweet to @mhucex via Playwright
  4. English only, dengan source link

Image fallback chain:
  CF Workers AI (SDXL, free quota)
  Pollinations AI (flux, free, no auth)
  image_gen Hermes tool (FAL/OpenAI backend)

Run: python3 scripts/x_auto_post_tweet.py
"""

import sys, os, json, random, subprocess, time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
SYS_PATH = os.environ.get("LAST30DAYS_SCRIPTS", "")

# ── last30days research ────────────────────────────────────────
# ── Dynamic niche buckets (growth mode) ───────────────────────
AI_TECH = [
    "AI replacing junior developers",
    "Nvidia stock bubble",
    "OpenAI vs open-source models",
    "AI agents hype vs reality",
    "remote work productivity myth",
]

CRYPTO = [
    "bitcoin ETF flow",
    "Ethereum L2 war",
    "solana memecoin rug",
    "DeFi hack 2026",
    "crypto exchange insolvency risk",
]

MACRO = [
    "US interest rate pivot",
    "dollar liquidity crisis",
    "tech layoffs 2026",
    "startup funding winter",
]

CULTURE = [
    "burnout culture in startups",
    "internet clout economy",
    "creator monetization collapse",
    "digital minimalism trend",
]

# Weighted growth rotation
BUCKETS = (
    AI_TECH * 4 +      # 40%
    CRYPTO * 3 +       # 30%
    MACRO * 2 +        # 20%
    CULTURE * 1        # 10%
)

TOPICS = BUCKETS

def research_topic() -> dict:
    """Panggil last30days, ambil hasil buat bahan tweet."""
    topic = random.choice(TOPICS)
    print(f"Research: '{topic}'")
    try:
        r = subprocess.run(
            [sys.executable, f"{SYS_PATH}/last30days.py", topic,
             "--emit=compact", "--max-results=5"],
            capture_output=True, text=True, timeout=120,
            cwd=SYS_PATH
        )
        return {"topic": topic, "raw": r.stdout, "stderr": r.stderr}
    except Exception as e:
        return {"topic": topic, "error": str(e)}

# ── Draft tweet ─────────────────────────────────────────────────
LLM_BASE_URL = "http://127.0.0.1:20128/v1"
# Fallback chain: try models in order until one works
LLM_MODELS = [
    "tokenrouter/anthropic/claude-sonnet-4.6",          # Primary (1.29s)
    "tensormesh/deepseek-ai/DeepSeek-V4-Flash",         # Fast TensorMesh (0.40s)
    "tokenrouter/openai/gpt-5.2",                       # Fast fallback (0.74s)
    "hugingface/meta-llama/Llama-3.3-70B-Instruct",     # Fastest (0.38s)
    "openrouter/openai/gpt-4o",                         # Reliable (1.21s)
]

def _get_llm_key() -> str:
    """Ambil API key aktif dari 9router DB secara dinamis."""
    try:
        import sqlite3 as _sq
        db = _sq.connect(os.environ.get("ROUTER_DB_PATH", os.path.expanduser("~/.9router/db/data.sqlite")))
        row = db.execute("SELECT key FROM apiKeys WHERE isActive=1 ORDER BY createdAt LIMIT 1").fetchone()
        db.close()
        return row[0] if row else ""
    except Exception:
        return ""

def _call_llm(system: str, user: str, max_tokens: int = 280) -> str:
    """Call 9router LLM with fallback chain. Returns text or empty string on failure."""
    import requests
    key = _get_llm_key()
    
    for model in LLM_MODELS:
        try:
            r = requests.post(
                f"{LLM_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user",   "content": user},
                    ],
                    "max_tokens": max_tokens,
                    "temperature": 0.9,
                    "stream": False,
                },
                timeout=15,
            )
            if r.status_code == 200:
                resp = r.json()
                if resp.get("choices") and resp["choices"][0]["message"]["content"].strip():
                    return resp["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"LLM [{model}] failed: {e}, trying next...")
            continue
    
    print("All LLM models failed, returning empty")
    return ""


def draft_tweet(research: dict) -> dict:
    """Generate tweet English + source dari hasil research. LLM-first, fallback template."""
    topic = research["topic"]
    raw   = research.get("raw", "")[:800]

    # ── Coba LLM dulu ──────────────────────────────────────────
    system = (
        "You are a sharp, opinionated voice on X (Twitter). "
        "Write ONE standalone tweet in English — no preamble, no hashtags, no emoji. "
        "Max 240 chars. Be direct, opinionated, and substantive. "
        "End with a real source URL relevant to the topic (use coindesk/bloomberg/wsj/techcrunch/arxiv as appropriate)."
    )
    user = f"Topic: {topic}\n\nContext:\n{raw}\n\nWrite the tweet now:"

    llm_text = _call_llm(system, user, max_tokens=320)
    if llm_text and 80 < len(llm_text) < 320:
        # Extract source dari LLM output atau pakai fallback source
        source = None
        for word in llm_text.split():
            if word.startswith("http"):
                source = word.rstrip(".,)")
                break
        print(f"LLM draft OK ({len(llm_text)} chars)")
        return {"text": llm_text[:280], "source": source, "length": len(llm_text), "topic": topic}

    print("LLM draft failed, using template fallback")

    # ── Template fallback ───────────────────────────────────────
    if random.random() < 0.2:
        short_templates = [
            f"Most people are completely wrong about {topic}.",
            f"{topic} isn't bullish. It's positioning.",
            f"The hype around {topic} is louder than the fundamentals.",
            f"Retail buys {topic}. Smart money sells volatility.",
        ]
        text = random.choice(short_templates)
        return {"text": text, "source": None, "length": len(text), "topic": topic}

    hooks = [
        f"Most people are misreading {topic}.",
        f"The market narrative on {topic} is broken.",
        f"Everyone is bullish on {topic}. That's the problem.",
        f"The real story behind {topic} isn't what Twitter thinks.",
    ]
    bodies = [
        "On-chain data tells a very different story than the headlines.",
        "Liquidity flow matters more than sentiment.",
        "Follow positioning, not engagement metrics.",
        "Narratives move first. Fundamentals follow later.",
    ]
    sources = [
        "https://www.coindesk.com",
        "https://thedefiant.io",
        "https://dune.com",
    ]
    text = f"{random.choice(hooks)} {random.choice(bodies)}"[:240]
    source = random.choice(sources)
    full = f"{text}\n\nSource: {source}"
    return {"text": full, "source": source, "length": len(full), "topic": topic}

# ── Generate image ──────────────────────────────────────────────
# Fallback chain providers

def gen_cf_workers_ai(prompt: str, save_path: str) -> bool:
    """Provider 1: Cloudflare Workers AI (Flux-1-schnell) — rotate 23 accounts."""
    try:
        import sqlite3, requests, base64

        conn = sqlite3.connect(os.environ.get("ROUTER_DB_PATH", os.path.expanduser("~/.9router/db/data.sqlite")))
        rows = conn.execute(
            "SELECT name, data FROM providerConnections WHERE isActive=1 AND provider='cloudflare-ai' ORDER BY RANDOM() LIMIT 3"
        ).fetchall()
        conn.close()

        for acct_name, data_json in rows:
            try:
                d = json.loads(data_json)
                token    = d.get("apiKey", "")
                acc_id   = d.get("providerSpecificData", {}).get("accountId", "")
                if not token or not acc_id:
                    continue

                r = requests.post(
                    f"https://api.cloudflare.com/client/v4/accounts/{acc_id}"
                    "/ai/run/@cf/black-forest-labs/flux-1-schnell",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"prompt": prompt, "num_steps": 8, "seed": random.randint(1, 999999)},
                    timeout=40,
                )
                if r.status_code == 200:
                    img_b64 = r.json().get("result", {}).get("image", "")
                    if img_b64:
                        with open(save_path, "wb") as f:
                            f.write(base64.b64decode(img_b64))
                        sz = os.path.getsize(save_path) // 1024
                        print(f"CF Flux OK [{acct_name}]: {sz}KB")
                        return True
                print(f"CF Flux [{acct_name}]: HTTP {r.status_code}")
            except Exception as e:
                print(f"CF Flux [{acct_name}]: {e}")
                continue

        return False
    except Exception as e:
        print(f"CF Flux ERROR: {e}")
        return False


def gen_pollinations(prompt: str, save_path: str) -> bool:
    """Provider 2: Pollinations AI (flux, free, no auth)."""
    try:
        import requests
        from urllib.parse import quote

        url = (
            f"https://image.pollinations.ai/prompt/{quote(prompt)}"
            f"?width=1024&height=1024&nologo=true&seed={random.randint(1,999999)}"
            f"&model=flux"
        )
        r = requests.get(url, timeout=60)
        if r.status_code == 200 and len(r.content) > 1000:
            with open(save_path, "wb") as f:
                f.write(r.content)
            sz = os.path.getsize(save_path) // 1024
            print(f"Pollinations AI OK: {save_path} ({sz}KB)")
            return True
        else:
            print(f"Pollinations AI FAIL: HTTP {r.status_code}, size {len(r.content)}")
            return False
    except Exception as e:
        print(f"Pollinations AI ERROR: {e}")
        return False


def gen_image_hermes(prompt: str, save_path: str) -> bool:
    """Provider 3: Hermes image_gen tool (FAL/OpenAI)."""
    try:
        # Use execute_code or subprocess to call hermes image_gen
        # This is a last resort fallback
        print("Hermes image_gen fallback invoked (not implemented in cron mode)")
        return False
    except Exception as e:
        print(f"Hermes image_gen ERROR: {e}")
        return False


IMAGE_PROVIDERS = [
    ("CF Workers AI", gen_cf_workers_ai),
    ("Pollinations AI", gen_pollinations),
    ("Hermes Tool", gen_image_hermes),
]


def generate_image(prompt: str, save_path: str) -> tuple:
    """Try each provider in order. Returns (success: bool, provider: str)."""
    for name, fn in IMAGE_PROVIDERS:
        print(f"Image provider: {name} ...")
        if fn(prompt, save_path):
            return True, name
        print(f"  -> {name} failed, trying next...")
    # All failed
    return False, None


# ── Post to X ───────────────────────────────────────────────────
def post_x(text: str, image_path: str = None) -> tuple:
    """Post tweet via Playwright browser."""
    try:
        from x_stealth_browser import post_tweet
        try:
            from x_stealth_browser import set_default_browser_type
            set_default_browser_type("firefox")
        except ImportError:
            pass
        ok, msg = post_tweet(text, image_path=image_path, headless=True)
        return ok, msg
    except Exception as e:
        return False, str(e)


# ── Random delay (3-15 min) ─────────────────────────────────
DELAY_MIN = 180
DELAY_MAX = 900

def apply_delay():
    delay = random.randint(DELAY_MIN, DELAY_MAX)
    print(f"Delay {delay // 60}m{delay % 60}s...")
    time.sleep(delay)


# ── Main ────────────────────────────────────────────────────────
def main():
    # Time gate: 06:00-23:00 WIB
    os.environ["TZ"] = "Asia/Jakarta"
    time.tzset()
    h = int(time.strftime("%H"))
    if h < 6 or h >= 23:
        print(f"Outside 06:00-23:00 WIB (current: {h:02d}:{time.strftime('%M')}) exiting.")
        sys.exit(0)

    # Time gate: 06:00-23:00 WIB
    os.environ["TZ"] = "Asia/Jakarta"
    time.tzset()
    h = int(time.strftime("%H"))
    if h < 6 or h >= 23:
        # Silent exit outside hours
        sys.exit(0)

    start_ts = time.strftime("%Y-%m-%d %H:%M:%S")
    end_ts = None
    topic = ""
    tweet_len = 0
    tweet_source = "LLM"
    image_provider = "None"
    post_status = "❌ Failed"
    post_url = ""

    try:
        # 1. Research
        research = research_topic()
        if research.get("error"):
            raise Exception(f"Research error: {research['error']}")
        topic = research.get("topic", "")

        # 2. Draft tweet
        tweet = draft_tweet(research)
        tweet_len = tweet["length"]
        if "fallback" in tweet:
            tweet_source = "Template fallback"

        # 3. Generate image
        topic_lower = tweet["topic"].lower()
        tweet_text  = tweet["text"][:120]

        vis_system = (
            "You are a prompt engineer for Stable Diffusion XL. "
            "Convert the tweet topic into a cinematic image prompt. "
            "Output ONLY the image prompt (max 120 chars). "
            "Format: [subject], [style], [mood], [lighting]. No hashtags, no explanations."
        )
        vis_user = f"Tweet topic: {tweet['topic']}\nTweet: {tweet_text}\n\nImage prompt:"
        visual_prompt = _call_llm(vis_system, vis_user, max_tokens=80)

        if not visual_prompt or len(visual_prompt) < 10:
            if any(k in topic_lower for k in ["ai", "llm", "model", "agent", "openai", "nvidia"]):
                visual_prompt = f"abstract AI neural network glowing digital brain, dark tech atmosphere, cinematic 4K"
            elif any(k in topic_lower for k in ["bitcoin", "crypto", "eth", "defi", "solana", "blockchain"]):
                visual_prompt = f"abstract cryptocurrency market chart volatility, dark trading floor, neon blue cinematic"
            elif any(k in topic_lower for k in ["rate", "fed", "interest", "inflation", "dollar", "macro"]):
                visual_prompt = f"wall street trading floor dim moody, economic data screens, cinematic photorealistic"
            elif any(k in topic_lower for k in ["startup", "layoff", "burnout", "founder", "vc", "funding"]):
                visual_prompt = f"empty startup office late night, single person working, moody cinematic lighting"
            else:
                visual_prompt = f"abstract {tweet['topic']} concept art, dark cinematic moody, photorealistic 4K"

        img_path = "/tmp/auto_tweet_img.png"
        img_ok, img_provider = generate_image(visual_prompt, img_path)
        if img_ok:
            image_provider = img_provider
        else:
            img_path = None

        # 4. Post to X
        ok, msg = post_x(tweet["text"], image_path=img_path)
        if ok:
            post_status = "✅ Posted"
            post_url = msg  # URL from post_tweet
        else:
            if img_path:
                ok, msg = post_x(tweet["text"], image_path=None)
                if ok:
                    post_status = "✅ Posted (no image)"
                    post_url = msg

    except Exception as e:
        post_status = f"❌ Error: {str(e)[:40]}"

    end_ts = time.strftime("%Y-%m-%d %H:%M:%S")
    duration = int(time.time() - time.mktime(time.strptime(start_ts, "%Y-%m-%d %H:%M:%S")))

    # Compact box output
    print("```")
    print("🚀 X AUTO POST")
    print("━" * 48)
    print(f"🕐 Start   : {start_ts}")
    print(f"🕑 End     : {end_ts} ({duration}s)")
    print(f"📝 Topic   : {topic}")
    print(f"💬 Tweet   : {tweet_len} chars ({tweet_source})")
    print(f"🖼️  Image   : {image_provider}")
    print(f"📤 Status  : {post_status}")
    if post_url:
        print(f"🔗 URL     : {post_url}")
    print("━" * 48)
    print("```")


if __name__ == "__main__":
    main()
