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

def get_target_date():
    dt = datetime.now(ZoneInfo(TIMEZONE)) - timedelta(days=1)
    return dt.strftime("%d/%m/%Y") # Matches your screenshot: 20/03/2026

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

# --- TIBIARISE PRECISION SCRAPER ---
async def scrape_tibiarise(char_name, session, date_str):
    slug = char_name.replace(' ', '%20')
    url = f"https://tibiarise.app/en/character/{slug}"
    iso_key = datetime.now(ZoneInfo(TIMEZONE)) - timedelta(days=1)
    iso_key = iso_key.strftime("%Y-%m-%d")

    try:
        print(f"🔍 Accessing: {char_name}...")
        # Using a mobile impersonation which often delivers simpler HTML
        response = await session.get(url, timeout=20)
        
        if response.status_code != 200:
            print(f"❌ {char_name}: Received HTTP {response.status_code}")
            return {}

        soup = BeautifulSoup(response.text, "html.parser")
        
        # We look through every table row
        for tr in soup.find_all("tr"):
            # We get the raw text separated by a pipe to identify columns
            row_content = tr.get_text("|", strip=True)
            
            if date_str in row_content:
                # Based on screenshot: [0] Date | [1] Gain | [2] Level
                parts = row_content.split("|")
                if len(parts) >= 2:
                    raw_val = parts[1].replace(",", "").replace("+", "").strip()
                    if raw_val.isdigit():
                        val = int(raw_val)
                        formatted_xp = f"+{val:,}"
                        print(f"✅ {char_name}: Found {formatted_xp} XP")
                        return {iso_key: formatted_xp}
        
        # DEBUG: If we can't find the date, print a snippet of what we DID find
        print(f"⚠️ {char_name}: Date {date_str} not found. (Check: {soup.title.string})")
        
    except Exception as e:
        print(f"⚠️ {char_name}: Error - {str(e)}")
    return {}

async def main():
    date_str = get_target_date()
    iso_key = (datetime.now(ZoneInfo(TIMEZONE)) - timedelta(days=1)).strftime("%Y-%m-%d")
    
    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]
    all_xp = load_json(JSON_PATH, {})
    
    async with AsyncSession(impersonate="chrome110") as session:
        for name in chars:
            new_data = await scrape_tibiarise(name, session, date_str)
            if new_data:
                all_xp.setdefault(name, {}).update(new_data)
            await asyncio.sleep(2)
            
    save_json(JSON_PATH, all_xp)
    
    # Process Ranking for Discord
    rank = sorted([(n, int(d[iso_key].replace(",","").replace("+",""))) 
                   for n, d in all_xp.items() if iso_key in d], 
                  key=lambda x: x[1], reverse=True)
    
    # Post even if gains are 0, as long as we found data
    if rank:
        if any(r[1] > 0 for r in rank):
            print("🎉 Success! Posting to Discord...")
            # (Insert your ranking/embed logic here)
            post_to_discord({"content": f"✅ Scraped gains for **{iso_key}**!"})
        else:
            print("😴 Data found, but everyone gained 0 XP.")
    else:
        print("❌ No data found for any character today.")

if __name__ == "__main__":
    asyncio.run(main())
