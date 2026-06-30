#!/usr/bin/env python3
"""
X @mhucex Weekly Views Tracker.
Scrapes the profile, sums per-post views for posts within the last 7 days
(proxy for the Premium-gated "7-day impressions" analytics number), saves a
snapshot, and reports week-over-week delta. Built to measure the effect of the
East-Asia targeting rollout (CJK fix + gold-filter + quote-sees-image).

Run weekly via cron. Self-delivers a box to Telegram.
"""
import sys, json, os, re, time
from datetime import datetime, timezone, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

SNAP_FILE = os.environ.get("X_VIEWS_SNAP_FILE", os.path.join(SCRIPT_DIR, "x_views_snapshots.json"))
WINDOW_DAYS = 7
HANDLE = "mhucex"


def parse_views(label: str) -> int:
    """'33124 tayangan...' / '12.5K tayangan' -> int."""
    if not label:
        return 0
    m = re.search(r'([\d.,]+)\s*([KMrb]*)', label.strip())
    if not m:
        return 0
    num = m.group(1).replace(',', '')
    suffix = (m.group(2) or '').lower()
    try:
        val = float(num)
    except ValueError:
        return 0
    if 'k' in suffix:
        val *= 1_000
    elif 'm' in suffix:
        val *= 1_000_000
    elif 'rb' in suffix:  # Indonesian "ribu" = thousand
        val *= 1_000
    return int(val)


def scrape_profile_views():
    """Scroll the profile, collect {datetime, views} for recent posts."""
    from x_stealth_browser import init_search_browser
    br, ctx = init_search_browser()
    pg = ctx.new_page()
    seen = {}
    try:
        pg.goto(f"https://x.com/{HANDLE}", timeout=30000, wait_until="domcontentloaded")
        pg.wait_for_timeout(7000)
        # Scroll a handful of times to pull ~7 days of posts into the DOM.
        for _ in range(10):
            rows = pg.evaluate(r"""() => {
              const arts = document.querySelectorAll('article');
              const out = [];
              arts.forEach(a => {
                const tm = a.querySelector('time');
                const al = a.querySelector('a[href*="/analytics"]');
                const link = a.querySelector('a[href*="/status/"]');
                let id = '';
                if (link) {
                  const h = link.getAttribute('href') || '';
                  const m = h.match(/status\/(\d+)/);
                  if (m) id = m[1];
                }
                out.push({
                  id: id,
                  dt: tm ? tm.getAttribute('datetime') : '',
                  views: al ? (al.getAttribute('aria-label') || '') : ''
                });
              });
              return out;
            }""")
            for r in rows:
                if r.get('id') and r.get('dt'):
                    seen[r['id']] = {'dt': r['dt'], 'views': parse_views(r['views'])}
            pg.mouse.wheel(0, 2200)
            pg.wait_for_timeout(1800)
    except Exception as e:
        print(f"scrape error: {e}", file=sys.stderr)
    finally:
        try:
            pg.close()
        except Exception:
            pass
    return seen


def main():
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=WINDOW_DAYS)

    posts = scrape_profile_views()
    in_window = []
    for pid, p in posts.items():
        try:
            dt = datetime.fromisoformat(p['dt'].replace('Z', '+00:00'))
        except Exception:
            continue
        if dt >= cutoff:
            in_window.append(p['views'])

    total_views = sum(in_window)
    n_posts = len(in_window)
    avg_per_post = (total_views // n_posts) if n_posts else 0
    avg_per_day = total_views // WINDOW_DAYS

    # Load previous snapshot for week-over-week delta
    prev = None
    if os.path.exists(SNAP_FILE):
        try:
            snaps = json.load(open(SNAP_FILE))
            if snaps:
                prev = snaps[-1]
        except Exception:
            snaps = []
    else:
        snaps = []

    # Append this snapshot
    snap = {
        'date': now.strftime('%Y-%m-%d'),
        'ts': now.isoformat(),
        'total_views': total_views,
        'posts': n_posts,
        'avg_per_post': avg_per_post,
        'avg_per_day': avg_per_day,
    }
    snaps.append(snap)
    snaps = snaps[-26:]  # keep ~6 months
    try:
        json.dump(snaps, open(SNAP_FILE, 'w'), indent=2)
    except Exception as e:
        print(f"snapshot save error: {e}", file=sys.stderr)

    # Build delta line
    if prev:
        d_views = total_views - prev['total_views']
        pct = (d_views / prev['total_views'] * 100) if prev['total_views'] else 0
        arrow = "📈" if d_views > 0 else ("📉" if d_views < 0 else "➡️")
        delta_line = f"{arrow} vs {prev['date']}: {d_views:+,} ({pct:+.0f}%)"
    else:
        delta_line = "📌 Snapshot pertama (baseline) — minggu depan ada perbandingan"

    # Target context: 60K/day = 420K/7d to hit 5M/3mo
    TARGET_7D = 420_000
    pct_target = (total_views / TARGET_7D * 100) if TARGET_7D else 0

    ts_wib = (now + timedelta(hours=7)).strftime('%Y-%m-%d %H:%M WIB')
    box = "\n".join([
        "```",
        "📊 X VIEWS TRACKER — @mhucex (7 hari)",
        "━" * 44,
        f"🕐 Cek      : {ts_wib}",
        f"👁️  Views 7d : {total_views:,}",
        f"📝 Posts    : {n_posts}  (avg {avg_per_post:,}/post)",
        f"📈 Per hari : ~{avg_per_day:,}/hari",
        f"🎯 vs target: {pct_target:.0f}% (dari 420K = 60K/hari)",
        delta_line,
        "━" * 44,
        "```",
    ])
    print(box)


if __name__ == "__main__":
    main()
