import os
import json
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

# --- SETTINGS ---
BASE_DIR = Path(__file__).resolve().parent
LOG_PATH = BASE_DIR / "xp_log.json"
POST_STATE_PATH = BASE_DIR / "post_state.json"
TIMEZONE = "Europe/London"

def get_yesterday_iso():
    tz = ZoneInfo(TIMEZONE)
    # Target: 2026-03-20
    return (datetime.now(tz) - timedelta(days=1)).strftime("%Y-%m-%d")

def load_json(path):
    """Safely loads JSON. Returns empty dict if file is missing."""
    if path.exists():
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"❌ Error reading {path.name}: {e}")
    return {}

def save_state(date_str):
    """Saves only the 'already posted' status to a separate file."""
    state = {"last_posted": date_str}
    with open(POST_STATE_PATH, "w") as f:
        json.dump(state, f)

def parse_xp(val):
    """Converts string '+1,234' to integer 1234."""
    try:
        return int(str(val).replace(",", "").replace("+", "").strip())
    except:
        return 0

# --- THE SAFE REPORTER ---
def main():
    yesterday = get_yesterday_iso()
    print(f"📊 Checking logs for: {yesterday}")

    # 1. LOAD DATA (Read Only)
    logs = load_json(LOG_PATH)
    if not logs:
        print(f"⚠️ {LOG_PATH.name} is empty or missing. Nothing to post.")
        return

    # 2. EXTRACT YESTERDAY'S GAINS
    results = []
    for name, dates in logs.items():
        if yesterday in dates:
            val = parse_xp(dates[yesterday])
            if val > 0:
                results.append({"name": name, "xp": val})

    if not results:
        print(f"😴 No entries found for {yesterday} in your log.")
        return

    # 3. SORT & BUILD EMBED
    results.sort(key=lambda x: x['xp'], reverse=True)
    
    # Avoid double-posting
    state = load_json(POST_STATE_PATH)
    if state.get("last_posted") == yesterday:
        print(f"⏩ Already posted results for {yesterday}. Skipping.")
        return

    fields = []
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    max_xp = results[0]['xp']

    for i, p in enumerate(results[:5]):
        pct = (p['xp'] / max_xp) if max_xp > 0 else 0
        bar = "🟩" * round(pct * 10) + "⬛" * (10 - round(pct * 10))
        fields.append({
            "name": f"{medals.get(i, '🔹')} **{p['name']}**",
            "value": f"`+{p['xp']:,} XP`\n{bar} `{int(pct*100)}%`",
            "inline": False
        })

    payload = {
        "embeds": [{
            "title": "🏆 Yesterday's XP Champions 🏆",
            "description": f"🗓️ Results for: **{yesterday}**",
            "fields": fields,
            "color": 0x2ecc71,
            "footer": {"text": "Verified Daily Log Results"}
        }]
    }

    # 4. SEND TO DISCORD
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if webhook:
        r = requests.post(webhook, json=payload)
        if r.status_code in [200, 204]:
            save_state(yesterday)
            print(f"🚀 Success! Yesterday's leaderboard sent to Discord.")
        else:
            print(f"❌ Discord error: {r.status_code}")

if __name__ == "__main__":
    main()
