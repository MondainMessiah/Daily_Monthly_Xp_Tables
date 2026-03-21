import os
import json
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
import requests

# --- SETTINGS ---
BASE_DIR = Path(__file__).resolve().parent
CHAR_FILE = BASE_DIR / "characters.txt"
JSON_PATH = BASE_DIR / "xp_log.json"
PB_PATH = BASE_DIR / "personal_bests.json"
STREAKS_PATH = BASE_DIR / "streaks.json"
POST_STATE_PATH = BASE_DIR / "post_state.json"
TIMEZONE = "Europe/London"

def get_date_formats():
    dt = datetime.now(ZoneInfo(TIMEZONE)) - timedelta(days=1)
    return [
        dt.strftime("%Y-%m-%d"), # 2026-03-20
        dt.strftime("%d.%m.%Y"), # 20.03.2026
        dt.strftime("%d/%m/%Y")  # 20/03/2026
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

# --- TIBIARING STEALTH SCRAPER ---
async def scrape_tibiaring(char_name, session, target_formats):
    # TibiaRing URL format
    url = f"https://www.tibiaring.com/char.php?c={char_name.replace(' ', '+')}&lang=en"
    iso_date = target_formats[0]
    
    try:
        print(f"🔍 Checking: {char_name}...")
        # Impersonate Chrome to bypass the 403 Forbidden error
        response = await session.get(url, timeout=15)
        
        if response.status_code != 200:
            print(f"⚠️ {char_name}: Received HTTP {response.status_code}")
            return None

        soup = BeautifulSoup(response.text, "html.parser")
        
        # Hunt for the date in the table rows
        for row in soup.find_all("tr"):
            row_text = row.get_text()
            if any(fmt in row_text for fmt in target_formats):
                cells = row.find_all("td")
                if len(cells) >= 3:
                    # Index 2 is typically the XP Gain
                    raw_xp = cells[2].get_text(strip=True).replace(",", "").replace("+", "").replace(" ", "")
                    if raw_xp.isdigit():
                        print(f"✅ {char_name}: Found +{int(raw_xp):,} XP")
                        return f"+{int(raw_xp):,}"
        
        print(f"ℹ️ {char_name}: Page loaded, but {iso_date} isn't in the list yet.")
    except Exception as e:
        print(f"⚠️ {char_name} Error: {str(e)}")
    return None

# --- EMBED LOGIC ---
def create_fields(rank):
    fields = []
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    for i, (name, xp) in enumerate(rank[:3]):
        fields.append({"name": f"{medals.get(i, '🔹')} **{name}**", "value": f"`+{xp:,} XP`", "inline": False})
    
    others = [f"**{n}** (`+{v:,}`)" for n, v in rank[3:] if v > 0]
    if others:
        fields.append({"name": "--- Others ---", "value": ", ".join(others)})
    return fields

# --- MAIN ENGINE ---
async def main():
    target_formats = get_date_formats()
    iso_date = target_formats[0]
    print(f"🎯 Target Date: {iso_date}")
    
    if not CHAR_FILE.exists(): return
    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]
    
    all_xp = load_json(JSON_PATH, {})
    new_entries = False

    # Start the stealth session
    async with AsyncSession(impersonate="chrome120") as session:
        for name in chars:
            gain = await scrape_tibiaring(name, session, target_formats)
            if gain:
                if name not in all_xp: all_xp[name] = {}
                all_xp[name][iso_date] = gain
                new_entries = True
            await asyncio.sleep(1) # Be polite to the server
            
    if new_entries:
        save_json(JSON_PATH, all_xp)
        
        rank = sorted([(n, int(d[iso_date].replace(",","").replace("+",""))) 
                       for n, d in all_xp.items() if iso_date in d], 
                      key=lambda x: x[1], reverse=True)
        
        if any(r[1] > 0 for r in rank):
            state = load_json(POST_STATE_PATH, {})
            if state.get("daily") != iso_date:
                post_to_discord({
                    "embeds": [{
                        "title": "🏆 Daily XP Champions 🏆",
                        "description": f"🗓️ Date: **{iso_date}**",
                        "fields": create_fields(rank),
                        "color": 0x2ecc71,
                        "footer": {"text": "Data via TibiaRing Stealth"}
                    }]
                })
                state["daily"] = iso_date
                save_json(POST_STATE_PATH, state)
                print("🚀 Discord post sent!")
    else:
        print("😴 No gains found to post yet.")

if __name__ == "__main__":
    asyncio.run(main())
