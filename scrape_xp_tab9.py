import os
import json
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import requests

# --- SETTINGS & PATHING ---
BASE_DIR = Path(__file__).resolve().parent
CHAR_FILE = BASE_DIR / "characters.txt"
JSON_PATH = BASE_DIR / "xp_log.json"
PB_PATH = BASE_DIR / "personal_bests.json"
STREAKS_PATH = BASE_DIR / "streaks.json"
TOTALS_HISTORY_PATH = BASE_DIR / "totals_history.json"
POST_STATE_PATH = BASE_DIR / "post_state.json"
TIMEZONE = "Europe/London"

def get_target_dates():
    # Returns a list of potential formats for the target date
    dt = datetime.now(ZoneInfo(TIMEZONE)) - timedelta(days=1)
    return [
        dt.strftime("%Y-%m-%d"),       # 2026-03-20
        dt.strftime("%d.%m.%Y"),       # 20.03.2026
        dt.strftime("%d/%m/%Y"),       # 20/03/2026
        dt.strftime("%b %d, %Y")       # Mar 20, 2026
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

def has_posted(category, date_str):
    state = load_json(POST_STATE_PATH, {})
    return state.get(category) == date_str

def mark_posted(category, date_str):
    state = load_json(POST_STATE_PATH, {})
    state[category] = date_str
    save_json(POST_STATE_PATH, state)

# --- TIBIARISE PLAYWRIGHT SCRAPER ---
async def scrape_tibiarise(char_name, page, target_formats):
    formatted_name = char_name.replace(' ', '%20')
    url = f"https://tibiarise.app/en/characters/{formatted_name}"
    iso_date = target_formats[0] # We store in JSON as YYYY-MM-DD
    
    try:
        print(f"🔍 Visiting: {url}")
        await page.goto(url, wait_until="domcontentloaded", timeout=40000)
        
        # Wait for any table to appear (TibiaRise uses them for history)
        try:
            await page.wait_for_selector("table", timeout=15000)
        except:
            print(f"⚠️ {char_name}: No table appeared after 15s.")
        
        await asyncio.sleep(3) # Final rest for React rendering
        
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")
        
        # Look through all tables on the page
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            for row in rows:
                row_text = row.get_text(separator=" ", strip=True)
                
                # Check if ANY of our date formats are in this row
                if any(fmt in row_text for fmt in target_formats):
                    tds = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
                    
                    # Look for the XP column (usually has a + or is a large number)
                    for td in tds:
                        clean_val = td.replace(",", "").replace(" ", "").replace("+", "").strip()
                        if clean_val.isdigit() and (int(clean_val) > 1000):
                            xp_str = f"+{int(clean_val):,}"
                            print(f"✅ {char_name}: Found data ({xp_str})")
                            return {iso_date: xp_str}
                            
        print(f"⚠️ {char_name}: Could not find a row matching {target_formats[0]}")
        return {}

    except Exception as e:
        print(f"⚠️ {char_name}: ERROR - {str(e)}")
    return {}

# --- REMAINDER OF SCRIPT (LOGIC & MAIN) ---
# [No changes needed to streak/PB/main logic, just keep it the same as the previous script]
