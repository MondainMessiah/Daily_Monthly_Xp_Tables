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

def get_target_date_info():
    dt = datetime.now(ZoneInfo(TIMEZONE)) - timedelta(days=1)
    return dt.strftime("%Y-%m-%d"), dt.strftime("%d/%m/%Y")

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

# --- TIBIARISE DATA EXTRACTOR ---
async def scrape_tibiarise(char_name, session, site_date):
    formatted_name = char_name.replace(' ', '%20')
    url = f"https://tibiarise.app/en/characters/{formatted_name}"
    iso_key, _ = get_target_date_info()
    
    try:
        print(f"📡 Requesting {char_name} via curl_cffi...")
        response = await session.get(url, timeout=15)
        
        if response.status_code != 200:
            print(f"⚠️ {char_name}: HTTP {response.status_code} block.")
            return {}

        # Look for the hidden JSON data in the HTML
        soup = BeautifulSoup(response.text, "html.parser")
        script_tag = soup.find("script", id="__NEXT_DATA__")
        
        if script_tag:
            data = json.loads(script_tag.string)
            # Find the XP history in the massive JSON blob
            # We search recursively for any key that looks like an XP list
            history = str(data)
            
            # Use Regex to find the date and the number next to it
            # TibiaRise JSON usually looks like {"date":"20/03/2026","experienceGained":123456}
            pattern = rf'"{site_date}"[^}}]+?experienceGained":(\d+)'
            match = re.search(pattern, history)
            
            if match:
                val = int(match.group(1))
                formatted_xp = f"+{val:,}"
                print(f"✅ {char_name}: Found {site_date} -> {formatted_xp} XP")
                return {iso_key: formatted_xp}
        
        # Fallback: Search the raw HTML text for the date
        print(f"⚠️ {char_name}: JSON not found, trying raw text search...")
        if site_date in response.text:
            # Look for a number immediately following the date in the raw text
            text_match = re.search(rf'{site_date}.*?(\d[\d,]*)', response.text)
            if text_match:
                print(f"✅ {char_name}: Found via raw text!")
                return {iso_key: f"+{text_match.group(1)}"}

    except Exception as e:
        print(f"⚠️ {char_name}: Error - {str(e)}")
    return {}

async def main():
    iso_key, site_date = get_target_date_info()
    print(f"🎯 Target: {iso_key} (Searching for: {site_date})")
    
    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]
    all_xp = load_json(JSON_PATH, {})
    
    async with AsyncSession(impersonate="chrome120") as session:
        for name in chars:
            new_data = await scrape_tibiarise(name, session, site_date)
            if new_data:
                if name not in all_xp: all_xp[name] = {}
                all_xp[name].update(new_data)
            await asyncio.sleep(1)
            
    save_json(JSON_PATH, all_xp)
    
    # Check if we should post
    rank_d = []
    for n, d in all_xp.items():
        if iso_key in d:
            val = int(d[iso_key].replace(",","").replace("+",""))
            rank_d.append((n, val))
    
    if any(r[1] > 0 for r in rank_d):
        post_to_discord({"content": f"🏆 **Daily XP Update for {iso_key}**\nData successfully pulled from TibiaRise!"})
        print("✅ Discord notified!")

if __name__ == "__main__":
    asyncio.run(main())
