import os
import json
import requests
import re
import urllib.parse
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

# --- CONFIGURATION ---
BASE_DIR = Path(__file__).resolve().parent
CHAR_FILE = BASE_DIR / "characters.txt"
LOG_PATH = BASE_DIR / "xp_log.json"
STATE_PATH = BASE_DIR / "post_state.json"
STREAKS_PATH = BASE_DIR / "streaks.json"
TIMEZONE = "Europe/London"

# ==========================================
# 🛠️ THE GUILDSTATS SURGEON (V22 - VISUAL MATCH)
# ==========================================
def fetch_guildstats_gain(name, dates):
    bridge_url = os.environ.get("GOOGLE_BRIDGE_URL")
    if not bridge_url: return "NO_URL"

    formatted_name = name.replace(' ', '+')
    target_url = f"https://guildstats.eu/include/character/tab.php?nick={formatted_name}&tab=experience"
    final_url = f"{bridge_url}?url={urllib.parse.quote(target_url)}"
    
    try:
        r = requests.get(final_url, timeout=45)
        if r.status_code != 200: return 0
        
        # 1. SEARCH FOR THE DATE (MM-DD as seen in screenshot)
        # We look for the date, then find the very first number with a + or - sign.
        # This will skip the Level gain because the XP gain comes first in the row.
        pattern = rf"{dates['yesterday_simple']}.*?([+-][\d,.]+)"
        match = re.search(pattern, r.text, re.IGNORECASE | re.DOTALL)
        
        if match:
            raw_val = match.group(1)
            is_neg = '-' in raw_val
            clean_val = "".join(c for c in raw_val if c.isdigit())
            
            if clean_val:
                val = int(clean_val)
                # Safety Valve (500kk)
                if val > 500000000: return 0 
                return -val if is_neg else val
        
        return 0
    except Exception as e:
        print(f"⚠️ {name} Scrape Error: {e}")
        return 0

# ==========================================

def get_dates():
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
    yesterday_obj = now - timedelta(days=1)
    return {
        "yesterday_iso": yesterday_obj.strftime("%Y-%m-%d"),
        "yesterday_simple": yesterday_obj.strftime("%m-%d"), # Matches "03-22" from screenshot
        "day_before_iso": (now - timedelta(days=2)).strftime("%Y-%m-%d")
    }

def load_json(path, fallback=None):
    if not path.exists(): return fallback if fallback is not None else {}
    try:
        with open(path, "r") as f: return json.load(f)
    except: return fallback if fallback is not None else {}

def save_json(path, data):
    with open(path, "w") as f: json.dump(data, f, indent=2)

def parse_xp(val):
    try:
        s = str(val).strip()
        is_neg = s.startswith('-')
        clean = "".join(c for c in s if c.isdigit())
        if not clean: return 0
        num = int(clean)
        return -num if is_neg else num
    except: return 0

def make_bar(val, max_val):
    if max_val <= 0: return "⬛" * 10
    filled = max(0, min(10, round((val / max_val) * 10)))
    return "🟩" * filled + "⬛" * (10 - filled)

def send_discord_post(title, date_label, ranking, team_total):
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook or not ranking: return
    max_xp = ranking[0][1]
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    fields = []
    
    # Simple Ranking
    for i, (name, xp) in enumerate(ranking[:3]):
        pct = int((xp / max_xp) * 100) if max_xp > 0 else 0
        fields.append({
            "name": f"{medals[i]} **{name}**",
            "value": f"`{xp:+,} XP`\n{make_bar(xp, max_xp)} `{pct}%`",
            "inline": False
        })
    
    others = [f"**{n}** ({v:+,} XP)" for n, v in ranking[3:10] if v != 0]
    if others: fields.append({"name": "--- Others ---", "value": "\n".join(others)})
    
    payload = {"embeds": [{"title": f"🏆 {title} 🏆", "description": f"🗓️ Date: **{date_label}**", "fields": fields, "color": 0x2ecc71, "footer": {"text": f"Total: {team_total:,} XP" }}]}
    requests.post(webhook, json=payload)

def main():
    dates = get_dates()
    logs, state = load_json(LOG_PATH), load_json(STATE_PATH)
    if not CHAR_FILE.exists(): return
    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]

    print(f"🌐 Scraping GuildStats using visual match '{dates['yesterday_simple']}'...")
    
    success_count = 0
    for name in chars:
        gain = fetch_guildstats_gain(name, dates)
        if isinstance(gain, int) and gain != 0:
            if name not in logs: logs[name] = {}
            logs[name][dates['yesterday_iso']] = f"{gain:+,}"
            print(f"✅ {name}: {gain:+,} XP")
            success_count += 1
            time.sleep(2) 
        else:
            print(f"⚪ {name}: No daily gain found.")

    if success_count > 0:
        save_json(LOG_PATH, logs)
        rank_y = []
        total_y = 0
        for name in chars:
            h = logs.get(name, {})
            y = parse_xp(h.get(dates['yesterday_iso'], 0))
            if y != 0: rank_y.append((name, y))
            total_y += y

        if rank_y and state.get("last_daily") != dates['yesterday_iso']:
            rank_y.sort(key=lambda x: x[1], reverse=True)
            send_discord_post("Daily Champion", dates['yesterday_iso'], rank_y, total_y)
            state["last_daily"] = dates['yesterday_iso']
            save_json(STATE_PATH, state)
            print("🚀 Successfully updated and posted.")
    else:
        print("⛔ Scrape failed to find gains. Verify the date in the table.")

if __name__ == "__main__":
    main()
