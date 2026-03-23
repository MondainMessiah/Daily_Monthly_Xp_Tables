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
# 🛠️ THE GOOGLE BRIDGE SCRAPER (V14 TIBIARING)
# ==========================================
def fetch_tibiaring_gain(name, dates):
    """
    Scrapes TibiaRing via Google Bridge. 
    Much cleaner table structure than GuildStats.
    """
    bridge_url = os.environ.get("GOOGLE_BRIDGE_URL")
    if not bridge_url: return "NO_URL"

    formatted_name = name.replace(' ', '+')
    # TibiaRing shows a clear 30-day history on the main char page
    target_url = f"https://www.tibiaring.com/char.php?c={formatted_name}"
    final_url = f"{bridge_url}?url={urllib.parse.quote(target_url)}"
    
    try:
        r = requests.get(final_url, timeout=45)
        if r.status_code != 200: return 0
        
        # --- THE TIBIARING SNIPER ---
        # 1. Finds the date (YYYY-MM-DD format).
        # 2. Skips the Level column.
        # 3. Grabs the XP Gain column.
        pattern = rf"{dates['yesterday_iso']}.*?<td>.*?</td>.*?<td>\s*([+-]?[\d,.]+)"
        match = re.search(pattern, r.text, re.IGNORECASE | re.DOTALL)
        
        if match:
            raw_val = match.group(1)
            is_negative = '-' in raw_val
            clean_val = "".join(c for c in raw_val if c.isdigit())
            
            if clean_val:
                val = int(clean_val)
                # EMERGENCY BRAKE: No legit Tibia player gains 500kk+ in 24 hours.
                if val > 500000000: 
                    print(f"🛑 Error: {name} scraped impossible number ({val}). Filtered to 0.")
                    return 0 
                return -val if is_negative else val
        
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
        "yesterday_iso": yesterday_obj.strftime("%Y-%m-%d"), # 2026-03-22
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
        # Final safety check during parsing
        if num > 500000000: return 0
        return -num if is_neg else num
    except: return 0

def make_bar(val, max_val):
    if max_val <= 0: return "⬛" * 10
    filled = max(0, min(10, round((val / max_val) * 10)))
    return "🟩" * filled + "⬛" * (10 - filled)

# --- DISCORD POSTER ---
def send_discord_post(title, date_label, ranking, team_total, team_change):
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook or not ranking: return

    max_xp = ranking[0][1]
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    fields = []
    
    # STREAK LOGIC
    streaks = load_json(STREAKS_PATH, {"daily": {"last_winner": "", "count": 0}})
    winner_name = ranking[0][0]
    daily = streaks.get("daily", {"last_winner": "", "count": 0})

    if daily.get("last_winner") == winner_name:
        daily["count"] += 1
    else:
        daily["last_winner"], daily["count"] = winner_name, 1
    
    save_json(STREAKS_PATH, streaks)
    icon = "👑" if daily['count'] >= 5 else "🔥"

    # BUILD TOP 3
    for i, (name, xp) in enumerate(ranking[:3]):
        pct = int((xp / max_xp) * 100) if max_xp > 0 else 0
        s = f" {icon} `{daily['count']}`" if i == 0 else ""
        fields.append({
            "name": f"{medals[i]} **{name}**{s}",
            "value": f"`{xp:+,} XP`\n{make_bar(xp, max_xp)} `{pct}%`",
            "inline": False
        })

    # OTHER GAINS
    others = [f"**{n}** ({v:+,} XP)" for n, v in ranking[3:10] if v != 0]
    if others: fields.append({"name": "--- Other Gains ---", "value": "\n".join(others)})

    payload = {
        "embeds": [{
            "title": f"🏆 {title} 🏆",
            "description": f"🗓️ Date: **{date_label}**",
            "fields": fields,
            "color": 0x2ecc71,
            "footer": {"text": f"Total: {team_total:,} XP ({team_change})\n🔥 = 1-4 Streak | 👑 = 5+ Streak"}
        }]
    }
    requests.post(webhook, json=payload)

# --- MAIN ENGINE ---
def main():
    dates = get_dates()
    logs, state = load_json(LOG_PATH), load_json(STATE_PATH)
    if not CHAR_FILE.exists(): return
    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]

    print(f"🌐 Pivoting to TibiaRing for {dates['yesterday_iso']}...")
    
    success_count = 0
    for name in chars:
        # We use TibiaRing now!
        gain = fetch_tibiaring_gain(name, dates)
        
        if isinstance(gain, int) and gain != 0:
            if name not in logs: logs[name] = {}
            logs[name][dates['yesterday_iso']] = f"{gain:+,}"
            print(f"✅ {name}: {gain:+,} XP")
            success_count += 1
            time.sleep(1) # Gentle pacing for the bridge
        else:
            print(f"⚪ {name}: No daily gain found on TibiaRing.")

    if success_count > 0:
        save_json(LOG_PATH, logs)
        rank_y = []
        total_y, total_db = 0, 0
        for name in chars:
            h = logs.get(name, {})
            y, db = parse_xp(h.get(dates['yesterday_iso'], 0)), parse_xp(h.get(dates['day_before_iso'], 0))
            if y != 0: rank_y.append((name, y))
            total_y += y; total_db += db

        if rank_y and state.get("last_daily") != dates['yesterday_iso']:
            rank_y.sort(key=lambda x: x[1], reverse=True)
            change = f"{((total_y - total_db)/total_db)*100:+.1f}%" if total_db > 0 else "0%"
            send_discord_post("Daily Champion", dates['yesterday_iso'], rank_y, total_y, change)
            state["last_daily"] = dates['yesterday_iso']
            save_json(STATE_PATH, state)
            print("🚀 TibiaRing Scrape & Post Complete.")
    else:
        print("⛔ Scrape failed to find any valid gains on TibiaRing today.")

if __name__ == "__main__":
    main()
