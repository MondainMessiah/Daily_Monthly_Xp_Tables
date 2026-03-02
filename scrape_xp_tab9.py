import os
import json
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import requests

# --- CONFIGURATION ---
CHAR_FILE = "characters.txt"
JSON_PATH = "xp_log.json"
BEST_DAILY_XP_PATH = "best_daily_xp.json"
STREAKS_PATH = "streaks.json" # Now handles daily, weekly, and monthly
TIMEZONE = "Europe/London"

# --- HELPER FUNCTIONS ---
def timestamp():
    return datetime.now(ZoneInfo(TIMEZONE)).strftime("[%Y-%m-%d %H:%M:%S]")

def xp_str_to_int(xp_str):
    try:
        return int(xp_str.replace(",", "").replace("+", "").strip())
    except (ValueError, AttributeError):
        return 0

def get_ordinal(n):
    if 10 <= n % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return f"{n}{suffix}"

def load_json(path, fallback):
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"{timestamp()} Failed to load {path}: {e}")
    return fallback

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def update_streak(category, winner_name):
    """
    Updates and returns streak for a category (daily, weekly, monthly).
    Example: update_streak("weekly", "Ilumine")
    """
    all_streaks = load_json(STREAKS_PATH, {})
    cat_data = all_streaks.get(category, {"last_winner": "", "count": 0})
    
    if cat_data["last_winner"] == winner_name:
        cat_data["count"] += 1
    else:
        cat_data["last_winner"] = winner_name
        cat_data["count"] = 1
        
    all_streaks[category] = cat_data
    save_json(STREAKS_PATH, all_streaks)
    return cat_data["count"]

def post_to_discord_embed(title, description, fields=None, color=0xf1c40f, footer=""):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print(f"{timestamp()} ERROR: DISCORD_WEBHOOK_URL not set.")
        return

    embed = {"title": title, "description": description, "color": color}
    if footer: embed["footer"] = {"text": footer}
    if fields: embed["fields"] = fields

    try:
        resp = requests.post(webhook_url, json={"embeds": [embed]}, timeout=10)
    except Exception as e:
        print(f"{timestamp()} ERROR: Discord failed: {e}")

# --- SCRAPING LOGIC ---

async def scrape_xp_tab9(char_name, page):
    url = f"https://guildstats.eu/character?nick={char_name.replace(' ', '+')}&tab=9"
    try:
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_selector("#tabs1 > .newTable", timeout=15000)
        content = await page.content()
        soup = BeautifulSoup(content, "html.parser")
        table = soup.select_one("#tabs1 > .newTable")
        if not table: return {}
        return {tds[0].get_text(strip=True): tds[1].get_text(strip=True) 
                for row in table.find_all("tr")[1:] 
                if len((tds := row.find_all("td"))) >= 2}
    except Exception:
        return {}

# --- REPORTING LOGIC ---

def run_daily_report(all_xp):
    print(f"{timestamp()} --- Daily Report ---")
    latest_dates = [max(xp.keys()) for xp in all_xp.values() if xp]
    if not latest_dates: return
    latest_date = max(latest_dates)
    
    daily_ranking = []
    for name, xp_data in all_xp.items():
        xp_raw = xp_data.get(latest_date)
        if xp_raw and "+" in xp_raw:
            val = xp_str_to_int(xp_raw)
            if val > 0: daily_ranking.append((name, val))

    if not daily_ranking: return
    daily_ranking.sort(key=lambda x: x[1], reverse=True)
    
    winner = daily_ranking[0][0]
    streak = update_streak("daily", winner)
    streak_txt = f" (🥇x{streak})" if streak > 1 else ""

    fields = [{"name": f"{('🥇' if i==0 else '🥈' if i==1 else '🥉' if i==2 else get_ordinal(i+1))} **{n}**", 
               "value": f"+{v:,} XP", "inline": False} for i, (n, v) in enumerate(daily_ranking)]
    
    post_to_discord_embed(
        "🟡🟢🔵 Tibia Daily XP Leaderboard 🔵🟢🟡",
        f"👑 **Top Gainer:** **{winner}**{streak_txt}\n🗓️ **Date:** {latest_date}",
        fields=fields, color=0xf1c40f
    )

    # Personal Bests
    best_daily = load_json(BEST_DAILY_XP_PATH, {})
    for name, xp_val in daily_ranking:
        if xp_val > best_daily.get(name, {}).get("xp", 0):
            best_daily[name] = {"xp": xp_val, "date": latest_date}
            post_to_discord_embed("🏅 New Personal Best!", f"**{name}** record: **+{xp_val:,} XP**!", color=0x2ecc71)
    save_json(BEST_DAILY_XP_PATH, best_daily)

def run_weekly_report(all_xp):
    today = datetime.now(ZoneInfo(TIMEZONE))
    if today.weekday() != 0: return # Monday check
    
    start_last = (today - timedelta(days=7)).strftime("%Y-%m-%d")
    end_last = (today - timedelta(days=1)).strftime("%Y-%m-%d")

    weekly_ranking = []
    for name, xp_data in all_xp.items():
        total = sum(xp_str_to_int(xp) for date, xp in xp_data.items() if start_last <= date <= end_last and "+" in xp)
        if total > 0: weekly_ranking.append((name, total))

    if not weekly_ranking: return
    weekly_ranking.sort(key=lambda x: x[1], reverse=True)

    winner = weekly_ranking[0][0]
    streak = update_streak("weekly", winner)
    streak_txt = f" (🏆x{streak})" if streak > 1 else ""

    fields = [{"name": f"{('🥇' if i==0 else '🥈' if i==1 else '🥉' if i==2 else get_ordinal(i+1))} **{n}**", 
               "value": f"Total: **+{v:,} XP**", "inline": False} for i, (n, v) in enumerate(weekly_ranking)]

    post_to_discord_embed(
        "🏆 Tibia Weekly XP Champion 🏆",
        f"👑 **Weekly Winner:** **{winner}**{streak_txt}\n📅 {start_last} to {end_last}",
        fields=fields, color=0x1abc9c
    )

def run_monthly_report(all_xp):
    today = datetime.now(ZoneInfo(TIMEZONE))
    if today.day != 1: return

    last_day_prev = today.replace(day=1) - timedelta(days=1)
    prev_month_str = last_day_prev.strftime("%Y-%m")
    
    monthly_ranking = []
    for name, xp_data in all_xp.items():
        total = sum(xp_str_to_int(xp) for date, xp in xp_data.items() if date.startswith(prev_month_str) and "+" in xp)
        if total > 0: monthly_ranking.append((name, total))

    if not monthly_ranking: return
    monthly_ranking.sort(key=lambda x: x[1], reverse=True)
    
    winner = monthly_ranking[0][0]
    streak = update_streak("monthly", winner)
    streak_txt = f" (👑x{streak})" if streak > 1 else ""

    fields = [{"name": f"{('🥇' if i==0 else '🥈' if i==1 else '🥉' if i==2 else get_ordinal(i+1))} **{n}**", 
               "value": f"Total: **+{v:,} XP**", "inline": False} for i, (n, v) in enumerate(monthly_ranking)]

    post_to_discord_embed(
        f"🌟 Monthly Report: {last_day_prev.strftime('%B %Y')} 🌟",
        f"👑 **Month Champion:** **{winner}**{streak_txt}",
        fields=fields, color=0x3498db
    )

# --- MAIN ---
async def main():
    if not os.path.exists(CHAR_FILE): return
    with open(CHAR_FILE) as f:
        characters = [line.strip() for line in f if line.strip()]

    all_xp = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        for name in characters:
            all_xp[name] = await scrape_xp_tab9(name, page)
        await browser.close()
    
    save_json(JSON_PATH, all_xp)
    run_daily_report(all_xp)
    run_weekly_report(all_xp)
    run_monthly_report(all_xp)

if __name__ == "__main__":
    asyncio.run(main())
