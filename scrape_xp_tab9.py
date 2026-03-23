import os
import json
import requests
import re
import urllib.parse
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
# 🛠️ GUILDSTATS.EU SCRAPER (HEAT-SEEKING) 🛠️
# ==========================================
def fetch_guildstats_gain(name, target_date):
    url = f"https://guildstats.eu/character?nick={urllib.parse.quote(name)}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0'}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200: 
            return 0
        
        # HEAT-SEEKING REGEX
        # Finds the date, jumps over HTML, grabs the number
        pattern = rf"{target_date}.*?([+-]?[\d,]+)"
        match = re.search(pattern, r.text, re.DOTALL)
        
        if match:
            clean_val = match.group(1).replace(',', '').replace('+', '')
            return int(clean_val)
    except Exception as e:
        print(f"⚠️ Error scraping {name}: {e}")
    return 0

# ==========================================

def get_dates():
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
    return {
        "today": now.strftime("%Y-%m-%d"),
        "yesterday": (now - timedelta(days=1)).strftime("%Y-%m-%d"),
        "day_before": (now - timedelta(days=2)).strftime("%Y-%m-%d"),
        "obj": now
    }

def load_json(path, fallback=None):
    if not path.exists(): return fallback if fallback is not None else {}
    try:
        with open(path, "r") as f: return json.load(f)
    except: return fallback if fallback is not None else {}

def save_json(path, data):
    with open(path, "w") as f: json.dump(data, f, indent=2)

def parse_xp(val):
    try: return int(str(val).replace(",", "").replace("+", "").strip())
    except: return 0

def make_bar(val, max_val):
    if max_val <= 0: return "⬛" * 10
    filled = round((val / max_val) * 10)
    return "🟩" * filled + "⬛" * (10 - filled)

# --- DISCORD POSTER ---
def send_discord_post(title, date_label, ranking, team_total, team_change):
    if not ranking:
        print("⚠️ Discord Post skipped: No players in ranking.")
        return
    
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook:
        print("❌ ERROR: DISCORD_WEBHOOK_URL environment variable is missing!")
        return

    max_xp = ranking[0][1]
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    fields = []
    description_addon = ""

    # 1. PROCESS STREAKS
    streaks = load_json(STREAKS_PATH, {"daily": {"last_winner": "", "count": 0}})
    winner_name = ranking[0][0]
    daily = streaks.get("daily", {"last_winner": "", "count": 0})

    if daily.get("last_winner") == winner_name:
        daily["count"] += 1
    else:
        if daily.get("last_winner") and daily.get("count", 0) >= 2:
            description_addon = f"\n⚔️ **{winner_name}** has ended **{daily['last_winner']}'s** `{daily['count']}` day streak!"
        daily["last_winner"], daily["count"] = winner_name, 1
    
    save_json(STREAKS_PATH, streaks)
    icon = "👑" if daily['count'] >= 5 else "🔥"
    streak_display = f" {icon} `{daily['count']}`"

    # 2. BUILD TOP 3
    for i, (name, xp) in enumerate(ranking[:3]):
        pct = int((xp / max_xp) * 100) if max_xp > 0 else 0
        s = streak_display if i == 0 else ""
        fields.append({
            "name": f"{medals[i]} **{name}**{s}",
            "value": f"`+{xp:,} XP`\n{make_bar(xp, max_xp)} `{pct}%`",
            "inline": False
        })

    # 3. OTHER GAINS
    others = [f"**{n}** (+{v:,} XP)" for n, v in ranking[3:10] if v > 0]
    if others:
        fields.append({"name": "--- Other Gains ---", "value": "\n".join(others)})

    # 4. FOOTER
    footer_text = f"Team Total: {team_total:,} XP ({team_change} vs last daily)\n"
    footer_text += "🔥 = 1-4 Streak | 👑 = 5+ Streak"

    payload = {
        "embeds": [{
            "title": f"🏆 {title} 🏆",
            "description": f"🗓️ Date: **{date_label}**{description_addon}",
            "fields": fields,
            "color": 0x2ecc71,
            "footer": {"text": footer_text}
        }]
    }
    
    resp = requests.post(webhook, json=payload)
    if resp.status_code == 204 or resp.status_code == 200:
        print("🚀 Discord Post sent successfully!")
    else:
        print(f"❌ Failed to post to Discord: {resp.status_code} - {resp.text}")

# --- MAIN ENGINE ---
def main():
    dates = get_dates()
    logs = load_json(LOG_PATH)
    state = load_json(STATE_PATH)
    
    if not CHAR_FILE.exists():
        print("❌ Error: characters.txt not found.")
        return
        
    with open(CHAR_FILE) as f: 
        chars = [l.strip() for l in f if l.strip()]

    # --- STEP 1: FRESH SCRAPE (OVERRIDE LOCK) ---
    print(f"🔍 Fetching gains for {dates['yesterday']}...")
    for name in chars:
        gain = fetch_guildstats_gain(name, dates['yesterday'])
        if name not in logs: logs[name] = {}
        
        # Always update the log with what we find on GuildStats
        if gain != 0:
            logs[name][dates['yesterday']] = f"+{gain:,}"
            print(f"✅ {name}: {gain:,} XP (Scraped)")
        else:
            # If we find nothing, don't overwrite if there's already data there
            print(f"⚪ {name}: No update found on GuildStats.")
    
    save_json(LOG_PATH, logs)

    # --- STEP 2: CALCULATE RANKINGS ---
    rank_y = []
    total_y, total_db = 0, 0

    for name in chars:
        history = logs.get(name, {})
        val_y = parse_xp(history.get(dates['yesterday'], 0))
        val_db = parse_xp(history.get(dates['day_before'], 0))
        
        if val_y > 0: 
            rank_y.append((name, val_y))
        total_y += val_y
        total_db += val_db

    if not rank_y: 
        print(f"❌ No XP data found in logs for {dates['yesterday']}. Post aborted.")
        return

    rank_y.sort(key=lambda x: x[1], reverse=True)

    # --- STEP 3: POST TO DISCORD ---
    # To force a post for testing, you can comment out the 'if' line below:
    # if state.get("last_daily") != dates['yesterday']:
    
    change = f"{((total_y - total_db)/total_db)*100:+.1f}%" if total_db > 0 else "0%"
    send_discord_post("Daily Champion", dates['yesterday'], rank_y, total_y, change)
    
    state["last_daily"] = dates['yesterday']
    save_json(STATE_PATH, state)

if __name__ == "__main__":
    main()
