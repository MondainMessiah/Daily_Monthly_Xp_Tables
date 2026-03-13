import os
import json
import asyncio
import random
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
TIMEZONE = "Europe/London"

def get_target_date():
    """Strictly targets yesterday's date, as Tibia server saves reflect the previous day."""
    return (datetime.now(ZoneInfo(TIMEZONE)) - timedelta(days=1)).strftime("%Y-%m-%d")

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

# --- STEALTH SCRAPER ---
async def scrape_xp_tab9(char_name, page, target_date):
    url = f"https://guildstats.eu/character?nick={char_name.replace(' ', '+')}&tab=9"
    for attempt in range(2):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=40000)
            await asyncio.sleep(3) # Let JavaScript build the table
            await page.wait_for_selector("#tabs1 > .newTable", timeout=15000)
            
            soup = BeautifulSoup(await page.content(), "html.parser")
            table = soup.select_one("#tabs1 > .newTable")
            
            char_data = {}
            if table:
                for row in table.find_all("tr")[1:]:
                    tds = row.find_all("td")
                    if len(tds) >= 2:
                        char_data[tds[0].get_text(strip=True)] = tds[1].get_text(strip=True)
            
            if target_date in char_data:
                print(f"✅ {char_name}: Found {target_date}")
                return char_data
            
            return {}
        except Exception as e:
            print(f"⚠️ {char_name} (Attempt {attempt+1}): {type(e).__name__}")
            await asyncio.sleep(3)
    return {}

# --- LOGIC & FORMATTING FUNCTIONS ---
def check_pb(category, name, current_xp):
    pbs = load_json(PB_PATH, {"daily": {}, "weekly": {}, "monthly": {}})
    cat_pbs = pbs.setdefault(category, {})
    record = cat_pbs.get(name, 0)
    if current_xp > record:
        cat_pbs[name] = current_xp
        save_json(PB_PATH, pbs)
        if record > 0: return " `⭐` "
    return ""

def update_streak(category, winner_name):
    all_streaks = load_json(STREAKS_PATH, {"daily": {}, "weekly": {}, "monthly": {}})
    cat_data = all_streaks.get(category, {"last_winner": "", "count": 0})
    old_winner, old_count = cat_data["last_winner"], cat_data["count"]
    msg = ""
    
    if old_winner == winner_name:
        cat_data["count"] += 1
        if cat_data["count"] == 5: 
            msg = f"\n👑 **{winner_name}** earned the Crown!"
    else:
        if old_winner and old_count >= 3: 
            msg = f"\n⚔️ **{winner_name}** ended **{old_winner}**'s `{old_count}` win streak!"
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
    
    legend = "\n⭐ = New PB | 🔥 = 1-4 Streak | 👑 = 5+ Streak"
    return f"Team Total: {current_total:,} XP{p_str}{legend}", color

def create_fields(ranking, category, streak_badge):
    fields = []
    if not ranking: return fields
    max_xp = ranking[0][1]
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    
    for i, (name, xp_val) in enumerate(ranking[:3]):
        percent = (xp_val / max_xp) if max_xp > 0 else 0
        bar = "🟩" * round(percent * 10) + "⬛" * (10 - round(percent * 10))
        pb = check_pb(category, name, xp_val)
        
        fields.append({
            "name": f"{medals[i]} **{name}{pb}{streak_badge if i==0 else ''}**", 
            "value": f"`+{xp_val:,} XP`\n{bar} `{int(percent*100)}%`", 
            "inline": False
        })
        
    others = [f"`{idx}.` **{n}** (`+{v:,} XP`){check_pb(category, n, v)}" for idx, (n, v) in enumerate(ranking[3:], start=4) if v > 0]
    if others: fields.append({"name": "--- Other Gains ---", "value": "\n".join(others), "inline": False})
    return fields

# --- MAIN ENGINE ---
async def main():
    target_date = get_target_date()
    print(f"🎯 Target: {target_date}")
    
    if not CHAR_FILE.exists(): 
        error_msg = f"❌ ERROR: Cannot find the file at {CHAR_FILE}"
        print(error_msg)
        post_to_discord({"content": f"🚨 **Bot Error:** I cannot find the `characters.txt` file."})
        return

    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]
    
    all_xp = load_json(JSON_PATH, {})
    
    async with async_playwright() as p:
        for name in chars:
            # 1. Launch a completely fresh browser for EVERY character
            browser = await p.chromium.launch(headless=True, args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox"
            ])
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                viewport={'width': 1920, 'height': 1080}
            )
            page = await context.new_page()
            
            # 2. Scrape the character
            new_data = await scrape_xp_tab9(name, page, target_date)
            
            if new_data:
                if name not in all_xp: all_xp[name] = {}
                all_xp[name].update(new_data)
                
            # 3. Completely close the browser to wipe the session
            await context.close()
            await browser.close()
            
            # 4. Wait a random amount of time before launching the next browser
            delay = random.uniform(4.0, 8.0)
            print(f"💤 Resting for {delay:.1f}s to avoid bot detection...")
            await asyncio.sleep(delay) 
            
    save_json(JSON_PATH, all_xp)
    
    rank_d = sorted([(n, int(d[target_date].replace(",","").replace("+",""))) for n, d in all_xp.items() if target_date in d], key=lambda x: x[1], reverse=True)
    rank_d = [r for r in rank_d if r[1] > 0]

    if rank_d:
        badge, announce = update_streak("daily", rank_d[0][0])
        footer, color = calculate_growth("daily", sum(r[1] for r in rank_d))
        post_to_discord({
            "embeds": [{
                "title": "🏆 Daily Champion 🏆", 
                "description": f"🗓️ Date: {target_date}{announce}", 
                "fields": create_fields(rank_d, "daily", badge), 
                "color": color, 
                "footer": {"text": footer}
            }]
        })
        print("✅ Discord embed posted successfully!")
    else:
        print(f"⚠️ No data found for {target_date}.")
        post_to_discord({"content": f"⚠️ **Data Missing:** GuildStats has not updated the highscores for `{target_date}` yet. I'll try again on the next scheduled run."})

if __name__ == "__main__":
    asyncio.run(main())
