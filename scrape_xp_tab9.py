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
        "euro": dt.strftime("%d/%m/%Y"),
        "short": dt.strftime("%-d/%-m/%Y") # Handles 20/3/2026
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

# --- THE DEEP SCANNER ---
async def scrape_tibiarise(char_name, session, target):
    slug = char_name.replace(' ', '%20')
    # Trying the plural version which is more common for character lists
    url = f"https://tibiarise.app/en/characters/{slug}"
    iso_key = target["iso"]
    
    try:
        print(f"📡 Requesting: {url}")
        response = await session.get(url, timeout=20)
        
        # DEBUG: What is the title of the page we got?
        soup = BeautifulSoup(response.text, "html.parser")
        title = soup.title.string if soup.title else "No Title"
        print(f"📄 Page Title: {title}")

        if "Verify" in title or "Cloudflare" in title:
            print(f"❌ {char_name}: Blocked by a Bot Verification screen.")
            return {}

        # SEARCH 1: The "Everything" Search
        # We look for the date and the NEXT number that looks like XP
        patterns = [target["euro"], target["iso"], target["short"]]
        for p in patterns:
            # This looks for the date, then skips characters until it finds a number
            match = re.search(rf'{p}.*?(\+?[0-9,]{{4,}})', response.text, re.DOTALL)
            if match:
                val = match.group(1).replace(",", "").replace("+", "")
                print(f"✅ {char_name}: Found {val} XP via Deep Search!")
                return {iso_key: f"+{int(val):,}"}

        # SEARCH 2: The Table Row Search (BeautifulSoup)
        for tr in soup.find_all("tr"):
            row_text = tr.get_text(" ", strip=True)
            if any(p in row_text for p in patterns):
                tds = tr.find_all("td")
                if len(tds) >= 2:
                    xp_text = tds[1].get_text(strip=True).replace(",", "").replace("+", "")
                    if xp_text.isdigit():
                        print(f"✅ {char_name}: Found {xp_text} XP in table!")
                        return {iso_key: f"+{int(xp_text):,}"}

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
    
    # Simple check for Discord
    rank = [n for n, d in all_xp.items() if iso in d]
    if rank:
        print(f"🎉 Success! Found data for {len(rank)} characters.")
    else:
        print("❌ Final Attempt: No data found.")

if __name__ == "__main__":
    asyncio.run(main())
