import os
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

# --- SETTINGS ---
BASE_DIR = Path(__file__).resolve().parent
CHAR_FILE = BASE_DIR / "characters.txt"
JSON_PATH = BASE_DIR / "xp_log.json"
PB_PATH = BASE_DIR / "personal_bests.json"
STREAKS_PATH = BASE_DIR / "streaks.json"
TOTALS_HISTORY_PATH = BASE_DIR / "totals_history.json"
POST_STATE_PATH = BASE_DIR / "post_state.json"
TIMEZONE = "Europe/London"

def get_target_date():
    dt = datetime.now(ZoneInfo(TIMEZONE)) - timedelta(days=1)
    return dt.strftime("%Y-%m-%d") # Format: 2026-03-20

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

def mark_posted(category, date_str):
    state = load_json(POST_STATE_PATH, {})
    state[category] = date_str
    save_json(POST_STATE_PATH, state)

# --- TIBIARING SCRAPER ---
def scrape_tibiaring(char_name, target_date):
    url = f"https://www.tibiaring.com/char.php?c={char_name.replace(' ', '+')}&lang=en"
    try:
        print(f"🔍 Checking TibiaRing: {char_name}...")
        response = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
        if response.status_code != 200: return None

        soup = BeautifulSoup(response.text, "html.parser")
        
        # TibiaRing stores history in a table. We look for the row with our date.
        for row in soup.find_all("tr"):
            text = row.get_text()
            if target_date in text:
                cells = row.find_all("td")
                if len(cells) >= 3:
                    # Column 2 is usually the XP Gain on TibiaRing
                    raw_xp = cells[2].get_text(strip=True).replace(",", "").replace("+", "")
                    if raw_xp.isdigit():
                        return f"+{int(raw_xp):,}"
    except Exception as e:
        print(f"⚠️ {char_name} Error: {e}")
    return None

# --- EMBED LOGIC ---
def check_pb(category, name, current_xp):
    pbs = load_json(PB_PATH, {"daily": {}, "weekly": {}, "monthly": {}})
    cat_pbs = pbs.setdefault(category, {})
    record = cat_pbs.get(name, 0)
    if current_xp > record:
        cat_pbs[name] = current_xp
        save_json(PB_PATH, pbs)
        return " `⭐` " if record > 0 else ""
    return ""

def update_streak(category, winner_name):
    all_streaks = load_json(STREAKS_PATH, {"daily": {}, "weekly": {}, "monthly": {}})
    cat_data = all_streaks.get(category, {"last_winner": "", "count": 0})
    if cat_data["last_winner"] == winner_name:
        cat_data["count"] += 1
    else:
        cat_data["last_winner"], cat_data["count"] = winner_name, 1
    save_json(STREAKS_PATH, all_streaks)
    badge = " `👑` " if cat_data["count"] >= 5 else f" `🔥 {cat_data['count']}` "
    return badge

def create_fields(ranking, category, streak_badge):
    fields = []
    max_xp = ranking[0][1]
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    for i, (name, xp_val) in enumerate(ranking[:3]):
        percent = (xp_val / max_xp) if max_xp > 0 else 0
        bar = "🟩" * round(percent * 10) + "⬛" * (10 - round(percent * 10))
        pb = check_pb(category, name, xp_val)
        fields.append({"name": f"{medals[i]} **{name}{pb}{streak_badge if i==0 else ''}**", "value": f"`+{xp_val:,} XP`\n{bar} `{int(percent*100)}%`", "inline": False})
    
    others = [f"`{idx}.` **{n}** (`+{v:,} XP`){check_pb(category, n, v)}" for idx, (n, v) in enumerate(ranking[3:], 4) if v > 0]
    if others: fields.append({"name": "--- Other Gains ---", "value": "\n".join(others)})
    return fields

# --- MAIN ---
def main():
    target_date = get_target_date()
    print(f"🎯 Target Date: {target_date}")
    
    if not CHAR_FILE.exists(): return
    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]
    
    all_xp = load_json(JSON_PATH, {})
    
    for name in chars:
        xp_gain = scrape_tibiaring(name, target_date)
        if xp_gain:
            if name not in all_xp: all_xp[name] = {}
            all_xp[name][target_date] = xp_gain
            print(f"✅ {name}: {xp_gain}")
            
    save_json(JSON_PATH, all_xp)
    
    # Process Daily Ranking
    rank_d = sorted([(n, int(d[target_date].replace(",","").replace("+",""))) for n, d in all_xp.items() if target_date in d], key=lambda x: x[1], reverse=True)
    rank_d = [r for r in rank_d if r[1] > 0]

    if rank_d:
        badge = update_streak("daily", rank_d[0][0])
        payload = {
            "embeds": [{
                "title": "🏆 Daily XP Champions 🏆",
                "description": f"🗓️ Date: **{target_date}**",
                "fields": create_fields(rank_d, "daily", badge),
                "color": 0x2ecc71,
                "footer": {"text": "Data sourced from TibiaRing"}
            }]
        }
        
        state = load_json(POST_STATE_PATH, {})
        if state.get("daily") != target_date:
            post_to_discord(payload)
            mark_posted("daily", target_date)
            print("🚀 Discord post sent!")

if __name__ == "__main__":
    main()
