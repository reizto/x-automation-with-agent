#!/usr/bin/env python3
"""
Robust X automation with multi-selector fallbacks, explicit errors, mobile browser support.
Replaces x_stealth_browser.py with production-ready version.
"""

import json
import os
import re
import time
import requests
from typing import Optional, Tuple
from playwright.sync_api import Page, Locator

COOKIE_FILE = os.environ.get("X_COOKIE_FILE", "")
_COOKIE_PERSISTENT = os.environ.get("X_COOKIE_PERSISTENT", "")

def _ensure_cookies():
    """Copy persistent cookie to /tmp if missing (survives reboot)."""
    import shutil, os
    if not COOKIE_FILE:
        raise FileNotFoundError("Set X_COOKIE_FILE or X_COOKIE_PERSISTENT")
    if not os.path.exists(COOKIE_FILE):
        if _COOKIE_PERSISTENT and os.path.exists(_COOKIE_PERSISTENT):
            shutil.copy2(_COOKIE_PERSISTENT, COOKIE_FILE)
        else:
            raise FileNotFoundError(
                f"Cookie file missing: {COOKIE_FILE}; set X_COOKIE_FILE or X_COOKIE_PERSISTENT"
            )

_ensure_cookies()

def _get_auth_cookies() -> dict:
    """Load cookies as a plain dict for requests library."""
    try:
        with open(COOKIE_FILE, 'r') as f:
            cookies = json.load(f)
        return {c['name']: c['value'] for c in cookies if c.get('name') and c.get('value')}
    except:
        return {}

def _get_ct0() -> str:
    """Get ct0 token for GraphQL requests."""
    try:
        with open(COOKIE_FILE) as f:
            cookies = json.load(f)
        for c in cookies:
            if c.get('name') == 'ct0':
                return c.get('value', '')
    except:
        pass
    return ''

def _api_search_tweets(query: str, count: int = 10) -> list:
    """Search tweets via X GraphQL API (requests-based, no browser/EPIPE)."""
    # Use Bearer token + full cookies + csrf token
    import re
    bearer = os.environ.get("X_WEB_BEARER", "")
    if not bearer:
        return []

    url = "https://api.x.com/graphql/o2NyI0qGj0x24bW3aPB9Mg/SearchTimeline"
    params = {
        "variables": json.dumps({
            "rawQuery": query,
            "count": count,
            "querySource": "typed_query",
            "product": "Latest"
        }),
        "features": json.dumps({
            "responsive_web_graphql_exclude_directive_enabled": True,
            "responsive_web_graphql_skip_inline_profile_enabled": False,
            "responsive_web_graphql_to_cache_data_endpoint_enabled": False,
        })
    }
    headers = {
        "Authorization": f"Bearer {bearer}",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"https://x.com/search?q={query}&f=live",
        "x-twitter-auth-type": "OAuth2Session",
        "x-twitter-active-user": "yes",
    }
    cookies = _get_auth_cookies()
    ct0 = _get_ct0()
    if ct0:
        cookies['ct0'] = ct0

    try:
        r = requests.get(url, params=params, headers=headers, cookies=cookies, timeout=20)
        if r.status_code != 200:
            return []
        data = r.json()
        tweets = []
        entries = (data.get('data', {}).get('search_by_raw_query', {})
                   .get('search_timeline', {}).get('timeline', {}).get('instructions', []))
        for instr in entries:
            for item in instr.get('entries', []):
                res = item.get('content', {}).get('itemContent', {})
                if res.get('__typename') == 'TimelineTweet':
                    result = res.get('tweet_results', {}).get('result', {})
                    legacy = result.get('legacy', {})
                    user_info = result.get('core', {}).get('user_results', {}).get('result', {}).get('legacy', {})
                    tweets.append({
                        'id': legacy.get('id_str', ''),
                        'text': legacy.get('full_text', ''),
                        'url': f"https://x.com/{user_info.get('screen_name','')}/status/{legacy.get('id_str','')}",
                        'username': user_info.get('screen_name', ''),
                        'views': 0,
                    })
        return tweets
    except:
        return []

def _api_timeline(count: int = 20) -> list:
    """Get home timeline via X GraphQL API (requests-based, no browser/EPIPE)."""
    bearer = os.environ.get("X_WEB_BEARER", "")
    if not bearer:
        return []

    url = "https://api.x.com/graphql/4Ny0xgJ9F0yw8Jq86J95iw/HomeTimeline"
    params = {
        "variables": json.dumps({
            "count": count,
            "includePromotedContent": False,
            "latestControlPoint": False,
        }),
        "features": json.dumps({
            "responsive_web_graphql_exclude_directive_enabled": True,
            "responsive_web_graphql_to_cache_data_endpoint_enabled": False,
        })
    }
    headers = {
        "Authorization": f"Bearer {bearer}",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://x.com/home",
        "x-twitter-auth-type": "OAuth2Session",
        "x-twitter-active-user": "yes",
    }
    cookies = _get_auth_cookies()
    ct0 = _get_ct0()
    if ct0:
        cookies['ct0'] = ct0

    try:
        r = requests.get(url, params=params, headers=headers, cookies=cookies, timeout=20)
        if r.status_code != 200:
            return []
        data = r.json()
        tweets = []
        entries = (data.get('data', {}).get('home', {})
                   .get('home_timeline_urt', {}).get('instructions', []))
        for instr in entries:
            for item in instr.get('entries', []):
                typename = item.get('content', {}).get('__typename', '')
                if 'Tweet' in typename:
                    tweet = item['content'].get('tweet', {})
                    legacy = tweet.get('legacy', {})
                    user_info = tweet.get('core', {}).get('user_results', {}).get('result', {}).get('legacy', {})
                    tweets.append({
                        'id': legacy.get('id_str', ''),
                        'text': legacy.get('full_text', ''),
                        'url': f"https://x.com/{user_info.get('screen_name','')}/status/{legacy.get('id_str','')}",
                        'username': user_info.get('screen_name', ''),
                        'views': 0,
                    })
        return tweets
    except:
        return []

# ===== SELECTOR MAPS (multi-locale, multi-layout) =====

SELECTORS = {
    # Login / Session
    "compose_button": [
        '[data-testid="tweetButton"]',
        '[data-testid="SideNav_NewTweet_Button"]',
        'a[href="/compose/tweet"]',
        '[aria-label*="Tweet" i]',
        '[aria-label*="Post" i]',
    ],
    "logged_in_indicator": [
        '[data-testid="tweetButton"]',
        '[data-testid="SideNav_NewTweet_Button"]',
    ],
    
    # Navigation
    "home_timeline": "https://x.com/home",
    "compose_tweet": "https://x.com/compose/tweet",
    
    # Tweet actions (timeline/detail)
    "reply_button": [
        '[data-testid="reply"]',
        '[aria-label*="Reply" i]',
        '[aria-label*="Balas" i]',  # ID
    ],
    "retweet_button": [
        '[data-testid="retweet"]',
        '[aria-label*="Retweet" i]',
        '[aria-label*="Repost" i]',
        '[aria-label*="Ulang" i]',  # ID
    ],
    "like_button": [
        '[data-testid="like"]',
        '[aria-label*="Like" i]',
        '[aria-label*="Suka" i]',
    ],
    "quote_menuitem": [
        '[role="menuitem"]:has-text("Quote")',
        '[role="menuitem"]:has-text("Kutip")',       # ID
        '[role="menuitem"]:has-text("引用")',        # JP
        '[role="menuitem"]:has-text("인용")',        # KR
        '[role="menuitem"]:has-text("Citar")',       # ES/PT
        '[data-testid="quote"]',                     # fallback
    ],
    "repost_menuitem": [
        '[role="menuitem"]:has-text("Repost")',
        '[role="menuitem"]:has-text("Retweet")',
        '[role="menuitem"]:has-text("Ulang")',
        '[data-testid="retweetConfirm"]',
    ],
    
    # Composer
    "tweet_textarea": [
        '[data-testid="tweetTextarea_0"]',
        '[data-testid="tweetTextarea_1"]',
        '[role="textbox"][data-testid*="tweet"]',
        'div[role="textbox"][contenteditable="true"]',
    ],
    "post_button": [
        '[data-testid="tweetButton"]',
        '[data-testid="tweetButtonInline"]',
        'button:has-text("Post")',
        'button:has-text("Tweet")',
        'button:has-text("Kirim")',  # ID
        'button:has-text("发布")',    # ZH
        'button:has-text("投稿")',    # JP
    ],
    
    # Verification
    "post_success": [
        ':has-text("Post sent")',
        ':has-text("Tweet sent")',
        ':has-text("Diposting")',
        ':has-text("已发布")',
        ':has-text("投稿しました")',
    ],
    
    # Tweet elements (timeline/search)
    "tweet_article": '[data-testid="tweet"]',
    "tweet_text": '[data-testid="tweetText"]',
    "tweet_link": 'a[href*="/status/"]',
    "user_name": '[data-testid="User-Name"]',
    "analytics": '[data-testid="analytics"]',
}

# ===== HELPER FUNCTIONS =====

def find_visible(page: Page, selector_list: list, timeout: int = 5000) -> Optional[Locator]:
    """Try multiple selectors, return first visible locator or None."""
    for selector in selector_list:
        try:
            locator = page.locator(selector).first
            if locator.is_visible(timeout=timeout):
                return locator
        except:
            continue
    return None

def wait_and_click(page: Page, selector_list: list, timeout: int = 5000, post_wait: int = 1000) -> Tuple[bool, str]:
    """Find and click with multiple selector fallbacks."""
    locator = find_visible(page, selector_list, timeout)
    if not locator:
        return False, f"Element not found: tried {[s[:50] for s in selector_list]}"
    try:
        locator.click()
        page.wait_for_timeout(post_wait)
        return True, "clicked"
    except Exception as e:
        return False, f"Click failed: {e}"

def load_cookies(context):
    """Load and normalize cookies for Playwright."""
    with open(COOKIE_FILE) as f:
        data = json.load(f)
    
    cookies = data if isinstance(data, list) else data.get('cookies', data)
    fixed = []
    for c in cookies:
        domain = c.get('domain', '')
        if 'x.com' not in domain and 'twitter.com' not in domain:
            continue
        
        # Normalize sameSite
        ss = c.get('sameSite', 'Lax')
        if ss in ('no_restriction', 'unspecified', ''):
            ss = 'None'
        elif ss.lower() == 'strict':
            ss = 'Strict'
        elif ss.lower() == 'lax':
            ss = 'Lax'
        
        # Handle auth_multi value (may contain quotes)
        value = c['value']
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        
        fixed.append({
            'name': c['name'],
            'value': value,
            'domain': '.x.com',
            'path': c.get('path', '/'),
            'secure': c.get('secure', True),
            'httpOnly': c.get('httpOnly', True),
            'sameSite': ss,
        })
    # Silent: only print if debugging
    # print(f"Loading {len(fixed)} cookies...")
    context.add_cookies(fixed)

def extract_views(text: str) -> int:
    """Extract view count from text — supports K, M, rb (Indonesian), jt (Indonesian juta)."""
    if not text:
        return 0
    import re
    text_lower = text.lower()
    
    # Indonesian: 48,6 rb (ribu=thousand), 1,7 jt (juta=million)
    for match in re.finditer(r'(\d+[.,]?\d*)\s*(jt|rb)\b', text_lower):
        val = float(match.group(1).replace(',', '.'))
        unit = match.group(2)
        if unit == 'jt':  # juta = million
            return int(val * 1_000_000)
        elif unit == 'rb':  # ribu = thousand
            return int(val * 1_000)
    
    # 1.5M, 500K patterns
    for match in re.finditer(r'(\d+\.?\d*)\s*([KMkm])\b', text_lower):
        val, unit = float(match.group(1)), match.group(2).upper()
        if unit == 'M':
            return int(val * 1_000_000)
        elif unit == 'K':
            return int(val * 1_000)
    
    # Try comma-decimal (Indonesian 48,6)
    for match in re.finditer(r'(\d+,\d+)\b', text_lower):
        try:
            val = float(match.group(1).replace(',', '.'))
            if val > 100:  # Filter out coordinates etc
                return int(val * 1000)  # Assume thousand if > 100
        except:
            pass
    
    # Plain 6+ digit numbers
    for match in re.finditer(r'\b(\d{6,})\b', text):
        try:
            return int(match.group(1))
        except:
            pass
    
    return 0

def get_view_count_from_aria(page) -> int:
    """Extract view count from aria-label attributes (most reliable)."""
    import re
    max_views = 0
    try:
        # Only look at aria-label attributes that contain "view"
        for el in page.locator('[aria-label]').all():
            try:
                aria = el.get_attribute('aria-label') or ''
                if 'view' in aria.lower():
                    for match in re.finditer(r'(\d+\.?\d*)\s*([KMkm])', aria):
                        val, unit = float(match.group(1)), match.group(2).upper()
                        if unit == 'M':
                            v = int(val * 1_000_000)
                        elif unit == 'K':
                            v = int(val * 1_000)
                        else:
                            v = int(val)
                        if v > max_views:
                            max_views = v
                    # Also match "X views" text
                    for m in re.finditer(r'([\d,]+)\s*views?', aria, re.IGNORECASE):
                        raw = m.group(1).replace(',', '')
                        try:
                            v = int(raw)
                            if v > max_views:
                                max_views = v
                        except:
                            pass
            except:
                continue
    except:
        pass
    return max_views

# Module-level default browser type (can be overridden per-script)
# Default to firefox: avoids EPIPE (chromium+xvfb incompatibility), better X anti-detection
_default_browser_type = "firefox"

# SINGLETON playwright - start ONCE, keep alive until stop_playwright()
# Starting playwright creates an asyncio event loop in the thread that calls it.
# Starting it multiple times = multiple loops = EPIPE crash.
# Solution: one playwright instance, launch/close browsers from it.
_playwright_singleton = None

def _get_playwright():
    """Get singleton Playwright instance. Start once, reuse forever."""
    global _playwright_singleton
    if _playwright_singleton is None:
        from playwright.sync_api import sync_playwright
        _playwright_singleton = sync_playwright().start()
    return _playwright_singleton

def stop_playwright():
    """Stop the singleton playwright (call once at script exit)."""
    global _playwright_singleton
    if _playwright_singleton is not None:
        try:
            _playwright_singleton.__exit__(None, None, None)
        except:
            pass
        _playwright_singleton = None

def close_browser(browser):
    """Close browser ONLY — do NOT stop the singleton playwright instance."""
    try:
        if browser:
            browser.close()
    except:
        pass

def set_default_browser_type(btype: str):
    """Set default browser type for all subsequent new_browser() calls in this module."""
    global _default_browser_type
    _default_browser_type = btype

def new_browser(headless: bool = True, use_xvfb: bool = True, browser_type: str = None):
    """Create browser with optimal settings.
    browser_type: 'chromium' (native), 'firefox' (gecko engine), 'webkit' (safari)
    Firefox recommended for X anti-detection — different TLS/canvas fingerprint
    """
    if browser_type is None:
        browser_type = _default_browser_type
    p = _get_playwright()
    
    common_args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--no-sandbox",
        "--disable-setuid-sandbox",
    ]
    if not headless:
        common_args.append("--start-maximized")
    
    if browser_type == "chromium":
        browser = p.chromium.launch(
            headless=headless,
            args=[
                "--width=1280",
                "--height=900",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
            ] + (["--start-maximized"] if not headless else [])
        )
    elif browser_type == "firefox":
        browser = p.firefox.launch(
            headless=headless,
            args=[
                "--width=1280",
                "--height=900",
            ] + common_args
        )
    elif browser_type == "webkit":
        browser = p.webkit.launch(
            headless=headless,
            args=["--width=1280", "--height=900"] + common_args
        )
    else:
        # Default: firefox
        browser = p.firefox.launch(
            headless=headless,
            args=["--width=1280", "--height=900"] + common_args
        )
    
    return browser, None

def new_browser(headless: bool = True, use_xvfb: bool = True, browser_type: str = None):
    """Create browser with context. Singleton playwright reused across calls."""
    if browser_type is None:
        browser_type = _default_browser_type
    p = _get_playwright()
    
    common_args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--no-sandbox",
        "--disable-setuid-sandbox",
    ]
    if not headless:
        common_args.append("--start-maximized")
    
    if browser_type == "chromium":
        browser = p.chromium.launch(
            headless=headless,
            args=[
                "--width=1280", "--height=900",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
            ] + (["--start-maximized"] if not headless else [])
        )
    elif browser_type == "firefox":
        browser = p.firefox.launch(
            headless=headless,
            args=["--width=1280", "--height=900"] + common_args
        )
    elif browser_type == "webkit":
        browser = p.webkit.launch(
            headless=headless,
            args=["--width=1280", "--height=900"] + common_args
        )
    else:
        browser = p.firefox.launch(
            headless=headless,
            args=["--width=1280", "--height=900"] + common_args
        )
    
    context = browser.new_context(
        viewport={"width": 1280, "height": 900},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0" if browser_type != "chromium" else "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        locale="en-US",
        timezone_id="Asia/Tokyo",
    )
    
    load_cookies(context)
    return browser, context

def close_browser(browser):
    """Close browser only — singleton playwright stays alive."""
    try:
        if browser:
            browser.close()
    except:
        pass

def verify_login(page: Page) -> bool:
    """Check if logged in via compose button visibility."""
    return find_visible(page, SELECTORS["logged_in_indicator"], timeout=3000) is not None

def navigate_and_wait(page: Page, url: str, wait_ms: int = 8000) -> bool:
    """Navigate with error handling."""
    try:
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(wait_ms)
        return True
    except Exception as e:
        return False

def click_retweet_then_quote(page: Page) -> Tuple[bool, str]:
    """Click retweet button then Quote menuitem using JS (reliable for dropdown menus)."""
    print(f"[DEBUG] Looking for retweet button...")
    
    # Click retweet - try multiple selectors with longer timeout
    locator = None
    for selector in SELECTORS["retweet_button"]:
        try:
            locator = page.locator(selector).first
            locator.wait_for(state="visible", timeout=8000)
            print(f"[DEBUG] Found retweet button with selector: {selector}")
            break
        except:
            continue
    
    if not locator:
        print(f"[DEBUG] Retweet button NOT found with any selector")
        return False, f"Retweet button not found (tried {len(SELECTORS['retweet_button'])} selectors)"
    
    try:
        locator.click()
        print(f"[DEBUG] Clicked retweet button")
    except Exception as e:
        return False, f"Retweet click failed: {e}"
    
    page.wait_for_timeout(3000)  # Wait longer for menu to appear
    
    # Click "Quote" via JS
    print(f"[DEBUG] Looking for Quote menu item...")
    result = page.evaluate('''() => {
        const keywords = ['quote','kutip','citar','인용','引用','引文','zitat','citer','citeer'];
        const items = document.querySelectorAll('[role="menuitem"]');
        console.log(`Found ${items.length} menu items`);
        for (const item of items) {
            const text = (item.textContent || '').replace(/\\s+/g, ' ').trim().toLowerCase();
            console.log(`Checking menu item: ${text}`);
            for (const kw of keywords) {
                if (text.includes(kw)) {
                    console.log(`MATCH: ${kw}`);
                    item.click();
                    return 'clicked_' + kw;
                }
            }
        }
        return 'not_found';
    }''')
    
    print(f"[DEBUG] Quote menu result: {result}")
    
    if result == 'not_found':
        page.wait_for_timeout(2000)
        # Try fallback
        result = page.evaluate('''() => {
            const el = document.querySelector('[data-testid="quote"]');
            if (el) { el.click(); return 'clicked_testid'; }
            const all = document.querySelectorAll('button, a, [role="button"]');
            for (const el of all) {
                const label = (el.getAttribute('aria-label') || '').toLowerCase();
                const txt = (el.textContent || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                if (label.includes('quote') || label.includes('kutip') || txt.includes('quote') || txt.includes('kutip')) {
                    el.click(); return 'clicked_fallback';
                }
            }
            return 'not_found';
        }''')
        print(f"[DEBUG] Fallback result: {result}")
    
    # Wait for composer textarea to be ready
    print(f"[DEBUG] Waiting for composer textarea...")
    try:
        textarea = page.locator('[data-testid="tweetTextarea_0"]').first
        textarea.wait_for(state="visible", timeout=5000)
        print(f"[DEBUG] Composer textarea ready!")
    except Exception as e:
        print(f"[DEBUG] Composer textarea wait failed: {e}")
        return False, f"Composer textarea not loaded: {e}"
    
    page.wait_for_timeout(1000)
    return True, "quote_dialog_opened"

def fill_and_post(page: Page, text: str, image_path: str = None, video_path: str = None, quote_url: str = None) -> Tuple[bool, str]:
    """Fill composer and post with fallbacks. Optionally attach an image or video.
    ORDER MATTERS: caption text is injected into the FRESH editor FIRST, THEN media
    is uploaded. Root cause of vanishing CJK captions on video posts: insert_text only
    mutates the DOM; X serializes the post from Draft.js's React editorState, not the
    DOM. An async re-render triggered by a finalizing VIDEO upload clobbers the DOM→state
    sync, so a caption injected AFTER upload lands in the DOM (passes our check) but is
    absent from editorState → posted with no caption. keyboard.type (Latin) survives
    because real key events commit to editorState directly. Quote/reply CJK works because
    text goes into a fresh editor before any media re-render. So we inject text first.
    If quote_url is given, the comment text is typed first (and verified), THEN the URL is
    typed separately so X builds the quote card."""
    media_path = video_path or image_path
    has_media = bool(media_path and os.path.exists(media_path))

    # Find textarea (compose editor exists immediately, before any media attach)
    editor = find_visible(page, SELECTORS["tweet_textarea"], timeout=5000)
    if not editor:
        return False, "Compose textarea not found (tried: tweetTextarea_0, _1, role=textbox)"

    text = text or ""

    def _editor_text():
        return page.evaluate("""() => {
            const el = document.querySelector('[data-testid="tweetTextarea_0"]')
                    || document.querySelector('[role="textbox"][data-testid*="tweetTextarea"]');
            return el ? (el.textContent || el.innerText || '') : '';
        }""")

    want_len = len(text.strip())

    try:
        # ---- STEP 1: inject caption into the FRESH editor (before media) ----
        # IMPORTANT: never wipe the DOM with `el.textContent = ''`. That desyncs
        # Draft.js's React editorState from the DOM — insert_text then lands in the
        # DOM only, editorState stays empty, and X serializes the POST from editorState
        # → CJK caption vanishes (video posts with no text). Proven via React-fiber
        # inspection 2026-06-28: textContent='' → editorState '' ; without it → intact.
        # The compose editor is already empty; for retries, clear via keyboard so
        # Draft.js tracks the change.
        editor.click()
        page.wait_for_timeout(300)

        def _kbd_clear():
            # select-all + delete dispatches real key events Draft.js commits to state
            page.keyboard.press("Control+a")
            page.wait_for_timeout(80)
            page.keyboard.press("Delete")
            page.wait_for_timeout(120)

        if not text.strip():
            if has_media:
                print(f"  📎 Media-only post, skipping text fill")
        else:
            has_non_latin = bool(re.search(r'[\u0400-\u04FF\u0600-\u06FF\u0900-\u0D7F\u4E00-\u9FFF\uAC00-\uD7AF\u3040-\u309F\u30A0-\u30FF]', text))
            if has_non_latin:
                # CDP insert_text fires ONE insertText event so CJK commits intact.
                # CRITICAL: do NOT clear a fresh compose editor before injecting.
                # Both `el.textContent=''` AND keyboard Ctrl+A→Delete reset Draft.js's
                # React editorState, leaving insert_text's text in the DOM only — X
                # serializes the POST from editorState, so the caption vanishes (proven
                # 2026-06-28 via React-fiber inspection + live submit test). The compose
                # editor is already empty, so just inject. Only clear on a RETRY, when a
                # prior attempt left partial text behind.
                print(f"  🈯 Non-Latin text → insert_text (atomic) + fallback chain")
                actual_text = ""
                for attempt in range(3):
                    editor.click()
                    page.wait_for_timeout(250)
                    editor.focus()
                    page.wait_for_timeout(200)
                    if attempt > 0:
                        # only clear if a previous attempt left residue (keyboard-based,
                        # Draft.js-aware — never textContent='')
                        if (_editor_text() or "").strip():
                            _kbd_clear()
                    if attempt < 2:
                        page.keyboard.insert_text(text)
                    else:
                        page.keyboard.type(text, delay=40)
                    page.wait_for_timeout(900)
                    actual_text = _editor_text()
                    if actual_text and len(actual_text.strip()) >= want_len * 0.9:
                        break
                    print(f"  ⚠️ inject attempt {attempt+1}: {len(actual_text.strip())}/{want_len} chars, retrying")
            else:
                print(f"  🔤 Using keyboard.type for Latin text")
                editor.click()
                page.wait_for_timeout(200)
                editor.focus()
                page.keyboard.type(text, delay=15)
                page.wait_for_timeout(300)
                actual_text = _editor_text()

            if actual_text and len(actual_text.strip()) > 0:
                landed = len(actual_text.strip())
                if landed < want_len * 0.9:
                    return False, f"Unicode drop: {landed}/{want_len} chars landed"
                print(f"  ✓ Text injected: {landed} chars")
            else:
                return False, "Text injection failed - textarea empty"

        # ---- STEP 2: upload media AFTER caption is in editorState ----
        if has_media:
            file_input = page.locator('input[type="file"]').first
            if file_input.count() > 0:
                file_input.set_input_files(media_path)
                if video_path:
                    # wait for progress to appear, then disappear, then preview render
                    for _ in range(16):
                        page.wait_for_timeout(500)
                        if page.locator('[data-testid="attachments"] [aria-label*="progress" i], [data-testid="attachments"] [role="progressbar"]').count() > 0:
                            break
                    for _ in range(120):
                        page.wait_for_timeout(500)
                        if page.locator('[data-testid="attachments"] [aria-label*="progress" i], [data-testid="attachments"] [role="progressbar"]').count() == 0:
                            break
                    for _ in range(30):
                        page.wait_for_timeout(500)
                        if page.locator('[data-testid="attachments"] video, [data-testid="attachments"] [data-testid="videoPlayer"]').count() > 0:
                            break
                    page.wait_for_timeout(2000)
                else:
                    for _ in range(20):
                        page.wait_for_timeout(500)
                        if page.locator('[data-testid="attachments"] [aria-label*="progress" i], [data-testid="attachments"] [role="progressbar"]').count() == 0:
                            break
                    page.wait_for_timeout(500)

        # ---- STEP 3: GUARD — re-verify caption survived media re-render ----
        if text.strip() and has_media:
            try:
                check = _editor_text()
                if not check or len(check.strip()) < want_len * 0.9:
                    print(f"  🔁 Caption lost after media finalize ({len(check.strip()) if check else 0}/{want_len}) — re-injecting")
                    editor.click()
                    page.wait_for_timeout(250)
                    editor.focus()
                    page.wait_for_timeout(150)
                    _kbd_clear()  # Draft.js-aware clear, NOT textContent='' (desyncs editorState)
                    page.keyboard.insert_text(text)
                    page.wait_for_timeout(900)
                    recheck = _editor_text()
                    if recheck and len(recheck.strip()) >= want_len * 0.9:
                        print(f"  ✓ Caption re-injected: {len(recheck.strip())} chars")
                    else:
                        print(f"  ⚠️ Caption re-inject still short: {len(recheck.strip()) if recheck else 0}/{want_len}")
            except Exception as e:
                print(f"  ⚠️ Caption guard error: {e}")

        # ---- STEP 4: quote URL (no media on quote path) ----
        if quote_url:
            editor.focus()
            page.wait_for_timeout(200)
            # Control+End = absolute end of all text (not just current line).
            # Plain End only moves to end of the current line — on multiline CJK text
            # the URL gets injected mid-sentence (confirmed bug Jun 29 2026).
            page.keyboard.press("Control+End")
            page.wait_for_timeout(100)
            page.keyboard.insert_text("\n\n" + quote_url)
            for _ in range(12):
                page.wait_for_timeout(500)
                has_card = page.evaluate("""() => document.querySelector('[data-testid="card.wrapper"], [aria-labelledby] div[role="link"][tabindex="0"]') !== null""")
                if has_card:
                    break
            print(f"  🔗 Quote URL appended, card={'yes' if has_card else 'no'}")

        # Force enable post button
        page.wait_for_timeout(500)
        editor.focus()
        page.wait_for_timeout(100)
        editor.evaluate("el => el.blur()")
        page.wait_for_timeout(200)
    except Exception as e:
        return False, f"Fill failed: {e}"
    
    # Click Post — escalate through methods, VERIFYING the editor empties after each
    # (a "successful" click that doesn't actually submit leaves text behind; video
    # posts often intercept the normal click via the preview overlay, so we must
    # fall through to JS click on [data-testid="tweetButton"] — proven to submit).
    page.wait_for_timeout(2000)

    # Wait for the Post button to become ENABLED. Video posts keep it aria-disabled
    # while X finalizes server-side processing even after the preview renders; clicking
    # a disabled button silently no-ops and leaves the editor full.
    def _post_btn_enabled():
        return page.evaluate('''() => {
            const btn = document.querySelector('[data-testid="tweetButton"]');
            if(!btn) return false;
            return !(btn.getAttribute('aria-disabled')==='true' || btn.disabled);
        }''')
    for _ in range(60):  # up to 30s
        if _post_btn_enabled():
            break
        page.wait_for_timeout(500)
    print(f"  🔘 Post button enabled={_post_btn_enabled()}")

    def _still_has_text():
        try:
            return bool((_editor_text() or "").strip())
        except:
            return False

    def _submitted():
        # navigated away from compose OR editor emptied
        if '/compose' not in page.url:
            return True
        return not _still_has_text()

    submitted = False

    # method 1: normal Playwright click on the post button
    post_btn = find_visible(page, SELECTORS["post_button"], timeout=3000)
    if post_btn:
        try:
            post_btn.click()
            print(f"  ✓ Post button clicked (normal)")
        except:
            pass
        page.wait_for_timeout(2500)
        if _submitted():
            submitted = True

    # method 2: JS click on tweetButton (proven to submit video posts)
    if not submitted:
        result = page.evaluate('''() => {
            const btn = document.querySelector('[data-testid="tweetButton"]')
                || document.querySelector('[data-testid="tweetTextarea_0"]')
                    ?.closest('[role="dialog"]')
                    ?.querySelector('button[aria-label*="Post"], button[aria-label*="Tweet"], button[aria-label*="Balas"], button[aria-label*="Reply"]');
            if (btn) { btn.click(); return 'clicked'; }
            return 'not_found';
        }''')
        print(f"  ↻ JS post click: {result}")
        page.wait_for_timeout(3000)
        if _submitted():
            submitted = True

    # method 3: keyboard shortcut
    if not submitted:
        editor.focus()
        page.wait_for_timeout(150)
        page.keyboard.press("Control+Enter")
        print(f"  ↻ Control+Enter (keyboard fallback)")
        page.wait_for_timeout(3000)
        if _submitted():
            submitted = True

    # Wait for navigation confirmation
    try:
        page.wait_for_url(lambda url: '/status/' in url or url == 'https://x.com/', timeout=8000)
        print(f"  ✅ Navigation confirmed")
        submitted = True
    except:
        if submitted:
            print(f"  ✅ Editor emptied (submitted, no nav)")
        else:
            print(f"  ⏭️ No navigation, checking manually...")

    page.wait_for_timeout(3000)
    if not submitted and _still_has_text():
        return False, "Post not submitted - editor still has content after all methods"
    return True, "posted"

def verify_posted(page: Page) -> Tuple[bool, Optional[str]]:
    """Check if post succeeded by waiting for navigation or success indicator."""
    # Wait for navigation or URL change
    page.wait_for_timeout(4000)
    
    # Check if we're still on compose page (post failed)
    if '/compose/post' in page.url or '/compose/tweet' in page.url:
        # Check if textarea still has text (post didn't submit)
        try:
            textarea = page.locator('[data-testid="tweetTextarea_0"]').first
            text_content = textarea.evaluate("el => el.textContent")
            if text_content and len(text_content.strip()) > 0:
                print(f"  ❌ Post failed - textarea still has text: {len(text_content)} chars")
                return False, "Post not submitted - textarea still has content"
        except:
            pass
        print(f"  ❌ Still on compose page")
        return False, "Still on compose page"
    
    # Success indicators
    if '/status/' in page.url:
        print(f"  ✅ Post successful - status URL")
        return True, page.url
    
    if 'home' in page.url or page.url == 'https://x.com/':
        print(f"  ✅ Post successful - back to home")
        return True, page.url
    
    # Check for "Your post was sent" message
    try:
        sent_msg = page.locator('text="Your post was sent"').first
        if sent_msg.is_visible(timeout=2000):
            print(f"  ✅ Post successful - confirmation message")
            return True, page.url
    except:
        pass
    
    # Fallback: assume success if not on compose page
    print(f"  ✅ Assuming success - URL: {page.url}")
    return True, page.url

# ===== HIGH-LEVEL ACTIONS =====

def post_tweet(text: str, reply_to_url: str = None, quote_url: str = None, headless: bool = True, browser_type: str = None, image_path: str = None, video_path: str = None) -> Tuple[bool, str]:
    """
    Post tweet/reply/quote using fresh browser (avoids EPIPE).
    Returns (success, url_or_error).
    """
    browser, context = new_browser(headless=headless, use_xvfb=True, browser_type=browser_type)
    page = context.new_page()
    
    try:
        # Navigate to target
        if reply_to_url:
            if not navigate_and_wait(page, reply_to_url):
                return False, "Navigation failed"
            # Use JavaScript click to bypass mask overlay
            reply_result = page.evaluate('''() => {
                const btn = document.querySelector('[data-testid="reply"]');
                if (!btn) return 'not_found';
                btn.click();
                return 'clicked';
            }''')
            page.wait_for_timeout(2000)
            if reply_result != 'clicked':
                return False, f"Reply button not found (result: {reply_result})"
        
        elif quote_url:
            # NATIVE QUOTE FLOW (fixed Jun 29 2026):
            # Navigate to the tweet → click Retweet → click Quote/Kutip.
            # URL stays ONLY in the quote card — NOT injected into body text.
            # Old flow (compose + inject URL) caused ghost ban: "too many links".
            if not navigate_and_wait(page, quote_url):
                return False, "Navigation to quote tweet failed"
            # Click Retweet button
            rt = page.evaluate('''() => {
                const btn = document.querySelector('[data-testid="retweet"]');
                if (!btn) return 'not_found';
                btn.click(); return 'clicked';
            }''')
            if rt != 'clicked':
                return False, f"Retweet button not found: {rt}"
            page.wait_for_timeout(1500)
            # Click Quote / Kutip from dropdown
            qt = page.evaluate('''() => {
                const items = [...document.querySelectorAll('[role="menuitem"]')];
                for (const item of items) {
                    const t = (item.innerText || '').toLowerCase();
                    if (t.includes('quote') || t.includes('kutip')) {
                        item.click(); return 'clicked';
                    }
                }
                return 'not_found';
            }''')
            if qt != 'clicked':
                return False, f"Quote menu item not found: {qt}"
            page.wait_for_timeout(2500)
            # Guard: verify compose dialog opened WITH quote card (not plain RT)
            has_card = page.evaluate('''() =>
                document.querySelector(
                    '[data-testid="quoteTweet"], [data-testid="card.wrapper"], '
                    + '[data-testid="tweetTextarea_0"]'
                ) !== null
            ''')
            if not has_card:
                return False, "Quote compose dialog did not open (plain RT guard)"
            # fill_and_post called WITHOUT quote_url — card already embedded natively

        else:
            if not navigate_and_wait(page, SELECTORS["compose_tweet"]):
                return False, "Navigation failed"
        
        # Fill and post — for native quote flow, quote_url is already embedded as card
        ok, msg = fill_and_post(page, text, image_path, video_path, quote_url=None)
        if not ok:
            return False, f"Compose: {msg}"
        
        # Verify
        success, url = verify_posted(page)
        return success, url or "Post verification failed"
    
    except Exception as e:
        err = str(e)
        if 'EPIPE' in err or 'write EPIPE' in err:
            return False, f"EPIPE (transport died): {err}"
        return False, f"Error: {err}"
    
    finally:
        try:
            page.close()
        except:
            pass
        try:
            close_browser(browser)
        except:
            pass

# ===== VIEW SCRAPING =====

def parse_view_count(view_text: str) -> int:
    """Parse Indonesian-formatted view count string to integer.
    Examples: '48,6 rb' -> 48600, '1,7 jt' -> 1700000, '680' -> 680
    """
    import re
    if not view_text:
        return 0
    # Clean: remove newlines, 'Tayangan', extra spaces
    text = view_text.replace('\n', ' ').replace('Tayangan', '').replace('Views', '').strip()
    text = re.sub(r'\s+', ' ', text)
    
    # Check multipliers
    multiplier = 1
    if re.search(r'\bjt\b', text):  # juta = million
        multiplier = 1_000_000
        text = re.sub(r'\bjt\b', '', text).strip()
    elif re.search(r'\brb\b', text):  # ribu = thousand
        multiplier = 1_000
        text = re.sub(r'\brb\b', '', text).strip()
    
    # Parse number: Indonesian uses ',' as decimal separator
    text = text.replace(',', '.')
    # Remove any remaining non-numeric except '.'
    nums = re.findall(r'[\d\.]+', text)
    if not nums:
        return 0
    
    try:
        return int(float(nums[0]) * multiplier)
    except:
        return 0


def get_tweet_views_detail(tweet_url: str, browser_type: str = "firefox") -> int:
    """Get view count from tweet detail page.
    Extracts from the analytics link in the article: <a href="/status/{id}/analytics">"48,6 rb Tayangan"</a>
    """
    import re
    browser, context = new_browser(headless=True, use_xvfb=True, browser_type=browser_type)
    page = context.new_page()
    
    try:
        if not navigate_and_wait(page, tweet_url, wait_ms=5000):
            return 0
        
        # Wait for articles to load
        page.wait_for_timeout(3000)
        
        # Extract tweet ID from URL
        match = re.search(r'status/(\d+)', tweet_url)
        tweet_id = match.group(1) if match else ''
        
        # Find the analytics link that belongs to this tweet article
        # Pattern: <a href="/{username}/status/{tweet_id}/analytics">"XXX rb Tayangan"</a>
        for link in page.locator(f'a[href*="/status/{tweet_id}/analytics"]').all():
            try:
                link_text = link.inner_text()
                views = parse_view_count(link_text)
                if views > 0:
                    close_browser(browser)
                    return views
            except:
                continue
        
        # Fallback: get all analytics links from all visible articles
        for link in page.locator('a[href*="/analytics"]').all():
            try:
                link_text = link.inner_text()
                views = parse_view_count(link_text)
                if views > 0:
                    close_browser(browser)
                    return views
            except:
                continue
        
        return 0
        
    except Exception as e:
        return 0
    finally:
        try:
            page.close()
            close_browser(browser)
        except:
            pass

# ===== SINGLETON BROWSER (for timeline/search — reuse, no EPIPE) =====

_search_browser = None
_search_context = None
_default_browser_type = "firefox"

def set_default_browser_type(t: str):
    global _default_browser_type
    _default_browser_type = t

def init_search_browser():
    """Init browser ONCE, reuse for all calls, close at end."""
    global _search_browser, _search_context
    if _search_browser is None:
        _search_browser, _search_context = new_browser(
            headless=True, use_xvfb=True, browser_type=_default_browser_type
        )
    return _search_browser, _search_context

def close_search_browser():
    """Close browser only — singleton playwright stays alive."""
    global _search_browser, _search_context
    if _search_browser:
        try:
            _search_browser.close()
        except:
            pass
        _search_browser = None
        _search_context = None

def _extract_tweets_via_js(page) -> list:
    """Extract tweets using JS (reliable, bypasses locator quirks).
    Only ORIGINAL tweets — skip replies (Membalas) and quotes (Kutipan)."""
    try:
        tweets = page.evaluate("""
() => {
  const articles = document.querySelectorAll('article');
  const results = [];
  // Detect GOLD (verified-organization) checkmark — skip brand/biz accounts.
  // X uses identical aria-label for all badges; the DIFFERENTIATOR is COLOR:
  //   blue individual = rgb(29,155,240) (high blue channel)
  //   gold org / gray gov = SVG gradient → computed color stays dark (low blue)
  const isGoldVerified = (el) => {
    const nameBlock = el.querySelector('[data-testid="User-Name"]') || el;
    const icon = nameBlock.querySelector('svg[data-testid="icon-verified"]');
    if (!icon) return false;  // unverified individual — keep
    const m = (getComputedStyle(icon).color || '').match(/rgba?\\(([^)]+)\\)/);
    if (m) {
      const [r, g, b] = m[1].split(',').map(x => parseFloat(x));
      // Twitter blue has b≈240; gold/gov verified do NOT → skip non-blue verified
      if (b < 180) return true;
    }
    return false;
  };
  articles.forEach(el => {
    const innerText = el.innerText || '';
    if (innerText.includes('Membalas') || innerText.includes('Kutipan')) return;
    const link = el.querySelector('a[href*="/status/"]');
    const textEl = el.querySelector('[lang]');
    const text = textEl ? textEl.innerText : innerText;
    if (link && text.trim()) {
      let href = link.getAttribute('href');
      if (!href.startsWith('http')) href = 'https://x.com' + href;
      // Extract username from href
      const parts = href.replace('https://x.com','').split('/status/');
      const username = parts[0].replace(/\/$/,'').replace(/^\//,'');
      results.push({
        url: href,
        text: text.substring(0, 300),
        username: username,
        goldVerified: isGoldVerified(el),
      });
    }
  });
  return results;
}
""")
        return tweets
    except:
        return []

def get_timeline_tweets(count: int = 20, browser_type: str = None) -> list:
    """Fetch tweets from home timeline using singleton browser (no EPIPE).
    Returns list of dicts with: url, text, username, views=0"""
    browser, context = init_search_browser()
    page = context.new_page()
    try:
        page.goto("https://x.com/home", timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(8000)
        page.mouse.wheel(0, 800)
        page.wait_for_timeout(1000)
        tweets = _extract_tweets_via_js(page)
        return tweets[:count]
    except:
        return []
    finally:
        try:
            page.close()
        except:
            pass

def search_tweets(query: str, count: int = 20, browser_type: str = None) -> list:
    """Search tweets using singleton browser (no EPIPE).
    Returns list of dicts with: url, text, username, views=0"""
    browser, context = init_search_browser()
    page = context.new_page()
    try:
        encoded = query.replace(' ', '%20')
        page.goto(f"https://x.com/search?q={encoded}&f=live",
                  timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(8000)
        page.mouse.wheel(0, 800)
        page.wait_for_timeout(1000)
        tweets = _extract_tweets_via_js(page)
        return tweets[:count]
    except:
        return []
    finally:
        try:
            page.close()
        except:
            pass

def parse_tweet_element(el) -> Optional[dict]:
    """Extract structured data from tweet element."""
    try:
        # Try data-tweet-id first, fallback to extracting from URL
        tweet_id = el.get_attribute('data-tweet-id') or ''
        
        # If no data-tweet-id, try to get from href (e.g. /username/status/1234567890)
        if not tweet_id:
            link_el = el.locator(SELECTORS["tweet_link"]).first
            href = link_el.get_attribute('href') if link_el.is_visible(timeout=1000) else ''
            # Extract ID from /username/status/1234567890
            if '/status/' in href:
                tweet_id = href.rsplit('/status/', 1)[-1].split('?')[0].split('/')[0]
        
        text_el = el.locator(SELECTORS["tweet_text"]).first
        text = text_el.inner_text() if text_el.is_visible(timeout=1000) else ''
        
        if not text:
            return None
        
        link_el = el.locator(SELECTORS["tweet_link"]).first
        link = link_el.get_attribute('href') if link_el.is_visible(timeout=1000) else ''
        
        author_el = el.locator(SELECTORS["user_name"]).first
        author = author_el.inner_text() if author_el.is_visible(timeout=1000) else ''
        
        return {
            'id': tweet_id,
            'text': text[:280],
            'url': f"https://x.com{link}" if link else '',
            'author': author,
            'views': 0,  # Not available in feed
        }
    except:
        return None

# ===== HEALTH CHECK =====

def check_cookie_health() -> Tuple[bool, str]:
    """Verify cookies still work for login."""
    browser, context = new_browser(headless=True, use_xvfb=True)
    page = context.new_page()
    
    try:
        page.goto(SELECTORS["home_timeline"], timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
        
        if verify_login(page):
            # Sync valid cookie back to persistent location
            import shutil
            try:
                shutil.copy2(COOKIE_FILE, _COOKIE_PERSISTENT)
            except Exception:
                pass
            return True, "Cookies valid - logged in"
        else:
            return False, "Cookies EXPIRED - re-login needed"
    except Exception as e:
        return False, f"Health check failed: {e}"
    finally:
        try:
            page.close()
            close_browser(browser)
        except:
            pass

# ===== MOBILE BROWSER (CDP) =====

def get_mobile_browser():
    """Connect to Android Chrome via CDP over ADB."""
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    browser = p.chromium.connect_over_cdp("http://localhost:9222")
    context = browser.contexts[0] if browser.contexts else browser.new_context()
    page = context.pages[0] if context.pages else context.new_page()
    return browser, context, page, p

def post_mobile(text: str, reply_to_url: str = None, quote_url: str = None) -> Tuple[bool, str]:
    """Post using mobile Chrome (more reliable, real UA)."""
    try:
        browser, context, page, p = get_mobile_browser()
        
        # Use mobile X for simpler DOM
        base = "https://mobile.x.com" if "x.com" in (reply_to_url or quote_url or "") else "https://x.com"
        
        target_url = reply_to_url or quote_url or f"{base}/compose/tweet"
        page.goto(target_url, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
        
        if reply_to_url:
            ok, msg = wait_and_click(page, SELECTORS["reply_button"], timeout=5000, post_wait=2000)
            if not ok:
                return False, f"Mobile reply: {msg}"
        elif quote_url:
            ok, msg = click_retweet_then_quote(page)
            if not ok:
                return False, f"Mobile quote: {msg}"
        
        ok, msg = fill_and_post(page, text)
        if not ok:
            return False, f"Mobile compose: {msg}"
        
        page.wait_for_timeout(3000)
        return True, page.url
    
    except Exception as e:
        return False, f"Mobile error: {e}"
    finally:
        try:
            close_browser(browser)
            p.stop()
        except:
            pass

# ===== STOP PLAYWRIGHT (call once at process exit) =====

_global_playwright = None

def _get_playwright():
    global _global_playwright
    if _global_playwright is None:
        from playwright.sync_api import sync_playwright
        _global_playwright = sync_playwright().start()
    return _global_playwright

def stop_playwright():
    """Stop global playwright singleton — call once at process exit."""
    global _global_playwright
    if _global_playwright:
        try:
            _global_playwright.stop()
        except:
            pass
        _global_playwright = None

# ===== EXPORTS =====
__all__ = [
    'new_browser',
    'post_tweet',
    'post_mobile',
    'get_tweet_views_detail',
    'get_timeline_tweets',
    'search_tweets',
    'check_cookie_health',
    'verify_login',
    'extract_views',
    'set_default_browser_type',
    'init_search_browser',
    'close_search_browser',
    'stop_playwright',
    'SELECTORS',
]