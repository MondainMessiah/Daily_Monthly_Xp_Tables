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
POST_STATE_PATH = BASE_DIR / "post_state.json"
TIMEZONE = "Europe/London"

def get_date_formats():
    """Returns a list of possible date formats found on TibiaRing."""
    dt = datetime.now(ZoneInfo(TIMEZONE)) - timedelta(days=1)
    return [
        dt.strftime("%Y-%m-%d"), # 2026-03-20
        dt.strftime("%d.%m.%Y"), # 20.03.2026
        dt.strftime("%d-%m-%Y")  # 20-03-2026
    ]

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

# --- TIBIARING SCRAPER ---
def scrape_tibiaring(char_name, target_formats):
    # TibiaRing uses '+' for spaces in URLs
    url = f"https://www.tibiaring.com/char.php?c={char_name.replace(' ', '+')}&lang=en"
    iso_date = target_formats[0]
    
    try:
        print(f"🔍 Checking: {char_name}...")
        response = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
        if response.status_code != 200:
            print(f"⚠️ {char_name}: HTTP {response.status_code}")
            return None

        soup = BeautifulSoup(response.text, "html.parser")
        
        # We search every table row for our date
        found_any_history = False
        for row in soup.find_all("tr"):
            row_text = row.get_text()
            # If the row contains ANY of our date formats...
            if any(fmt in row_text for fmt in target_formats):
                cells = row.find_all("td")
                if len(cells) >= 3:
                    # TibiaRing Format: [Date] [Level] [XP Gain]
                    # We grab the 3rd column (index 2)
                    raw_xp = cells[2].get_text(strip=True).replace(",", "").replace("+", "").replace(" ", "")
                    if raw_xp.isdigit():
                        print(f"✅ {char_name}: Found {int(raw_xp):,} XP")
                        return f"+{int(raw_xp):,}"
                found_any_history = True
        
        if not found_any_history:
            print(f"ℹ️ {char_name}: History table seen, but {iso_date} isn't listed yet.")
            
    except Exception as e:
        print(f"⚠️ {char_name} Error: {e}")
    return None

# --- RANKING & EMBEDS ---
def update_streak(category, winner):
    streaks = load_json(STREAKS_PATH, {"daily": {}})
    data = streaks["daily"].setdefault(winner, {"last_winner": "", "count": 0})
    # Simplified streak logic for this test run
    return " `🔥` "

def create_fields(rank):
    fields = []
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    for i, (name, xp) in enumerate(rank[:3]):
        fields.append({"name": f"{medals[i]} **{name}**", "value": f"`+{xp:,} XP`", "inline": False})
    
    others = [f"**{n}** (`+{v:,}`)" for n, v in rank[3:] if v > 0]
    if others: fields.append({"name": "--- Others ---", "value": ", ".join(others)})
    return fields

# --- MAIN ---
def main():
    target_formats = get_date_formats()
    iso_date = target_formats[0]
    print(f"🎯 Target: {iso_date}")
    
    if not CHAR_FILE.exists(): return
    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]
    
    all_xp = load_json(JSON_PATH, {})
    new_entries = False

    for name in chars:
        gain = scrape_tibiaring(name, target_formats)
        if gain:
            if name not in all_xp: all_xp[name] = {}
            all_xp[name][iso_date] = gain
            new_entries = True
            
    if new_entries:
        save_json(JSON_PATH, all_xp)
        
        # Create Ranking
        rank = sorted([(n, int(d[iso_date].replace(",","").replace("+",""))) 
                       for n, d in all_xp.items() if iso_date in d], 
                      key=lambda x: x[1], reverse=True)
        
        # Only post if someone gained XP
        if any(r[1] > 0 for r in rank):
            payload = {
                "embeds": [{
                    "title": "🏆 Daily XP Champions 🏆",
                    "description": f"🗓️ Date: **{iso_date}**",
                    "fields": create_fields(rank),
                    "color": 0x2ecc71,
                    "footer": {"text": "Data via TibiaRing"}
                }]
            }
            
            state = load_json(POST_STATE_PATH, {})
            if state.get("daily") != iso_date:
                post_to_discord(payload)
                state["daily"] = iso_date
                save_json(POST_STATE_PATH, state)
                print("🚀 Discord post sent!")
    else:
        print("😴 No data found to post yet.")

if __name__ == "__main__":
    main()
