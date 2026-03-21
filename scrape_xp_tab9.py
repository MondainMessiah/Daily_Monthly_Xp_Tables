import os
import json
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
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

def has_posted(category, date_str):
    state = load_json(POST_STATE_PATH, {})
    return state.get(category) == date_str

def mark_posted(category, date_str):
    state = load_json(POST_STATE_PATH, {})
    state[category] = date_str
    save_json(POST_STATE_PATH, state)

# --- SCRAPER ---
async def scrape_tibiarise(char_name, page, site_date):
    formatted_name = char_name.replace(' ', '%20')
    url = f"https://tibiarise.app/en/characters/{formatted_name}"
    iso_key, _ = get_target_date_info()
    
    try:
        print(f"🔍 Loading {char_name}...")
        await page.goto(url, wait_until="networkidle", timeout=60000)
        
        # Human-like behavior: Scroll
        await page.mouse.wheel(0, 500)
        await asyncio.sleep(3)
        
        # Check if the text actually exists
        content = await page.content()
        if site_date in content:
            rows = await page.locator("tr").all()
            for row in rows:
                row_text = await row.inner_text()
                if site_date in row_text:
                    cells = await row.locator("td").all_inner_texts()
                    if len(cells) >= 2:
                        raw_xp = cells[1].replace(",", "").replace("+", "").replace(" ", "").strip()
                        if raw_xp.isdigit():
                            val = int(raw_xp)
                            print(f"✅ {char_name}: Found {val:,} XP")
                            return {iso_key: f"+{val:,}"}
        
        # If we got here, it failed. TAKE SCREENSHOT.
        clean_name = char_name.replace(" ", "_")
        await page.screenshot(path=f"debug_{clean_name}.png", full_page=True)
        print(f"⚠️ {char_name}: Data not found. Screenshot saved as debug_{clean_name}.png")

    except Exception as e:
        print(f"⚠️ {char_name}: Error - {str(e)}")
    return {}

async def main():
    iso_key, site_date = get_target_date_info()
    if has_posted("daily", iso_key): return 

    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]
    all_xp = load_json(JSON_PATH, {})
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # SUPER STEALTH CONTEXT
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080}
        )
        
        # Inject script to hide bot status
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.chrome = { runtime: {} };
        """)
        
        page = await context.new_page()
        for name in chars:
            new_data = await scrape_tibiarise(name, page, site_date)
            if new_data:
                if name not in all_xp: all_xp[name] = {}
                all_xp[name].update(new_data)
            await asyncio.sleep(2)
        await browser.close()
            
    save_json(JSON_PATH, all_xp)
    
    # Simple post check
    rank_d = []
    for n, d in all_xp.items():
        if iso_key in d:
            val = int(d[iso_key].replace(",","").replace("+",""))
            rank_d.append((n, val))
    
    if any(r[1] > 0 for r in rank_d):
        # (Formatting logic same as before)
        post_to_discord({"content": f"✅ Scraped data for {iso_key}!"}) 
        mark_posted("daily", iso_key)

if __name__ == "__main__":
    asyncio.run(main())
