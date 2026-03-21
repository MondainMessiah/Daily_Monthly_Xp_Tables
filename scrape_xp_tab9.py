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
    """Returns the ISO key for JSON and the matching format for the website."""
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

# --- TIBIARISE SCRAPER ---
async def scrape_tibiarise(char_name, page, site_date):
    formatted_name = char_name.replace(' ', '%20')
    url = f"https://tibiarise.app/en/characters/{formatted_name}"
    iso_key, _ = get_target_date_info()
    
    try:
        print(f"🔍 Checking: {char_name}...")
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        
        # Wait for table rows
        try:
            await page.wait_for_selector("table tr", timeout=15000)
        except:
            print(f"⚠️ {char_name}: Table didn't render.")
            return {}

        await asyncio.sleep(2) 
        soup = BeautifulSoup(await page.content(), "html.parser")
        
        for row in soup.find_all("tr"):
            tds = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
            if len(tds) < 2: continue
            
            # Match the date exactly (e.g., 20/03/2026)
            if site_date in tds[0]:
                raw_xp = tds[1].replace(",", "").replace("+", "").replace(" ", "").strip()
                if raw_xp.isdigit() or (raw_xp.startswith('-') and raw_xp[1:].isdigit()):
                    val = int(raw_xp)
                    formatted_xp = f"+{val:,}" if val >= 0 else f"{val:,}"
                    print(f"✅ {char_name}: Found {tds[0]} -> {formatted_xp} XP")
                    return {iso_key: formatted_xp}
                        
        print(f"⚠️ {char_name}: Date {site_date} not found in history.")
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

    print(f"🎯 Target: {iso_key} (Searching site for: {site_date})")
    
    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]
    all_xp = load_json(JSON_PATH, {})
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        page = await context.new_page()
        
        for name in chars:
            new_data = await scrape_tibiarise(name, page, site_date)
            if new_data:
                if name not in all_xp: all_xp[name] = {}
                all_xp[name].update(new_data)
            await asyncio.sleep(2)
        await browser.close()
            
    save_json(JSON_PATH, all_xp)
    
    # Process Daily
    rank_d = sorted([(n, int(d[iso_key].replace(",","").replace("+",""))) for n, d in all_xp.items() if iso_key in d], key=lambda x: x[1], reverse=True)
    rank_d = [r for r in rank_d if r[1] >= 0] # Include 0s

    if any(r[1] > 0 for r in rank_d):
        badge, announce = update_streak("daily", rank_d[0][0])
        footer, color = calculate_growth("daily", sum(r[1] for r in rank_d))
        post_to_discord({"embeds": [{"title": "🏆 Daily Champion 🏆", "description": f"🗓️ Date: {iso_key}{announce}", "fields": create_fields(rank_d, "daily", badge), "color": color, "footer": {"text": footer}}]})
        mark_posted("daily", iso_key)
        print("✅ Daily embed posted!")
    else:
        print("😴 Found data, but everyone had 0 XP gain. No post sent.")

if __name__ == "__main__":
    asyncio.run(main())
