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
PB_PATH = BASE_DIR / "personal_bests.json"
STREAKS_PATH = BASE_DIR / "streaks.json"
TOTALS_HISTORY_PATH = BASE_DIR / "totals_history.json"
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

# --- TIBIARISE SMART PATHFINDER ---
async def scrape_tibiarise(char_name, session, site_date):
    slug = char_name.replace(' ', '%20')
    lower_slug = char_name.lower().replace(' ', '%20')
    
    # We try every possible combination of URL paths
    urls_to_try = [
        f"https://tibiarise.app/en/characters/{slug}",
        f"https://tibiarise.app/characters/{slug}",
        f"https://tibiarise.app/en/character/{slug}",
        f"https://tibiarise.app/character/{slug}",
        f"https://tibiarise.app/en/characters/{lower_slug}",
        f"https://tibiarise.app/characters/{lower_slug}"
    ]
    
    iso_key, _ = get_target_date_info()
    
    for url in urls_to_try:
        try:
            response = await session.get(url, timeout=10)
            
            if response.status_code == 200:
                print(f"🔗 Successful URL: {url}")
                
                # Extract hidden JSON data
                soup = BeautifulSoup(response.text, "html.parser")
                script_tag = soup.find("script", id="__NEXT_DATA__")
                
                if script_tag:
                    raw_json = script_tag.string
                    # Pattern for: "20/03/2026" ... "experienceGained":123456
                    pattern = rf'"{site_date}".*?"experienceGained":(\d+)'
                    match = re.search(pattern, raw_json)
                    
                    if match:
                        val = int(match.group(1))
                        print(f"✅ {char_name}: Found {val:,} XP")
                        return {iso_key: f"+{val:,}"}
                
                # Fallback text search
                if site_date in response.text:
                    text_match = re.search(rf'{site_date}.*?(\d[\d,]*)', response.text)
                    if text_match:
                        val = text_match.group(1).replace(",", "")
                        print(f"✅ {char_name}: Found {val} XP via text search")
                        return {iso_key: f"+{int(val):,}"}
                
                print(f"⚠️ {char_name}: Page loaded but {site_date} isn't in history yet.")
                return {} 
                
        except Exception:
            continue
            
    print(f"❌ {char_name}: No valid URL found (Tried {len(urls_to_try)} variations).")
    return {}

# --- MAIN ---
async def main():
    iso_key, site_date = get_target_date_info()
    print(f"🎯 Target: {iso_key} (Searching for: {site_date})")
    
    if not CHAR_FILE.exists():
        print("❌ Error: characters.txt not found")
        return

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
    
    # Process Ranking
    rank_d = []
    for n, d in all_xp.items():
        if iso_key in d:
            val = int(d[iso_key].replace(",","").replace("+",""))
            rank_d.append((n, val))
    
    if any(r[1] > 0 for r in rank_d):
        rank_d.sort(key=lambda x: x[1], reverse=True)
        top = rank_d[0]
        msg = f"🏆 **Daily Champion:** {top[0]} (`+{top[1]:,} XP`)\n(Scraped from TibiaRise)"
        post_to_discord({"content": msg})
        print("✅ Discord notified!")
    else:
        print("😴 No gains found today.")

if __name__ == "__main__":
    asyncio.run(main())
