import os
import json
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

# --- SETTINGS ---
BASE_DIR = Path(__file__).resolve().parent
CHAR_FILE = BASE_DIR / "characters.txt"
LOG_PATH = BASE_DIR / "xp_log.json"      # Master record of daily gains
TOTALS_PATH = BASE_DIR / "xp_totals.json" # Last known total XP
STATE_PATH = BASE_DIR / "post_state.json"
TIMEZONE = "Europe/London"

def get_date(days_ago):
    tz = ZoneInfo(TIMEZONE)
    return (datetime.now(tz) - timedelta(days=days_ago)).strftime("%Y-%m-%d")

def load_json(path, fallback):
    if path.exists():
        try:
            with open(path, "r") as f: return json.load(f)
        except: pass
    return fallback

def save_json(path, data):
    with open(path, "w") as f: json.dump(data, f, indent=2)

def fetch_current_total(name):
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
    
    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]
    
    # 1. UPDATE LOGS FOR TODAY
    totals = load_json(TOTALS_PATH, {})
    logs = load_json(LOG_PATH, {})
    
    print(f"📡 Updating daily gains in {LOG_PATH.name} for {today}...")
    for name in chars:
        current_total = fetch_current_total(name)
        if current_total == 0: continue
        
        last_total = totals.get(name, 0)
        if last_total > 0:
            gain = current_total - last_total
            if gain >= 0:
                if name not in logs: logs[name] = {}
                logs[name][today] = f"+{gain:,}"
        
        totals[name] = current_total
    
    save_json(TOTALS_PATH, totals)
    save_json(LOG_PATH, logs)

    # 2. POST RESULTS FOR YESTERDAY
    print(f"📊 Extracting Yesterday's results ({yesterday}) for Discord...")
    yesterday_results = []
    for name, dates in logs.items():
        if yesterday in dates:
            val = int(dates[yesterday].replace(",", "").replace("+", ""))
            if val > 0:
                yesterday_results.append((name, val))

    if yesterday_results:
        yesterday_results.sort(key=lambda x: x[1], reverse=True)
        
        # Discord Embed logic
        fields = []
        medals = {0: "🥇", 1: "🥈", 2: "🥉"}
        max_xp = yesterday_results[0][1]
        
        for i, (name, val) in enumerate(yesterday_results[:5]):
            pct = (val / max_xp) if max_xp > 0 else 0
            bar = "🟩" * round(pct * 10) + "⬛" * (10 - round(pct * 10))
            fields.append({
                "name": f"{medals.get(i, '🔹')} **{name}**",
                "value": f"`+{val:,} XP`\n{bar} `{int(pct*100)}%`"
            })

        payload = {
            "embeds": [{
                "title": "🏆 Yesterday's XP Champions 🏆",
                "description": f"🗓️ Results for: **{yesterday}**",
                "fields": fields,
                "color": 0x2ecc71,
                "footer": {"text": "Data sourced from xp_log.json"}
            }]
        }

        # Avoid double posting
        state = load_json(STATE_PATH, {})
        if state.get("daily_posted") != yesterday:
            webhook = os.environ.get("DISCORD_WEBHOOK_URL")
            if webhook:
                requests.post(webhook, json=payload)
                state["daily_posted"] = yesterday
                save_json(STATE_PATH, state)
                print("🚀 Discord post sent!")
    else:
        print(f"😴 No entries for {yesterday} found in log yet.")

if __name__ == "__main__":
    main()
