import os
import json
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

# --- SETTINGS ---
BASE_DIR = Path(__file__).resolve().parent
LOG_PATH = BASE_DIR / "xp_log.json"      # Your master source
STATE_PATH = BASE_DIR / "post_state.json"
TIMEZONE = "Europe/London"

def get_yesterday_dates():
    tz = ZoneInfo(TIMEZONE)
    yesterday = datetime.now(tz) - timedelta(days=1)
    return [
        yesterday.strftime("%Y-%m-%d"), # 2026-03-20
        yesterday.strftime("%d/%m/%Y")  # 20/03/2026
    ]

def load_json(path, fallback):
    if path.exists():
        try:
            with open(path, "r") as f: return json.load(f)
        except: pass
    return fallback

def save_json(path, data):
    with open(path, "w") as f: json.dump(data, f, indent=2)

def parse_xp(val):
    """Turns '+1,234,567' or 1234567 into a clean integer."""
    try:
        if isinstance(val, int): return val
        return int(str(val).replace(",", "").replace("+", "").strip())
    except: return 0

# --- MAIN REPORTER ---
def main():
    target_dates = get_yesterday_dates()
    iso_yesterday = target_dates[0]
    
    print(f"📊 Searching for Yesterday's results ({' or '.join(target_dates)}) in {LOG_PATH.name}...")

    # Load your historical data
    # Structure expected: {"Character Name": {"Date": "XP Gain"}}
    logs = load_json(LOG_PATH, {})
    yesterday_results = []

    for name, history in logs.items():
        # Check both date formats
        for d_fmt in target_dates:
            if d_fmt in history:
                gain = parse_xp(history[d_fmt])
                if gain >= 0:
                    yesterday_results.append({"name": name, "gain": gain})
                    break # Found it for this character

    if yesterday_results:
        # Sort by highest gain
        yesterday_results.sort(key=lambda x: x['gain'], reverse=True)
        
        # Filter out 0 gains for the top list
        top_gainers = [g for g in yesterday_results if g['gain'] > 0]
        
        if not top_gainers:
            print("😴 Data found, but everyone gained 0 XP.")
            return

        # --- DISCORD EMBED ---
        fields = []
        medals = {0: "🥇", 1: "🥈", 2: "🥉"}
        max_xp = top_gainers[0]['gain']

        for i, p in enumerate(top_gainers[:5]):
            pct = (p['gain'] / max_xp) if max_xp > 0 else 0
            bar = "🟩" * round(pct * 10) + "⬛" * (10 - round(pct * 10))
            fields.append({
                "name": f"{medals.get(i, '🔹')} **{p['name']}**",
                "value": f"`+{p['gain']:,} XP`\n{bar} `{int(pct*100)}%`",
                "inline": False
            })

        payload = {
            "embeds": [{
                "title": "🏆 Yesterday's XP Champions 🏆",
                "description": f"🗓️ Results for: **{iso_yesterday}**",
                "fields": fields,
                "color": 0x2ecc71,
                "footer": {"text": "Data extracted from local xp_log.json"}
            }]
        }

        # Post to Discord (with state check to avoid double-posting)
        state = load_json(STATE_PATH, {})
        if state.get("daily_posted") != iso_yesterday:
            webhook = os.environ.get("DISCORD_WEBHOOK_URL")
            if webhook:
                r = requests.post(webhook, json=payload)
                if r.status_code in [200, 204]:
                    state["daily_posted"] = iso_yesterday
                    save_json(STATE_PATH, state)
                    print(f"🚀 Discord post sent for {iso_yesterday}!")
                else:
                    print(f"❌ Discord error: {r.status_code}")
    else:
        print(f"❌ No entries for {target_dates[0]} or {target_dates[1]} found in {LOG_PATH.name}.")
        # Debug: Print the first character's dates to see what's actually in there
        if logs:
            first_char = next(iter(logs))
            available_dates = list(logs[first_char].keys())[:3]
            print(f"💡 Found dates like {available_dates} for {first_char}. Check your format!")

if __name__ == "__main__":
    main()
