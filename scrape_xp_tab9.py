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
    """Returns the date of the most recent Tibia Server Save."""
    now = datetime.now(ZoneInfo(TIMEZONE))
    # If it's before 10:00 AM, the most recent save was yesterday
    if now.hour < 10:
        return (now - timedelta(days=1)).strftime("%Y-%m-%d")
    return now.strftime("%Y-%m-%d")

def load_json(path, fallback):
    if path.exists():
        try:
            with open(path, "r") as f: return json.load(f)
        except: pass
    return fallback

def save_json(path, data):
    with open(path, "w") as f: json.dump(data, f, indent=2)

# --- REFINED SCRAPER ---
async def scrape_xp_tab9(char_name, page, target_date):
    url = f"https://guildstats.eu/character?nick={char_name.replace(' ', '+')}&tab=9"
    try:
        # Increased timeout and wait for network to settle
        await page.goto(url, wait_until="networkidle", timeout=60000)
        await page.wait_for_selector("#tabs1 > .newTable", timeout=20000)
        
        soup = BeautifulSoup(await page.content(), "html.parser")
        table = soup.select_one("#tabs1 > .newTable")
        
        rows = table.find_all("tr")[1:]
        char_data = {}
        for row in rows:
            tds = row.find_all("td")
            if len(tds) >= 2:
                date_str = tds[0].get_text(strip=True)
                xp_str = tds[1].get_text(strip=True)
                char_data[date_str] = xp_str
        
        if target_date in char_data:
            print(f"✅ Found {target_date} for {char_name}: {char_data[target_date]}")
        else:
            print(f"⚠️ {target_date} NOT found for {char_name}. Latest on site: {list(char_data.keys())[0] if char_data else 'None'}")
            
        return char_data
    except Exception as e:
        print(f"❌ Error scraping {char_name}: {e}")
        return {}

# --- UPDATED RANKING LOGIC ---
def update_streak(category, winner_name):
    all_streaks = load_json(STREAKS_PATH, {"daily": {}, "weekly": {}, "monthly": {}})
    cat_data = all_streaks.get(category, {"last_winner": "", "count": 0})
    old_winner = cat_data["last_winner"]
    old_count = cat_data["count"]
    streak_msg = ""

    if old_winner == winner_name:
        cat_data["count"] += 1
        if cat_data["count"] == 5:
            streak_msg = f"\n👑 **{winner_name}** has reached a 5-win streak and earned the Crown!"
    else:
        if old_winner and old_count >= 3:
            streak_msg = f"\n⚔️ **{winner_name}** ended **{old_winner}**'s `{old_count}` win streak!"
        cat_data["last_winner"] = winner_name
        cat_data["count"] = 1
    
    all_streaks[category] = cat_data
    save_json(STREAKS_PATH, all_streaks)
    badge = " `👑` " if cat_data["count"] >= 5 else f" `🔥 {cat_data['count']}` "
    return badge, streak_msg

def calculate_growth(category, current_total):
    history = load_json(TOTALS_HISTORY_PATH, {})
    prev_total = history.get(category, 0)
    percent_str = ""
    color = 0xf1c40f 
    if prev_total > 0:
        diff = current_total - prev_total
        percent_change = (diff / prev_total) * 100
        percent_str = f" ({'+' if percent_change >= 0 else ''}{percent_change:.1f}% vs prev {category})"
        color = 0x2ecc71 if percent_change > 0 else 0xe74c3c
    history[category] = current_total
    save_json(TOTALS_HISTORY_PATH, history)
    legend = "\n⭐ = New PB\n🔥 = 1-4 Streak\n👑 = 5+ Streak"
    return f"Team Total: {current_total:,} XP{percent_str}{legend}", color

def check_pb(category, name, current_xp):
    pbs = load_json(PB_PATH, {"daily": {}, "weekly": {}, "monthly": {}})
    cat_pbs = pbs.setdefault(category, {})
    record = cat_pbs.get(name, 0)
    if current_xp > record:
        cat_pbs[name] = current_xp
        save_json(PB_PATH, pbs)
        return " `⭐` " if record > 0 else ""
    return ""

def create_fields(ranking, category, streak_badge=""):
    fields = []
    if not ranking: return fields
    max_xp = ranking[0][1]
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    for i, (name, xp_val) in enumerate(ranking[:3]):
        percent = (xp_val / max_xp) if max_xp > 0 else 0
        bar = "🟩" * round(percent * 10) + "⬛" * (10 - round(percent * 10))
        pb = check_pb(category, name, xp_val)
        fields.append({
            "name": f"{medals[i]} **{name}{pb}{streak_badge if i == 0 else ''}**",
            "value": f"`+{xp_val:,} XP`\n{bar} `{int(percent*100)}%`",
            "inline": False
        })
    if len(ranking) > 3:
        others = [f"`{idx}.` **{n}** (`+{v:,} XP`){check_pb(category, n, v)}" for idx, (n, v) in enumerate(ranking[3:], start=4) if v > 0]
        if others: fields.append({"name": "--- Other Gains ---", "value": "\n".join(others), "inline": False})
    return fields

def post_to_discord(title, description, fields, color, footer):
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url: return
    requests.post(url, json={"embeds": [{"title": title, "description": description, "fields": fields, "color": color, "footer": {"text": footer}}]}, timeout=10)

# --- MAIN ENGINE ---
async def main():
    target_date = get_target_date()
    print(f"🎯 Target Date for today's run: {target_date}")
    
    if not CHAR_FILE.exists(): return
    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]
    
    all_xp = load_json(JSON_PATH, {})
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0")
        page = await context.new_page()
        
        for name in chars:
            new_data = await scrape_xp_tab9(name, page, target_date)
            if name not in all_xp: all_xp[name] = {}
            all_xp[name].update(new_data)
            await asyncio.sleep(1.5)
        await browser.close()
    
    save_json(JSON_PATH, all_xp)
    
    # Process Ranking based on Target Date
    rank_d = []
    for name, dates in all_xp.items():
        if target_date in dates:
            val = int(dates[target_date].replace(",", "").replace("+", ""))
            if val > 0: rank_d.append((name, val))
    
    rank_d.sort(key=lambda x: x[1], reverse=True)
    
    if rank_d:
        badge, announce = update_streak("daily", rank_d[0][0])
        footer, color = calculate_growth("daily", sum(r[1] for r in rank_d))
        post_to_discord("🏆 Daily Champion 🏆", f"🗓️ Date: {target_date}{announce}", create_fields(rank_d, "daily", badge), color, footer)
    else:
        print(f"⚠️ No XP data found for {target_date}. Discord post skipped.")

if __name__ == "__main__":
    asyncio.run(main())
