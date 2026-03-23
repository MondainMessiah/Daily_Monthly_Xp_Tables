import os
import json
import requests
import re
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

def fetch_guildstats_gain(session, name, target_date):
    # CHANGED: Using the direct path URL format
    formatted_name = name.replace(' ', '+')
    url = f"https://guildstats.eu/character/{formatted_name}"
    
    # CHANGED: Mobile Safari headers (often bypasses basic Cloudflare IP blocks)
    headers = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-GB,en;q=0.9',
        'Referer': 'https://guildstats.eu/',
        'Connection': 'keep-alive'
    }
    
    try:
        r = session.get(url, headers=headers, timeout=20)
        
        if r.status_code == 403:
            return "BLOCKED"
        if r.status_code != 200:
            return "ERROR"
        
        # Heat-Seeking Regex
        pattern = rf"{target_date}.*?class=\"text-right.*?>\s*([+-]?[\d,]+)"
        match = re.search(pattern, r.text, re.IGNORECASE | re.DOTALL)
        
        if match:
            clean_val = match.group(1).replace(',', '').replace('+', '')
            return int(clean_val)
        return 0
    except:
        return "ERROR"

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

def send_discord_post(title, date_label, ranking, team_total, team_change):
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook or not ranking: return

    max_xp = ranking[0][1]
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    fields = []
    
    # Streaks
    streaks = load_json(STREAKS_PATH, {"daily": {"last_winner": "", "count": 0}})
    winner_name = ranking[0][0]
    daily = streaks.get("daily", {"last_winner": "", "count": 0})
    desc_addon = ""

    if daily.get("last_winner") == winner_name:
        daily["count"] += 1
    else:
        if daily.get("last_winner") and daily.get("count", 0) >= 2:
            desc_addon = f"\n⚔️ **{winner_name}** ended **{daily['last_winner']}'s** `{daily['count']}` day streak!"
        daily["last_winner"], daily["count"] = winner_name, 1
    
    save_json(STREAKS_PATH, streaks)
    icon = "👑" if daily['count'] >= 5 else "🔥"
    
    for i, (name, xp) in enumerate(ranking[:3]):
        pct = int((xp / max_xp) * 100) if max_xp > 0 else 0
        s = f" {icon} `{daily['count']}`" if i == 0 else ""
        fields.append({
            "name": f"{medals[i]} **{name}**{s}",
            "value": f"`+{xp:,} XP`\n{make_bar(xp, max_xp)} `{pct}%`",
            "inline": False
        })

    others = [f"**{n}** (+{v:,} XP)" for n, v in ranking[3:10] if v > 0]
    if others: fields.append({"name": "--- Other Gains ---", "value": "\n".join(others)})

    payload = {
        "embeds": [{
            "title": f"🏆 {title} 🏆",
            "description": f"🗓️ Date: **{date_label}**{desc_addon}",
            "fields": fields,
            "color": 0x2ecc71,
            "footer": {"text": f"Total: {team_total:,} XP ({team_change})\n🔥 = 1-4 Streak | 👑 = 5+ Streak"}
        }]
    }
    requests.post(webhook, json=payload)

def main():
    dates = get_dates()
    logs = load_json(LOG_PATH)
    state = load_json(STATE_PATH)
    
    if not CHAR_FILE.exists(): return
    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]

    print(f"🔍 Fetching gains for {dates['yesterday']}...")
    
    scrape_success = False
    with requests.Session() as session:
        for name in chars:
            result = fetch_guildstats_gain(session, name, dates['yesterday'])
            
            if name not in logs: logs[name] = {}
            
            if isinstance(result, int):
                if result != 0:
                    logs[name][dates['yesterday']] = f"+{result:,}"
                    print(f"✅ {name}: {result:,} XP")
                    scrape_success = True
                else:
                    print(f"⚪ {name}: No daily gain found.")
            elif result == "BLOCKED":
                print(f"❌ {name}: Blocked (403).")
            
            time.sleep(5) # Higher delay for stealth

    # ONLY SAVE AND POST IF AT LEAST ONE CHARACTER WAS SUCCESSFULLY SCRAPED
    if scrape_success:
        save_json(LOG_PATH, logs)
        
        rank_y = []
        total_y, total_db = 0, 0
        for name in chars:
            h = logs.get(name, {})
            y, db = parse_xp(h.get(dates['yesterday'], 0)), parse_xp(h.get(dates['day_before'], 0))
            if y > 0: rank_y.append((name, y))
            total_y += y; total_db += db

        if rank_y and state.get("last_daily") != dates['yesterday']:
            rank_y.sort(key=lambda x: x[1], reverse=True)
            change = f"{((total_y - total_db)/total_db)*100:+.1f}%" if total_db > 0 else "0%"
            send_discord_post("Daily Champion", dates['yesterday'], rank_y, total_y, change)
            state["last_daily"] = dates['yesterday']
            save_json(STATE_PATH, state)
            print("🚀 Successfully updated and posted.")
    else:
        print("⛔ Aborting: No new data was scraped (IP block likely still active).")

if __name__ == "__main__":
    main()
