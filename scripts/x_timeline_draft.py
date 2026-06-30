#!/usr/bin/env python3
"""
X Timeline -> AUTO QUOTE TWEET (from @mhucex)
For: @mhucex
Scope: For You timeline, skip crypto & geo-tag Indonesia
Action: Post quote tweets directly using @mhucex session
Interval: Every 30 minutes
Uses: x_stealth_browser.py (CloakBrowser with fresh cookies)
"""
import json
import time
import random
import re
import sys
import os
from datetime import datetime
from pathlib import Path

# Import stealth browser functions
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from x_stealth_browser import (
    post_tweet,
    get_tweet_views_detail,
    get_timeline_tweets,
    search_tweets,
    check_cookie_health,
)

# Browser type for anti-detection: 'chromium', 'firefox', 'webkit'
# Firefox recommended for X — different TLS/canvas fingerprint
BROWSER_TYPE = os.environ.get("BROWSER_TYPE", "firefox")

# Auto-post mode: post directly without draft approval
DRAFT_MODE = False

# Module-level run counters so the SIGALRM deadline handler can emit an
# ACCURATE per-run summary even when main() exits early via os._exit().
quote_count = 0
reply_count = 0

# Telegram config (for reporting only)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# LLM config for contextual quote tweets
# Use OmbrO combo (23 models, round-robin)
LLM_API_URL = os.environ.get("LLM_API_URL", "http://127.0.0.1:20128/v1")
LLM_API_KEY = None  # fetched from 9router DB
LLM_MODEL = os.environ.get("LLM_MODEL", "OmbrO")

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

# Fallback chain for LLM calls (max 3 models for speed)
LLM_MODELS = [
    "virtuals/google-gemini-3-5-flash",  # fast, stable
    "OmbrO",                               # local combo fallback
]

# Config
MAX_INTERACTIONS_PER_RUN = 1  # Total interactions per run - keep it 1 for stability
MAX_QUOTE_TWEETS_PER_RUN = 1  # Max quote tweets per run
MAX_REPLIES_PER_RUN = 0       # No replies (quote-only mode)
MIN_VIEWS_THRESHOLD = 50000    # Minimum view count to engage (50k)
ENABLE_VIEW_SCRAPE = False     # DISABLED: terlalu lambat (buka browser baru per tweet), boros 20-30s/tweet

# Output format functions for box header style
import unicodedata

def wcwidth(text):
    """Calculate visible width of text (emoji = 2, ascii = 1)"""
    return sum(2 if unicodedata.east_asian_width(c) in ('W','F') else 1 for c in text)

def ljust_vis(text, width):
    """Left-justify with visual width awareness"""
    v = wcwidth(text)
    return text + " " * (width - v) if v < width else text

def box_header(title, job_id, timestamp, inner_width=80):
    """Generate box header with title, job_id, timestamp"""
    lines = []
    top = "╔" + "═" * (inner_width + 2) + "═╗"
    mid = "╠" + "═" * (inner_width + 2) + "═╣"
    bot = "╚" + "═" * (inner_width + 2) + "═╝"
    # Title line
    line1 = f"║ {ljust_vis(title, inner_width)} ║"
    # Job ID and timestamp
    right_part = f"│  {job_id}  │  {timestamp}  "
    right_width = wcwidth(right_part)
    padding = inner_width - right_width - 2
    line2 = f"║{' ' * (padding + 1)}{right_part}║"
    lines.append(top)
    lines.append(line1)
    lines.append(mid)
    lines.append(line2)
    return lines, mid, bot

def box_footer(bot):
    return [bot]

def box_row(content, inner_width, mid_line=None):
    """Generate a row in the box"""
    return f"║ {ljust_vis(content, inner_width)} ║"

def box_separator(mid_line):
    return mid_line

# Indonesian detection
INDONESIAN_PATTERNS = [
    r'\b(aku|saya|kamu|lu|lo|gue|gua|dia|mereka|kita|kami)\b',
    r'\b(Indonesia|indonesia|Jakarta|Surabaya|Bandung|Bali|Medan|Jogja)\b',
    r'\b(nasi padang|sate|rendang|indomie|soto|bakso|warteg)\b',
    r'\b(anjir|bulol|baper|cewekcowok|receh|garing)\b',
    r'#\w*(Indonesia|indonesia|Jakarta|Bandung|Surabaya)\w*',
]
INDONESIAN_REGEX = re.compile('|'.join(INDONESIAN_PATTERNS), re.IGNORECASE)

# Crypto detection - skip these
CRYPTO_PATTERNS = [
    r'\$[A-Z]{2,10}',
    r'\b(Bitcoin|BTC|ETH|Ethereum|Solana|crypto|defi|nft|airdrop|trading coin)\b',
    r'\b(Whale|bullish|bearish|hold|dump|pump|token|blockchain|web3|dex)\b',
    r'\b(metamask|wallet|private key|seed phrase|gas fee|RPC)\b',
    r'\b(satoshi|halving|fork|masternode|staking|yield farm)\b',
    r'\b(XRP|Ripple|Cardano|ADA|Doge|Dogecoin|Shiba|Inu)\b',
]
CRYPTO_REGEX = re.compile('|'.join(CRYPTO_PATTERNS), re.IGNORECASE)

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", file=sys.stderr)

def is_indonesian(text):
    """Check if text is Indonesian (skip these)"""
    if not text:
        return False
    matches = INDONESIAN_REGEX.findall(text)
    return len(matches) >= 2

def is_crypto(text):
    """Check if text is crypto-related (skip these)"""
    if not text:
        return False
    return bool(CRYPTO_REGEX.search(text))

def detect_language(text):
    """Detect language of text - returns lang code"""
    if not text:
        return "en"
    
    # Korean (Hangul) — check first, no overlap with CJK Han
    kr_chars = len(re.findall(r'[\uac00-\ud7af]', text))
    if kr_chars > 3:
        return "ko"

    # Japanese — REQUIRE kana (hiragana/katakana). Kanji alone is ambiguous with
    # Chinese, so don't count Han here or Chinese tweets misdetect as Japanese.
    kana_chars = len(re.findall(r'[\u3040-\u309f\u30a0-\u30ff]', text))
    if kana_chars > 2:
        return "ja"

    # Chinese (Han characters, no kana present)
    cn_chars = len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf]', text))
    if cn_chars > 3:
        return "zh"
    
    # Arabic
    ar_chars = len(re.findall(r'[\u0600-\u06ff]', text))
    if ar_chars > 5:
        return "ar"
    
    # Spanish
    spanish_patterns = [r'\b(que|como|esta|pero|para|con|son|los|las|del|una|por|está|tiene|hace|este|esta)\b']
    if re.search('|'.join(spanish_patterns), text.lower()) and len(text.split()) < 50:
        spanish_words = len(re.findall('|'.join(spanish_patterns), text.lower()))
        if spanish_words >= 2:
            return "es"
    
    # French
    french_patterns = [r'\b(les|des|une|pour|est|que|dans|ce|avec|pas|sur|plus|par|son|ses|tout|elle)\b']
    french_words = len(re.findall('|'.join(french_patterns), text.lower()))
    if french_words >= 2:
        return "fr"
    
    # German
    german_patterns = [r'\b(dass|ist|ein|eine|nicht|als|auch|es|an|werden|aus|noch|nur|bei|hat|oder)\b']
    german_words = len(re.findall('|'.join(german_patterns), text.lower()))
    if german_words >= 2:
        return "de"
    
    # Portuguese
    pt_patterns = [r'\b(o|que|é|um|uma|para|com|não|as|os|mas|em|seu|sua|muito|já|tudo)\b']
    pt_words = len(re.findall('|'.join(pt_patterns), text.lower()))
    if pt_words >= 2:
        return "pt"
    
    # Default to English
    return "en"

def generate_reply_draft(text, category, lang="en"):
    """Generate reply draft in the same language as the tweet (template-based, fast)"""
    templates = {
        "en": {
            "news": ["the framing here matters more than the headline", "this is less surprising than people are making it", "the context they left out changes everything", "watch what happens in the next 48 hours"],
            "sports": ["the result was decided long before today", "the stat that actually matters isn't the score", "people keep misreading what this team is doing", "this changes the dynamic for the whole season"],
            "tech": ["the launch is the easy part, retention is where it dies", "this solves a problem most people don't actually have", "the real question is who controls the data", "the gap between the demo and the product is still wide"],
            "funny": ["the fact that this needs explaining is the funniest part", "the comments will be worse than the thing itself", "whoever made this decision has a lot to answer for", "this is the kind of thing that ends careers"],
            "question": ["the answer exists but nobody wants to say it", "the framing of the question already contains the answer", "the real issue is why this keeps coming up", "most people already know the answer and are avoiding it"],
            "general": ["the actual story here is being ignored", "this changes something people haven't thought about yet", "most people will miss what this actually implies", "the downstream effects of this are underestimated"],
        },
        "ja": {
            "news": ["これは大きい 🐸", "注目に値する 📰", "シェアしとく 📢", "ブックマーク確定 📌"],
            "sports": ["最高だ ⚽", "レジェンド 🐐", "何度も見返す 🔄", "鳥肌たった 🏆"],
            "tech": ["未来きた 🤖", "思わず見た 🖥️", "革新的 ✨", "衝撃的 🚀"],
            "funny": ["吹いた 💀", "頭がバグった 🧠", "夜中に笑った 😂", "人間ってこういうことある 😂"],
            "question": ["いい質問！ 👆", "実は私も気になってた 🤔", "誰かやっと聞いた 💯", "正直私も知りたい 👀"],
            "general": ["刺さる 🎯", "こういうの需要あり ✨", "今日必要だった 💯", "その通り 💯", "正しい 🙌"],
        },
        "ko": {
            "news": ["이거 크다 🐸", "더 많은 사람이 보면 좋겠다 📰", "주목받을 자격 있다 👀", "공유한다 📢"],
            "sports": ["최고야 ⚽", "레전드 🐐", "재탕 가치 무한 🔄", "우리가 사랑하는 게임 🏆"],
            "tech": ["미래 왔어 🤖", "못 지나쳐 🖥️", "혁신적이다 ✨", "우리 지금 미래에 살고 있어 🚀"],
            "funny": ["웃기네 💀", "뇌가 뻗었어 🧠", "새벽에 웃었다 😂", "인간 참 😅"],
            "question": ["좋은 질문이야! 👆", "나도 사실 궁금했어 🤔", "누군가 물어봤어 💯", "솔직히 나도 궁금해 👀"],
            "general": ["다르다 🎯", "이것만은 해야해 ✨", "오늘 필요했어 💯", "맞아 💯", "옳다 🙌"],
        },
        "zh": {
            "news": ["这很重大 🐸", "希望更多人看到 📰", "值得关注 👀", "转发 📢"],
            "sports": ["太精彩了 ⚽", "传奇 🐐", "值得反复看 🔄", "这就是我们爱这项运动 🏆"],
            "tech": ["未来已来 🤖", "忍不住看 🖥️", "创新 ✨", "我们活在未来 🚀"],
            "funny": ["笑死 💀", "脑子宕机 🧠", "半夜笑出声 😂", "人类迷惑 😅"],
            "question": ["好问题！ 👆", "我也正好在想 🤔", "终于有人问了 💯", "说实话我也好奇 👀"],
            "general": ["戳心了 🎯", "拿这个当信号 ✨", "今天正需要 💯", "确实 💯", "说得好 🙌"],
        },
        "es": {
            "news": ["esto es enorme 🐸", "necesitamos más gente cubriendo esto 📰", "merece más atención 👀", "compartiendo con todos 📢"],
            "sports": ["escenas absolutas ⚽", "comportamiento GOAT 🐐", "valor de repetición infinito 🔄", "esto es por lo que amamos el juego 🏆"],
            "tech": ["el futuro ya llegó 🤖", "no puedo pasar de esto 🖥️", "innovador ✨", "vivimos en el futuro 🚀"],
            "funny": ["estoy gritando 💀", "esto rompió mi cerebro 🧠", "yo riéndome a las 3am 😂", "el estado absoluto de la humanidad 🤡"],
            "question": ["¡gran pregunta! 👆", "esto es exactamente lo que pensaba 🤔", "alguien finalmente lo preguntó 💯", "honestamente curioso también 👀"],
            "general": ["esto llega diferente 🎯", "toma esto como señal ✨", "necesitaba esto hoy 💯", "exactamente 💯", "predica 🙌"],
        },
        "fr": {
            "news": ["c'est énorme 🐸", "il faut plus de gens pour couvrir ça 📰", "mérite plus d'attention 👀", "je partage avec tout le monde 📢"],
            "sports": ["scènes absolues ⚽", "comportement GOAT 🐐", "valeur de rewatch infinie 🔄", "c'est pour ça qu'on aime ce jeu 🏆"],
            "tech": ["le futur est là 🤖", "je ne peux pas ignorer 🖥️", "innovant ✨", "on vit dans le futur 🚀"],
            "funny": ["je crie 💀", "ça a cassé mon cerveau 🧠", "moi qui ris à 3h du mat' 😂", "l'état absolu de l'humanité 🤡"],
            "question": ["grande question! 👆", "c'est exactement ce que je pensais 🤔", "quelqu'un afinally posé la question 💯", "honnêtement curieux aussi 👀"],
            "general": ["ça tape différemment 🎯", "prends ça comme un signe ✨", "j'avais besoin de ça aujourd'hui 💯", "exactement 💯", "prêche 🙌"],
        },
        "de": {
            "news": ["das ist riesig 🐸", "wir brauchen mehr Leute, die darüber berichten 📰", "verdient mehr Aufmerksamkeit 👀", "teile das mit allen 📢"],
            "sports": ["absolute Szenen ⚽", "GOAT-Verhalten 🐐", "Replay-Wert: unendlich 🔄", "deshalb lieben wir das Spiel 🏆"],
            "tech": ["die Zukunft ist da 🤖", "kann man nicht ignorieren 🖥️", "innovativ ✨", "wir leben in der Zukunft 🚀"],
            "funny": ["ich schreie 💀", "das hat mein Gehirn gebrochen 🧠", "ich lache um 3 Uhr nachts 😂", "der absolute Zustand der Menschheit 🤡"],
            "question": ["große Frage! 👆", "das denke ich auch gerade 🤔", "jemand hat es endlich gefragt 💯", "ehrlich gesagt neugierig 👀"],
            "general": ["das sitzt anders 🎯", "nimm das als Zeichen ✨", "brauchte ich heute 💯", "genau 💯", "predige 🙌"],
        },
        "pt": {
            "news": ["isso é enorme 🐸", "precisamos de mais pessoas cobrindo isso 📰", "merece mais atenção 👀", "compartilhando com todos 📢"],
            "sports": ["cenas absolutas ⚽", "comportamento GOAT 🐐", "valor de replay infinito 🔄", "é por isso que amamos o jogo 🏆"],
            "tech": ["o futuro chegou 🤖", "não dá pra ignorar 🖥️", "inovador ✨", "vivemos no futuro 🚀"],
            "funny": ["estou gritando 💀", "isso quebrou meu cérebro 🧠", "eu rindo às 3am 😂", "o estado absoluto da humanidade 🤡"],
            "question": ["ótima pergunta! 👆", "isso é exatamente o que eu estava pensando 🤔", "alguém finalmente perguntou 💯", "honestamente curioso também 👀"],
            "general": ["isso atinge diferente 🎯", "pegou isso como sinal ✨", "precisava disso hoje 💯", "exatamente 💯", "pregando 🙌"],
        },
        "ar": {
            "news": ["هذا كبير 🐸", "نحتاج لمزيد من التغطية 📰", "يستحق المزيد من الاهتمام 👀", "مشاركة مع الجميع 📢"],
            "sports": ["مشاهد رائعة ⚽", "سلوك GOAT 🐐", "قيمة إعادة المشاهدة: لا نهائية 🔄", "هذا ما نحب في اللعبة 🏆"],
            "tech": ["المستقبل هنا 🤖", "لا يمكنني تجاهل هذا 🖥️", "مبتكر ✨", "نحن نعيش في المستقبل 🚀"],
            "funny": ["أصيح 💀", "هذا كسر عقلي 🧠", "أضحك في الثالثة فجراً 😂", "حالة البشرية المطلقة 🤡"],
            "question": ["سؤال رائع! 👆", "هذا بالضبط ما كنت أفكر فيه 🤔", "أخيراً سأل شخص ما 💯", "بصراحة أنا أيضاً فضولي 👀"],
            "general": ["يضرب بشكل مختلف 🎯", "خذ هذا كإشارة ✨", "كنت بحاجة لهذا اليوم 💯", "تماماً صحيح 💯", "قولت الصح 🙌"],
        },
    }

    lang_templates = templates.get(lang, templates["en"])
    selected = lang_templates.get(category, lang_templates["general"])
    draft = random.choice(selected)

    text_lower = text.lower()
    if any(x in text_lower for x in ['shocking', 'wow', 'unbelievable', 'insane', '信じられない', '驚', '厉害', '최고', 'increíble']):
        draft = f"🤯 {draft}"
    elif any(x in text_lower for x in ['sad', 'cry', ' rip', 'passed away', '死了', '최애', 'triste']):
        draft = f"❤️ {draft}"
    elif any(x in text_lower for x in ['win', 'achievement', 'success', 'congrats', '勝', '축하', 'felicidades']):
        draft = f"🎉 {draft}"

    return draft


def _analyze_image(image_url, lang="en"):
    """Ask a vision-capable model what's IN the tweet image, so the quote can
    react to the actual visual content (charts, scoreboards, photos), not just
    the text. Returns a short factual description, or '' on any failure.
    Many JP/sports/entertainment tweets are image-first — text alone misses the point."""
    if not image_url:
        return ""
    import requests as _rq
    from json import JSONDecoder as _JD
    api_key = _get_llm_key()
    # Vision-capable models verified working on the gateway (Jun 2026).
    vision_models = ["tokenrouter/anthropic/claude-sonnet-4.6", "tokenrouter/openai/gpt-5.4", "OmbrO"]
    sys_prompt = ("Describe what is actually shown in this image in ONE concise factual sentence "
                  "(max 25 words). Focus on concrete content: who/what, any visible numbers, text, "
                  "charts, scores, or actions. No interpretation, no fluff.")
    for model in vision_models:
        try:
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": sys_prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ]}],
                "max_tokens": 80, "temperature": 0.4, "stream": False,
            }
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            r = _rq.post(f"{LLM_API_URL}/chat/completions", headers=headers, json=payload, timeout=12)
            if r.status_code == 200:
                obj, _ = _JD().raw_decode(r.text)
                if obj.get('choices') and obj['choices'][0].get('message'):
                    desc = (obj['choices'][0]['message'].get('content') or '').strip()
                    # Reject models that refuse / can't see images
                    low = desc.lower()
                    if desc and len(desc) > 12 and "can't view" not in low and "cannot view" not in low and "i'm sorry" not in low:
                        print(f"  🖼️ Image analyzed [{model.split('/')[-1]}]: {desc[:80]}")
                        return desc[:200]
        except Exception as e:
            print(f"  vision [{model}] failed: {e}")
            continue
    return ""

def generate_contextual_quote(text, lang="en", author="", image_url=""):
    """Generate contextual reply/quote using local LLM - CHATTY/OPINION style.
    If the tweet has an image, analyze it FIRST (vision) and fold the visual
    content into the prompt so the quote reacts to what's actually shown."""
    text_preview = text[:200].replace('\n', ' ').strip()

    # Vision pre-step: see the image before writing the comment.
    image_desc = _analyze_image(image_url, lang) if image_url else ""

    lang_prompts = {
        "en": f"You are a sharp, opinionated person on X with strong takes. Read the tweet and reply with 1-2 punchy sentences (max 200 chars). State a clear take, push back, or add real context — not just agreeing or hyping. Vary your style: sometimes ask a rhetorical question, sometimes state a counterintuitive fact, sometimes call out the unspoken implication. Never repeat the same phrasing pattern. No filler phrases ('this hits', 'needed this', 'take this as a sign', 'the story here', 'people don't realize', 'the framing matters', 'the context left out'). No emoji unless it adds meaning. No hashtags. Output ONLY the reply.\n\nTweet by @{author}: {text_preview}",
        "ja": f"あなたはXで率直な意見を持つ人。ツイートを読んで、断定的な1文（120字以内）で返信する。明確な立場、反論、または本質的な補足を述べる。「すごい」「共感」などの空虚な同意は禁止。絵文字は意味がある場合のみ使う。ハッシュタグ禁止。返信テキストのみ出力。\n例: ツイート: '夢の会社に落ちた' -> 'その会社に落ちたことが、半年後の後悔を防いだ可能性がある'\n例: ツイート: '新型iPhone発表' -> '発表のタイミングは製品より株価のためにデザインされている'\n\n@{author}の投稿: {text_preview}",
        "ko": f"당신은 X에서 직설적인 사람. 트윗을 읽고 단호한 한 문장(120자 이내)으로 답할 것. 명확한 입장, 반론, 또는 진짜 인사이트를 추가할 것. 공허한 동의·칭찬 금지. 의미 있을 때만 이모지 사용. 해시태그 금지. 답변 텍스트만 출력.\n예: 트윗: '드림 회사에서 거절당했다' -> '그 회사에 거절당한 게 6개월치 후회를 막았을 수도 있어'\n예: 트윗: '새 아이폰 발표' -> '발표 타이밍은 제품보다 주가를 위한 거야'\n\n@{author}님의 트윗: {text_preview}",
        "zh": f"你是X上有观点的人。读推文，用一句有力的话回复（120字以内）。说清楚立场、反驳或加入真实背景——不只是赞同或炒热。不用'这很触动我'之类的空话。有意义时才用表情，不加标签。只输出回复本身。\n例: 推文: '被梦想公司拒了' -> '那家公司拒了你，可能帮你省了六个月的后悔'\n例: 推文: '苹果发布新品' -> '这个发布时机是为股价设计的，不是为产品'\n\n@{author}的推文: {text_preview}",
        "es": f"Eres una persona directa y con opiniones en X. Lee el tweet y responde con 1 frase asertiva (máx 120 caracteres). Da una postura clara, contradice, o agrega contexto real — no solo validar ni halagar. Sin frases vacías. Sin hashtags. Solo el texto de la respuesta.\nEjemplo: tweet: 'me rechazaron del trabajo soñado' -> 'ese rechazo probablemente te ahorró seis meses de arrepentimiento'\nEjemplo: tweet: 'Apple lanza nuevo iPhone' -> 'el timing del anuncio está diseñado para mover el precio de la acción, no para lanzar el producto'\n\nTweet de @{author}: {text_preview}",
        "fr": f"Tu es quelqu'un de direct et avec des opinions sur X. Lis le tweet et réponds avec 1 phrase assertive (max 120 caractères). Prends une position claire, contredis, ou apporte un vrai contexte — pas juste valider ou féliciter. Pas de phrases vides. Pas de hashtags. Juste le texte de la réponse.\nExemple: tweet: 'refusé à mon job de rêve' -> 'ce refus t'a probablement évité six mois de regrets'\nExemple: tweet: 'Apple lance un nouveau iPhone' -> 'le timing de l'annonce est fait pour bouger le cours de l'action, pas pour livrer un produit'\n\nTweet de @{author}: {text_preview}",
        "de": f"Du bist eine direkte Person mit klaren Meinungen auf X. Lies den Tweet und antworte mit 1 assertiven Satz (max 120 Zeichen). Nimm eine klare Position ein, widersprich oder ergänze echten Kontext — nicht einfach bestätigen oder loben. Keine leeren Floskeln. Keine Hashtags. Nur der Antworttext.\nBeispiel: Tweet: 'gerade von meinem Traumjob abgelehnt' -> 'diese Absage hat dir wahrscheinlich sechs Monate Reue erspart'\nBeispiel: Tweet: 'Apple kündigt neues iPhone an' -> 'das Timing der Ankündigung ist für den Aktienkurs gedacht, nicht für das Produkt'\n\nTweet von @{author}: {text_preview}",
        "pt": f"Você é uma pessoa direta e com opiniões no X. Leia o tweet e responda com 1 frase assertiva (máx 120 caracteres). Dê uma posição clara, contradiga, ou adicione contexto real — não apenas concordar ou elogiar. Sem frases vazias. Sem hashtags. Apenas o texto da resposta.\nExemplo: tweet: 'fui rejeitado do emprego dos sonhos' -> 'essa rejeição provavelmente te poupou seis meses de arrependimento'\nExemplo: tweet: 'Apple lança novo iPhone' -> 'o timing do anúncio é feito para mover o preço da ação, não para entregar o produto'\n\nTweet de @{author}: {text_preview}",
        "ar": f"أنت شخص مباشر وذو رأي على X. اقرأ التغريدة ورد بجملة واحدة حازمة (أقصى 120 حرفاً). أعطِ موقفاً واضحاً، ناقض، أو أضف سياقاً حقيقياً — لا مجرد موافقة أو مديح. بدون عبارات فارغة. بدون هاشتاق. فقط نص الرد.\nمثال: تغريدة: 'رفضوني من شغل أحلامي' -> 'هذا الرفض على الأرجح أنقذك من ستة أشهر من الندم'\nمثال: تغريدة: 'أبل تطلق آيفون جديد' -> 'توقيت الإعلان مصمم لتحريك سعر السهم لا لإطلاق المنتج'\n\nتغريدة @{author}: {text_preview}",
    }
    
    
    import requests, re as _re
    api_key = _get_llm_key()
    if not api_key:
        print("⚠️ No API key available")
        return None
    
    # Try each model in fallback chain
    # Fold the vision result into the user message so the text model reacts to
    # what the image SHOWS, not just the caption.
    _img_block = f"\n\nThe tweet includes an image showing: {image_desc}" if image_desc else ""
    user_msg = (f"Reply to this tweet with 1-2 punchy sentences (max 200 chars). "
                f"No filler. No hashtags.\n\nTweet:\n{text_preview}{_img_block}")
    for model in LLM_MODELS:
        try:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": lang_prompts.get(lang, lang_prompts["en"])},
                    {"role": "user", "content": user_msg}
                ],
                "max_tokens": 200,
                "temperature": 0.95,
                "stream": False
            }
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            
            r = requests.post(f"{LLM_API_URL}/chat/completions", headers=headers, json=payload, timeout=4)
            
            if r.status_code == 200:
                obj = r.json()
                if obj.get('choices') and obj['choices'][0].get('message'):
                    content = obj['choices'][0]['message'].get('content', '').strip()
                    content = _re.sub(r'<think>.*?</think>', '', content, flags=_re.DOTALL).strip()
                    content = content.strip().strip('"').strip("'").strip()
                    # Reject degenerate output: a quote caption must be substantive
                    # ("tegas dan berisi"). Count meaningful chars (drop URLs, @,
                    # whitespace, lone emoji). Short junk like "W" / "AI" — which is
                    # also the residue of a CJK unicode-drop — must NOT be posted.
                    meaningful = _re.sub(r'https?://\S+|@\w+|[\s\W_]+', '', content)
                    if content and len(meaningful) >= 8:
                        return content[:300]
                    print(f"  ⏭️ Rejected too-short/degenerate quote: {content!r}")
        except Exception as e:
            print(f"LLM [{model}] failed: {e}, trying next...")
            continue
    
    print("All LLM models failed for quote generation")
    return ""

CLICHES = [
    "this hits different", "we are so back", "this is huge", "game changer",
    "let that sink in", "the future is now", "we are living in the future",
    "this is the way", "no notes", "absolute cinema", "peak", "this is gold",
    "this deserves more attention", "needed this today", "take this as a sign",
]

def _strip_emojis(s, keep=1):
    """Keep at most `keep` emoji; drop the rest."""
    emoji_re = re.compile(
        "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\u2190-\u21FF\u2B00-\u2BFF]"
    )
    found = 0
    out = []
    for ch in s:
        if emoji_re.match(ch):
            found += 1
            if found <= keep:
                out.append(ch)
        else:
            out.append(ch)
    return "".join(out)

def sanitize_reply(text):
    """Clean LLM output to sound more human: drop clichés, cap emoji, trim."""
    if not text:
        return text
    t = text.strip().strip('"').strip("'").strip()
    # Drop wrapping quotes/labels the model sometimes adds
    t = re.sub(r'^(reply|quote|tweet)\s*[:\-]\s*', '', t, flags=re.IGNORECASE)
    # Cap emoji at 1 (often 0 reads more human)
    t = _strip_emojis(t, keep=1)
    # Collapse whitespace
    t = re.sub(r'\s+', ' ', t).strip()
    # Reject if it's basically a cliché
    low = t.lower()
    if any(c in low for c in CLICHES) and len(t) < 40:
        return ""
    # Reject assistant-identity / refusal leaks (LLM answering as itself, not as a tweet)
    LEAK_MARKERS = [
        "i'm claude", "i am claude", "claude code", "language model", "as an ai",
        "i can't post", "i cannot post", "i can't reply", "i cannot reply",
        "i don't have access", "i do not have access", "anthropic", "openai",
        "as a text-based", "i'm an ai", "i am an ai", "i'm just a", "happy to help",
        "i'm not able to", "i am not able to", "social media platform",
    ]
    if any(m in low for m in LEAK_MARKERS):
        return ""
    return t
def detect_category(text):
    """Detect tweet category for reply style"""
    text_lower = text.lower()
    
    if any(x in text_lower for x in ['news', 'breaking', 'report', 'announcement', '公式', ' news', 'noticia']):
        return "news"
    elif any(x in text_lower for x in ['sport', 'game', 'goal', 'win', 'score', 'player', 'team', 'match', '試合', '경기', 'partido']):
        return "sports"
    elif any(x in text_lower for x in ['ai', 'tech', 'app', 'software', 'startup', 'code', 'data', ' tech', '科技']):
        return "tech"
    elif any(x in text_lower for x in ['lol', 'haha', 'funny', 'joke', 'laugh', 'comedy', 'meme', '笑', '웃', 'jaja', 'kkk']):
        return "funny"
    elif any(x in text_lower for x in ['?', 'why', 'how', 'what', 'when', 'think', '为什么', '어떻게', 'por qué']):
        return "question"
    else:
        return "general"

def _print_draft_card(pending):
    """Print a Telegram-friendly draft card to stdout (cron delivers it to thread 2)."""
    action = pending.get("action", "?").upper()
    src = (pending.get("source_text") or "").strip().replace("\n", " ")
    if len(src) > 200:
        src = src[:200] + "…"
    draft = pending.get("draft_text", "")
    author = pending.get("author", "").split("\n")[0].strip()
    url = pending.get("url", "")
    # Normalize to clean tweet permalink: strip /photo/N, /analytics, query/fragment
    import re as _re
    m = _re.search(r"(https?://(?:x|twitter)\.com/[^/]+/status/\d+)", url)
    if m:
        url = m.group(1)
    lang = pending.get("lang", "?")
    lines = [
        "📝 *DRAFT @mhucex* — menunggu approval",
        "",
        f"🎯 Aksi: *{action}*  │  🌐 {lang}",
        f"👤 Sumber: {author}",
        f"🔗 {url}",
        "",
        f"💬 Tweet asli:",
        f"> {src}",
        "",
        f"✍️ Draft balasan:",
        f"> {draft}",
        "",
        "Balas *oke* untuk posting, atau *skip* untuk batalkan.",
    ]
    print("\n".join(lines))


def get_state():
    """Load state to avoid reprocessing same tweets"""
    state_file = "/tmp/x_timeline_draft_state.json"
    if Path(state_file).exists():
        with open(state_file) as f:
            return json.load(f)
    return {"processed_urls": [], "drafts": []}

def save_state(state):
    """Save state"""
    state_file = "/tmp/x_timeline_draft_state.json"
    with open(state_file, 'w') as f:
        json.dump(state, f)

def main():
    log("Starting X Timeline -> Auto Quote Tweet + Reply (@mhucex) [CloakBrowser]")
    
    state = get_state()
    processed = set(state.get("processed_urls", []))
    
    global quote_count, reply_count
    quote_count = 0
    reply_count = 0
    skipped_count = 0
    errors = []
    
    # Get timeline tweets (function creates own browser)
    log("Fetching For You timeline...")
    tweets = get_timeline_tweets(count=12, browser_type=BROWSER_TYPE)
    log(f"Fetched {len(tweets)} tweets from timeline")
    
    # Search fallback disabled for cron runtime safety (<120s watchdog)
    if False and len(tweets) < 10:
        log("Timeline sparse, searching for viral content...")
        search_results = search_tweets("viral", count=15, browser_type=BROWSER_TYPE)
        tweets.extend(search_results)
        log(f"Added {len(search_results)} search results")
    
    for tweet in tweets:
        if (quote_count + reply_count) >= MAX_INTERACTIONS_PER_RUN:
            break

        text = tweet.get('text', '')
        url = tweet.get('url', '')
        author = tweet.get('author', '')
        image_url = tweet.get('imageUrl', '') or tweet.get('image_url', '')

        if not text or not url or url in processed:
                continue

        # Skip centang kuning (verified organization / brand account)
        if tweet.get('goldVerified'):
                skipped_count += 1
                log(f"  🟡 Skip centang kuning (org): {text[:50]}...")
                continue

        # Normalize URL: strip /analytics, /photo/N, query params, etc.
        # These suffixes break post_tweet() navigation
        url = re.sub(r'(\.com/\w+/status/\d+)(?:/analytics|/photo/\d+).*', r'\1', url)

        # Filters
        if is_crypto(text):
                skipped_count += 1
                log(f"  ⏭️ Skipped crypto: {text[:50]}...")
                continue
        if is_indonesian(text):
                skipped_count += 1
                log(f"  ⏭️ Skipped Indonesian: {text[:50]}...")
                continue

        # View threshold check
        if ENABLE_VIEW_SCRAPE:
                views = get_tweet_views_detail(url, browser_type=BROWSER_TYPE)
                if views < MIN_VIEWS_THRESHOLD:
                    skipped_count += 1
                    log(f"  ⏭️ Skipped low views ({views:,}) < {MIN_VIEWS_THRESHOLD:,}: {text[:50]}...")
                    continue
                log(f"  ✅ Passed content filters ({views:,} views) - {text[:50]}...")
        else:
                log(f"  ✅ Passed content filters - {text[:50]}...")

        # Detect language
        lang = detect_language(text)

        # Generate contextual quote text using LLM (QUOTE-ONLY MODE)
        # Pass image_url so the LLM analyzes the tweet's image FIRST, then
        # writes a comment that reacts to the actual visual content.
        interaction_text = generate_contextual_quote(text, lang, author.split('@')[0] if '@' in author else author.split('\n')[0], image_url=image_url)

        # Skip if LLM failed (None = no fallback template)
        if not interaction_text:
                log(f"  ⏭️ Skipping — LLM failed to generate quote")
                continue

        # QUOTE-ONLY MODE - always quote, never reply
        action = "quote"

        # Respect quote limit
        if quote_count >= MAX_QUOTE_TWEETS_PER_RUN:
                break

        # --- DRAFT MODE: save candidate for approval, do NOT post ---
        if DRAFT_MODE:
                pending = {
                    "action": action,
                    "url": url,
                    "author": author,
                    "lang": lang,
                    "source_text": text[:280],
                    "draft_text": interaction_text,
                    "created_at": time.time(),
                    "job_id": "1eb1c96516fa",
                }
                with open(PENDING_FILE, "w") as f:
                    json.dump(pending, f)
                log(f"📝 DRAFT saved ({action}): {interaction_text}")
                processed.add(url)
                state["processed_urls"] = list(processed)[-100:]
                save_state(state)
                _print_draft_card(pending)
                return

        try:
                success = False
                if action == "quote":
                    log(f"Posting quote tweet ({lang}): @{author}: {text[:60]}...")
                    success, tweet_url = post_tweet(interaction_text, quote_url=url, browser_type=BROWSER_TYPE)
                    if success:
                        quote_count += 1
                        log(f"✅ Posted quote #{quote_count} -> {tweet_url}")
                else:
                    log(f"Posting reply ({lang}): @{author}: {text[:60]}...")
                    success, tweet_url = post_tweet(interaction_text, reply_to_url=url, browser_type=BROWSER_TYPE)
                    if success:
                        reply_count += 1
                        log(f"✅ Posted reply #{reply_count} -> {tweet_url}")

                if success:
                    time.sleep(2)  # Rate limit protection
                else:
                    errors.append(f"Failed to {action}: {url}")

        except Exception as e:
                log(f"Error posting {action}: {e}")
                errors.append(f"Error {action}: {e}")

        processed.add(url)

        # Small delay between interactions
        time.sleep(random.uniform(1, 2))

    # Report results
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    from box_helper import box
    box("🚀 TIMELINE DRAFT", {
        "🕐 Time    ": timestamp,
        "📥 Fetched ": str(len(tweets)),
        "🔁 Quotes  ": str(quote_count),
        "↩️  Replies ": str(reply_count),
        "⏭️  Skip    ": str(skipped_count),
        "❌ Errors  ": str(len(errors)),
    })
    
    if errors:
        for err in errors[:3]:
            print(f"  ❌ {err[:80]}")
    
    log(f"Done! Posted {quote_count} quotes, {reply_count} replies")
    # Fresh per-run summary line for the wrapper to parse (NOT stale state file).
    print(f"SUMMARY: {{\"quotes\": {quote_count}, \"replies\": {reply_count}}}", flush=True)
    
    # Save state with counters
    state["processed_urls"] = list(processed)[-100:]
    state["quotes"] = quote_count
    state["replies"] = reply_count
    state["last_run"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save_state(state)
    
    log("Done!")

if __name__ == "__main__":
    import signal
    _deadline = int(os.getenv("X_RUN_DEADLINE", "0"))
    if _deadline > 0:
        def _on_deadline(signum, frame):
            # Raising through Playwright's C driver is unreliable, and closing the
            # browser here can block until SIGKILL. Emit a fresh, ACCURATE summary
            # from the live counters, then force a clean exit. Exit code reflects
            # whether anything actually landed so the wrapper can't falsely report
            # "Posted" when the deadline hit mid-attempt with 0 posts.
            log(f"⏰ Deadline {_deadline}s reached — graceful clean exit")
            print(f"SUMMARY: {{\"quotes\": {quote_count}, \"replies\": {reply_count}}}", flush=True)
            os._exit(0 if (quote_count + reply_count) > 0 else 2)
        signal.signal(signal.SIGALRM, _on_deadline)
        signal.alarm(_deadline)
    try:
        main()
    finally:
        try:
            signal.alarm(0)
        except Exception:
            pass
        try:
            from x_stealth_browser import stop_playwright
            stop_playwright()
        except Exception:
            pass