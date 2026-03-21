import os
import json
import asyncio
import re
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
POST_STATE_PATH = BASE_DIR / "post_state.json"
TIMEZONE = "Europe/London"

def get_target_info():
    dt = datetime.now(ZoneInfo(TIMEZONE)) - timedelta(days=1)
    return {
        "iso": dt.strftime("%Y-%m-%d"),
        "euro": dt.strftime("%d/%m/%Y"), # 20/03/2026
        "short": dt.strftime("%-d/%-m/%Y") # 20/3/2026
    }

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

async def scrape_tibiarise(char_name, session, target):
    slug = char_name.replace(' ', '%20')
    # FIXED: Reverted to singular 'character'
    url = f"https://tibiarise.app/en/character/{slug}"
    iso_key = target["iso"]
    
    try:
        print(f"📡 Requesting: {url}")
        response = await session.get(url, timeout=20)
        
        if response.status_code != 200:
            print(f"❌ {char_name}: Received HTTP {response.status_code}")
            return {}

        # SEARCH: Look for the date and the gain
        # We search the raw text for the date followed by a large number (XP)
        patterns = [target["euro"], target["iso"], target["short"]]
        for p in patterns:
            # This regex looks for the date, then skips characters until it finds a number (+1,234,567)
            # It avoids 3-digit numbers (Levels) by looking for 4+ digits
            match = re.search(rf'{p}.*?([0-9,]{{4,}})', response.text, re.DOTALL)
            if match:
                val = match.group(1).replace(",", "")
                print(f"✅ {char_name}: Found {int(val):,} XP")
                return {iso_key: f"+{int(val):,}"}

        print(f"⚠️ {char_name}: Date {target['euro']} not found in source.")
        
    except Exception as e:
        print(f"⚠️ {char_name}: Error - {str(e)}")
    return {}

async def main():
    target = get_target_info()
    iso = target["iso"]
    print(f"🎯 Target: {iso} (Searching for: {target['euro']})")
    
    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]
    all_xp = load_json(JSON_PATH, {})
    
    async with AsyncSession(impersonate="chrome120") as session:
        for name in chars:
            new_data = await scrape_tibiarise(name, session, target)
            if new_data:
                all_xp.setdefault(name, {}).update(new_data)
            await asyncio.sleep(2)
            
    save_json(JSON_PATH, all_xp)
    
    # Simple check for results
    found = [n for n, d in all_xp.items() if iso in d]
    if found:
        print(f"🎉 Success! Found data for: {', '.join(found)}")
        # You can add your Discord ranking logic back here if this works!
    else:
        print("❌ Still no data found. The site might not have yesterday's logs ready yet.")

if __name__ == "__main__":
    asyncio.run(main())
