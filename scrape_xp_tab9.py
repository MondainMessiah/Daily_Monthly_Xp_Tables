import os
import json
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

# --- SETTINGS ---
BASE_DIR = Path(__file__).resolve().parent
CHAR_FILE = BASE_DIR / "characters.txt"
JSON_PATH = BASE_DIR / "xp_history.json"
POST_STATE_PATH = BASE_DIR / "post_state.json"
TIMEZONE = "Europe/London"

def get_date(days_ago):
    tz = ZoneInfo(TIMEZONE)
    dt = datetime.now(tz) - timedelta(days=days_ago)
    return dt.strftime("%Y-%m-%d")

def load_json(path, fallback):
    if path.exists():
        try:
            with open(path, "r") as f: return json.load(f)
        except: pass
    return fallback

def save_json(path, data):
    with open(path, "w") as f: json.dump(data, f, indent=2)

def post_to_discord(payload):
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if url:
        try: requests.post(url, json=payload, timeout=10)
        except: pass

# --- TIBIADATA API (To keep your files updated daily) ---
def fetch_current_xp(name):
    url = f"https://api.tibiadata.com/v4/character/{name.replace(' ', '%20')}"
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            return r.json().get("character", {}).get("character", {}).get("experience", 0)
    except: pass
    return 0

# --- MAIN ENGINE ---
def main():
    today = get_date(0)
    yesterday = get_date(1)
    day_before = get_date(2)
    
    if not CHAR_FILE.exists(): return
    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]
    
    # Load your existing history file
    history = load_json(JSON_PATH, {})
    yesterday_gains = []

    print(f"📊 Calculating results for Yesterday: {yesterday}")

    for name in chars:
        # 1. Update Today's XP in the file (Daily Maintenance)
        current_xp = fetch_current_xp(name)
        if current_xp > 0:
            if name not in history: history[name] = {}
            history[name][today] = current_xp

        # 2. Calculate Yesterday's Gain
        # Gain(Yesterday) = XP(Yesterday) - XP(Day Before)
        xp_yesterday = history.get(name, {}).get(yesterday)
        xp_day_before = history.get(name, {}).get(day_before)

        if xp_yesterday and xp_day_before:
            gain = int(xp_yesterday) - int(xp_day_before)
            if gain >= 0:
                yesterday_gains.append((name, gain))
                print(f"✅ {name}: +{gain:,} XP")
        else:
            print(f"⚠️ {name}: Missing data for {yesterday} or {day_before}")

    # Save the updated history with today's new data
    save_json(JSON_PATH, history)

    # --- DISCORD POSTING ---
    if yesterday_gains:
        yesterday_gains.sort(key=lambda x: x[1], reverse=True)
        
        # Only post if someone actually had a gain
        if any(g[1] > 0 for g in yesterday_gains):
            max_xp = yesterday_gains[0][1]
            fields = []
            medals = {0: "🥇", 1: "🥈", 2: "🥉"}
            
            for i, (name, val) in enumerate(yesterday_gains[:5]):
                pct = (val / max_xp) if max_xp > 0 else 0
                bar = "🟩" * round(pct * 10) + "⬛" * (10 - round(pct * 10))
                fields.append({
                    "name": f"{medals.get(i, '🔹')} **{name}**",
                    "value": f"`+{val:,} XP`\n{bar} `{int(pct*100)}%`",
                    "inline": False
                })

            payload = {
                "embeds": [{
                    "title": "🏆 Yesterday's XP Champions 🏆",
                    "description": f"🗓️ Results for: **{yesterday}**",
                    "fields": fields,
                    "color": 0x2ecc71,
                    "footer": {"text": "Calculated from local XP history"}
                }]
            }

            # Avoid double posting the same date
            state = load_json(POST_STATE_PATH, {})
            if state.get("daily_posted") != yesterday:
                post_to_discord(payload)
                state["daily_posted"] = yesterday
                save_json(POST_STATE_PATH, state)
                print("🚀 Discord post sent for yesterday!")
    else:
        print(f"😴 Not enough history yet to calculate {yesterday}.")

if __name__ == "__main__":
    main()
