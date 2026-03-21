import os
import json
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

# --- SETTINGS ---
BASE_DIR = Path(__file__).resolve().parent
CHAR_FILE = BASE_DIR / "characters.txt"
JSON_PATH = BASE_DIR / "xp_history.json"  # Stores total XP per day
PB_PATH = BASE_DIR / "personal_bests.json"
STREAKS_PATH = BASE_DIR / "streaks.json"
POST_STATE_PATH = BASE_DIR / "post_state.json"
TIMEZONE = "Europe/London"

def get_dates():
    today = datetime.now(ZoneInfo(TIMEZONE))
    return today.strftime("%Y-%m-%d"), (today - timedelta(days=1)).strftime("%Y-%m-%d")

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

# --- TIBIADATA API ---
def get_total_xp(char_name):
    url = f"https://api.tibiadata.com/v4/character/{char_name.replace(' ', '%20')}"
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            data = response.json()
            return data.get("character", {}).get("character", {}).get("experience", 0)
    except: pass
    return 0

# --- LOGIC ---
def create_fields(rank, max_xp, category, badge_winner):
    fields = []
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    for i, (name, xp) in enumerate(rank[:3]):
        pct = (xp / max_xp) if max_xp > 0 else 0
        bar = "🟩" * round(pct * 10) + "⬛" * (10 - round(pct * 10))
        fields.append({"name": f"{medals[i]} **{name}** {badge_winner if i==0 else ''}", "value": f"`+{xp:,} XP`\n{bar} `{int(pct*100)}%`", "inline": False})
    
    others = [f"**{n}** (`+{v:,}`)" for n, v in rank[3:] if v > 0]
    if others: fields.append({"name": "--- Others ---", "value": ", ".join(others)})
    return fields

def update_streak(winner):
    s = load_json(STREAKS_PATH, {"last": "", "count": 0})
    if s["last"] == winner: s["count"] += 1
    else: s["last"], s["count"] = winner, 1
    save_json(STREAKS_PATH, s)
    return f" `🔥 {s['count']}` "

# --- MAIN ---
def main():
    today, yesterday = get_dates()
    if not CHAR_FILE.exists(): return
    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]
    
    history = load_json(JSON_PATH, {})
    daily_gains = []

    print(f"🎯 Fetching current XP for baseline...")
    for name in chars:
        current_xp = get_total_xp(name)
        if current_xp == 0: continue
        
        if name not in history: history[name] = {}
        
        # Calculate gain if we have yesterday's data
        prev_xp = history[name].get(yesterday)
        if prev_xp:
            gain = current_xp - prev_xp
            if gain >= 0:
                daily_gains.append((name, gain))
                print(f"✅ {name}: +{gain:,} XP")
        
        # Update history with today's total
        history[name][today] = current_xp

    save_json(JSON_PATH, history)

    if daily_gains:
        daily_gains.sort(key=lambda x: x[1], reverse=True)
        if any(g[1] > 0 for g in daily_gains):
            badge = update_streak(daily_gains[0][0])
            payload = {
                "embeds": [{
                    "title": "🏆 Daily XP Champions 🏆",
                    "description": f"🗓️ Date: **{today}**",
                    "fields": create_fields(daily_gains, daily_gains[0][1], "daily", badge),
                    "color": 0x2ecc71,
                    "footer": {"text": "Powered by TibiaData API • No more 403 blocks!"}
                }]
            }
            
            state = load_json(POST_STATE_PATH, {})
            if state.get("daily") != today:
                post_to_discord(payload)
                state["daily"] = today
                save_json(POST_STATE_PATH, state)
                print("🚀 Discord post sent!")
    else:
        print("ℹ️ Baseline established. First results will show in the next run!")

if __name__ == "__main__":
    main()
