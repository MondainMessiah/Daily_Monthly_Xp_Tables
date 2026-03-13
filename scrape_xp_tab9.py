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
TIMEZONE = "Europe/London"

def get_target_date():
    """Strictly yesterday."""
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

# --- SCRAPER ---
async def scrape_xp_tab9(char_name, page, target_date):
    url = f"https://guildstats.eu/character?nick={char_name.replace(' ', '+')}&tab=9"
    for attempt in range(2):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=40000)
            await asyncio.sleep(3) 
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
        except:
            await asyncio.sleep(2)
    return {}

# --- LOGIC ---
def update_streak(category, winner_name):
    all_streaks = load_json(STREAKS_PATH, {"daily": {}, "weekly": {}, "monthly": {}})
    cat_data = all_streaks.get(category, {"last_winner": "", "count": 0})
    old_winner, old_count = cat_data["last_winner"], cat_data["count"]
    msg = ""
    if old_winner == winner_name:
        cat_data["count"] += 1
        if cat_data["count"] == 5: msg = f"\n👑 **{winner_name}** earned the Crown!"
    else:
        if old_winner and old_count >= 3: msg = f"\n⚔️ **{winner_name}** ended **{old_winner}**'s `{old_count}` streak!"
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
    return f"Team Total: {current_total:,} XP{p_str}\n⭐ = New PB | 🔥 = 1-4 Streak | 👑 = 5+ Streak", color

def create_fields(ranking, category, streak_badge):
    fields = []
    max_xp = ranking[0][1]
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    for i, (name, xp_val) in enumerate(ranking[:3]):
        percent = (xp_val / max_xp) if max_xp > 0 else 0
        bar = "🟩" * round(percent * 10) + "⬛" * (10 - round(percent * 10))
        fields.append({"name": f"{medals[i]} **{name}{streak_badge if i==0 else ''}**", "value": f"`+{xp_val:,} XP`\n{bar} `{int(percent*100)}%`", "inline": False})
    others = [f"`{idx}.` **{n}** (`+{v:,} XP`)" for idx, (n, v) in enumerate(ranking[3:], start=4) if v > 0]
    if others: fields.append({"name": "--- Other Gains ---", "value": "\n".join(others), "inline": False})
    return fields

# --- MAIN ---
async def main():
    target_date = get_target_date()
    print(f"🎯 Target: {target_date}")
    if not CHAR_FILE.exists(): return
    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]
    
    all_xp = load_json(JSON_PATH, {})
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = await browser.new_context(user_agent="Mozilla/5.0...")
        page = await context.new_page()
        for name in chars:
            new_data = await scrape_xp_tab9(name, page, target_date)
            if new_data:
                if name not in all_xp: all_xp[name] = {}
                all_xp[name].update(new_data)
            await asyncio.sleep(1.5)
        await browser.close()
    
    save_json(JSON_PATH, all_xp)
    rank_d = sorted([(n, int(d[target_date].replace(",","").replace("+",""))) for n, d in all_xp.items() if target_date in d], key=lambda x: x[1], reverse=True)
    rank_d = [r for r in rank_d if r[1] > 0]

    if rank_d:
        badge, announce = update_streak("daily", rank_d[0][0])
        footer, color = calculate_growth("daily", sum(r[1] for r in rank_d))
        post_to_discord({"embeds": [{"title": "🏆 Daily Champion 🏆", "description": f"🗓️ Date: {target_date}{announce}", "fields": create_fields(rank_d, "daily", badge), "color": color, "footer": {"text": footer}}]})
    else:
        # Alert that data is missing
        post_to_discord({"content": f"⚠️ **Data Missing:** GuildStats has not updated the highscores for `{target_date}` yet. I'll try again on the next scheduled run."})

if __name__ == "__main__":
    asyncio.run(main())
