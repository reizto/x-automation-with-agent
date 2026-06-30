#!/usr/bin/env python3
"""@mhucex Cookie Health Check — uses the SAME validated path as the bots."""
import sys
import os
from datetime import datetime

# --- Active hours gate: 06-23 WIB ---
os.environ['TZ'] = 'Asia/Jakarta'
now_h = datetime.now().hour
if now_h < 6 or now_h >= 23:
    sys.exit(0)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from box_helper import box
from x_stealth_browser import check_cookie_health, set_default_browser_type

set_default_browser_type('firefox')
ok, msg = check_cookie_health()
now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

if ok:
    box("🍪 COOKIE HEALTH CHECK — OK", {
        "👤 Account" : "@mhucex",
        "✅ Status"  : f"{msg}",
        "🕐 Time"    : now,
    })
    sys.exit(0)
else:
    box("🍪 COOKIE HEALTH CHECK — FAIL", {
        "👤 Account" : "@mhucex",
        "❌ Status"  : f"{msg}",
        "🔧 Action"  : "Re-login needed",
        "📁 File"    : "set X_COOKIE_FILE",
        "🕐 Time"    : now,
    })
    sys.exit(1)