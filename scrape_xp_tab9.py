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

# --- TIBIARISE STEALTH SCRAPER ---
async def scrape_tibiarise(char_name, page, site_date):
    formatted_name = char_name.replace(' ', '%20')
    url = f"https://tibiarise.app/en/characters/{formatted_name}"
    iso_key, _ = get_target_date_info()
    
    try:
        print(f"🔍 Loading {char_name}...")
        # Go to page and wait for basic load
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        
        # TRICK 1: Scroll down to trigger lazy-loading of the table
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
        await asyncio.sleep(2)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        
        # TRICK 2: Wait for the "Experience on last 30 days" header
        try:
            await page.wait_for_selector("text=Experience", timeout=20000)
        except:
            print(f"⚠️ {char_name}: Header 'Experience' didn't load.")
            return {}

        await asyncio.sleep(3) 
        
        # TRICK 3: Find the row by text content (more robust than CSS selectors)
        rows = await page.get_by_role("row").all()
        for row in rows:
            text = await row.inner_text()
            if site_date in text:
                cells = await row.get_by_role("cell").all_inner_texts()
                if len(cells) >= 2:
                    # Column 1 is XP Gained
                    raw_xp = cells[1].replace(",", "").replace("+", "").replace(" ", "").strip()
                    if raw_xp.isdigit():
                        val = int(raw_xp)
                        formatted_xp = f"+{val:,}"
                        print(f"✅ {char_name}: Found {site_date} -> {formatted_xp} XP")
                        return {iso_key: formatted_xp}
                        
        print(f"⚠️ {char_name}: Found the page, but date {site_date} isn't in the table yet.")
    except Exception as e:
        print(f"⚠️ {char_name}: Error - {str(e)}")
    return {}

# --- FORMATTING LOGIC ---
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
    old_winner, old_count = cat_data["last_winner"], cat_data["count"]
    msg = ""
    if old_winner == winner_name:
        cat_data["count"] += 1
        if cat_data["count"] == 5: msg = f"\n👑 **{winner_name}** earned the Crown!"
    else:
        if old_winner and old_count >= 3: msg = f"\n⚔️ **{winner_name}** ended **{old_winner}**'s `{old_count}` win streak!"
        cat_data["last_winner"], cat_data["count"] = winner_name, 1
    save_json(STREAKS_PATH, all_streaks)
    badge = " `👑` " if cat_data["count"] >= 5 else f" `🔥 {cat_data['count']}` "
    return badge, msg

def calculate_growth(category, current_total):
    history = load_json(TOTALS_HISTORY_PATH, {})
    prev = history.get(category, 0)
    p_str, color = "", 0xf1c40f 
    if prev > 0:
        pc = ((current_total - prev) / prev) * 100
        p_str = f" ({'+' if pc >= 0 else ''}{pc:.1f}% vs last {category})"
        color = 0x2ecc71 if pc > 0 else 0xe74c3c
    history[category] = current_total
    save_json(TOTALS_HISTORY_PATH, history)
    return f"Team Total: {current_total:,} XP{p_str}\n⭐ = PB | 🔥 = Streak | 👑 = Crown", color

def create_fields(ranking, category, streak_badge):
    fields = []
    if not ranking: return fields
    max_xp = ranking[0][1]
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    for i, (name, xp_val) in enumerate(ranking[:3]):
        percent = (xp_val / max_xp) if max_xp > 0 else 0
        bar = "🟩" * round(percent * 10) + "⬛" * (10 - round(percent * 10))
        pb = check_pb(category, name, xp_val)
        fields.append({"name": f"{medals[i]} **{name}{pb}{streak_badge if i==0 else ''}**", "value": f"`+{xp_val:,} XP`\n{bar} `{int(percent*100)}%`", "inline": False})
    others = [f"`{idx}.` **{n}** (`+{v:,} XP`){check_pb(category, n, v)}" for idx, (n, v) in enumerate(ranking[3:], start=4) if v > 0]
    if others: fields.append({"name": "--- Other Gains ---", "value": "\n".join(others), "inline": False})
    return fields

# --- MAIN ---
async def main():
    iso_key, site_date = get_target_date_info()
    today = datetime.now(ZoneInfo(TIMEZONE))
    
    if has_posted("daily", iso_key):
        print(f"⏩ Already posted for {iso_key}. Skipping.")
        return 

    print(f"🎯 Target: {iso_key} (Searching for: {site_date})")
    
    if not CHAR_FILE.exists():
        print("❌ Error: characters.txt not found.")
        return
        
    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]
    all_xp = load_json(JSON_PATH, {})
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # TRICK 4: Full Stealth Context
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 800},
            java_script_enabled=True
        )
        # Remove the 'webdriver' flag
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        page = await context.new_page()
        
        for name in chars:
            new_data = await scrape_tibiarise(name, page, site_date)
            if new_data:
                if name not in all_xp: all_xp[name] = {}
                all_xp[name].update(new_data)
            await asyncio.sleep(3)
        await browser.close()
            
    save_json(JSON_PATH, all_xp)
    
    rank_d = []
    for n, d in all_xp.items():
        if iso_key in d:
            val = int(d[iso_key].replace(",","").replace("+",""))
            rank_d.append((n, val))
    
    if any(r[1] > 0 for r in rank_d):
        rank_d.sort(key=lambda x: x[1], reverse=True)
        badge, announce = update_streak("daily", rank_d[0][0])
        footer, color = calculate_growth("daily", sum(r[1] for r in rank_d))
        post_to_discord({
            "embeds": [{
                "title": "🏆 Daily Champion 🏆", 
                "description": f"🗓️ Date: {iso_key}{announce}", 
                "fields": create_fields(rank_d, "daily", badge), 
                "color": color, 
                "footer": {"text": footer}
            }]
        })
        mark_posted("daily", iso_key)
        print("✅ Daily leaderboard posted!")
    else:
        print("😴 No XP gains found for this date. No post sent.")

if __name__ == "__main__":
    asyncio.run(main())
