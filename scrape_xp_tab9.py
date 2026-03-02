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
TIMEZONE = "Europe/London"

# --- HELPER FUNCTIONS ---
def timestamp():
    """Returns a formatted timestamp string for logging."""
    return datetime.now(ZoneInfo(TIMEZONE)).strftime("[%Y-%m-%d %H:%M:%S]")

def xp_str_to_int(xp_str):
    """Converts a formatted XP string (e.g., '+1,234,567') to an integer."""
    try:
        return int(xp_str.replace(",", "").replace("+", "").strip())
    except (ValueError, AttributeError):
        return 0

def get_ordinal(n):
    """Returns the ordinal string for a number (e.g., 1st, 2nd, 3rd, 4th)."""
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
    print(f"{timestamp()} Saved data to {path}.")

def post_to_discord_embed(title, description, fields=None, color=0xf1c40f, footer=""):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print(f"{timestamp()} ERROR: DISCORD_WEBHOOK_URL not set.")
        return

    embed = {"title": title, "description": description, "color": color}
    if footer:
        embed["footer"] = {"text": footer}
    if fields:
        embed["fields"] = fields

    try:
        resp = requests.post(webhook_url, json={"embeds": [embed]}, timeout=10)
        if resp.status_code not in (200, 204):
            print(f"{timestamp()} ERROR: Discord post failed! Status: {resp.status_code}")
    except Exception as e:
        print(f"{timestamp()} ERROR: Exception posting to Discord: {e}")

# --- SCRAPING LOGIC ---

async def scrape_xp_tab9(char_name, page):
    url = f"https://guildstats.eu/character?nick={char_name.replace(' ', '+')}&tab=9"
    print(f"{timestamp()} Scraping {char_name}")
    try:
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_selector("#tabs1 > .newTable", timeout=15000)
    except Exception:
        print(f"{timestamp()} No XP table found for {char_name}.")
        return {}

    content = await page.content()
    soup = BeautifulSoup(content, "html.parser")
    table = soup.select_one("#tabs1 > .newTable")
    if not table: return {}

    xp_data = {tds[0].get_text(strip=True): tds[1].get_text(strip=True) 
               for row in table.find_all("tr")[1:] 
               if len((tds := row.find_all("td"))) >= 2}
    return xp_data

# --- REPORTING LOGIC ---

def run_daily_report(all_xp):
    print(f"{timestamp()} --- Starting Daily Report ---")
    latest_dates = [max(xp.keys()) for xp in all_xp.values() if xp]
    if not latest_dates: return

    latest_date = max(latest_dates)
    daily_ranking = []
    for name, xp_data in all_xp.items():
        xp_raw = xp_data.get(latest_date)
        if xp_raw and "+" in xp_raw:
            xp_val = xp_str_to_int(xp_raw)
            if xp_val > 0:
                daily_ranking.append((name, xp_val))

    if not daily_ranking:
        post_to_discord_embed("Tibia Daily XP", f"No XP gains on {latest_date}.", color=0x636e72)
        return

    daily_ranking.sort(key=lambda x: x[1], reverse=True)
    
    medals = ["🥇", "🥈", "🥉"]
    fields = [
        {"name": f"{(medals[i] if i < 3 else get_ordinal(i + 1))} **{name}**", "value": f"+{xp_val:,} XP", "inline": False}
        for i, (name, xp_val) in enumerate(daily_ranking)
    ]
    post_to_discord_embed(
        "🟡🟢🔵 Tibia Daily XP Leaderboard 🔵🟢🟡",
        f"👑 **Top Gainer:** **{daily_ranking[0][0]}**\n🗓️ **Date:** {latest_date}",
        fields=fields, color=0xf1c40f
    )

    # Personal Bests Check
    best_daily = load_json(BEST_DAILY_XP_PATH, {})
    updated = False
    for name, xp_val in daily_ranking:
        if xp_val > best_daily.get(name, {}).get("xp", 0):
            best_daily[name] = {"xp": xp_val, "date": latest_date}
            updated = True
            post_to_discord_embed(
                "🏅 New Personal Best!",
                f"**{name}** just set a new record: **+{xp_val:,} XP** on {latest_date}! 🚀",
                color=0x2ecc71, footer="Tibia XP Tracker"
            )
    if updated: save_json(BEST_DAILY_XP_PATH, best_daily)

def run_weekly_report(all_xp):
    """Calculates and posts the PREVIOUS week's gains every Monday morning."""
    print(f"{timestamp()} --- Checking for Weekly Report ---")
    today = datetime.now(ZoneInfo(TIMEZONE))

    # ONLY RUN ON MONDAY (0)
    if today.weekday() != 0:
        print(f"{timestamp()} Not Monday. Skipping weekly summary.")
        return

    # Range: Last Monday to Last Sunday
    start_last_week = (today - timedelta(days=7)).strftime("%Y-%m-%d")
    end_last_week = (today - timedelta(days=1)).strftime("%Y-%m-%d")

    weekly_ranking = []
    for name, xp_data in all_xp.items():
        total = sum(xp_str_to_int(xp) for date, xp in xp_data.items() 
                    if start_last_week <= date <= end_last_week and "+" in xp)
        if total > 0:
            weekly_ranking.append((name, total))

    if not weekly_ranking:
        print(f"{timestamp()} No weekly gains found.")
        return

    weekly_ranking.sort(key=lambda x: x[1], reverse=True)
    medals = ["🥇", "🥈", "🥉"]
    fields = [
        {"name": f"{(medals[i] if i < 3 else get_ordinal(i + 1))} **{name}**", "value": f"Total: **+{xp_val:,} XP**", "inline": False}
        for i, (name, xp_val) in enumerate(weekly_ranking)
    ]

    post_to_discord_embed(
        "🏆 Tibia Weekly XP Champion 🏆",
        f"Final results for **{start_last_week}** to **{end_last_week}**!\n\n👑 **Weekly Winner:** **{weekly_ranking[0][0]}**",
        fields=fields, color=0x1abc9c, footer="Tibia Weekly XP Tracker"
    )

def run_monthly_report(all_xp):
    today = datetime.now(ZoneInfo(TIMEZONE))
    if today.day != 1: return

    last_day_prev = today.replace(day=1) - timedelta(days=1)
    prev_month_str = last_day_prev.strftime("%Y-%m")
    prev_month_name = last_day_prev.strftime("%B %Y")

    monthly_ranking = []
    for name, xp_data in all_xp.items():
        total = sum(xp_str_to_int(xp) for date, xp in xp_data.items() if date.startswith(prev_month_str) and "+" in xp)
        if total > 0: monthly_ranking.append((name, total))

    if not monthly_ranking: return
    monthly_ranking.sort(key=lambda x: x[1], reverse=True)
    
    medals = ["🥇", "🥈", "🥉"]
    fields = [
        {"name": f"{(medals[i] if i < 3 else get_ordinal(i + 1))} **{name}**", "value": f"Total: **+{total_xp:,} XP**", "inline": False}
        for i, (name, total_xp) in enumerate(monthly_ranking)
    ]
    post_to_discord_embed(
        f"🏆 Tibia Monthly Report: {prev_month_name} 🏆",
        f"Monthly summary for {prev_month_name}!\n\n👑 **Month Champion:** **{monthly_ranking[0][0]}**",
        fields=fields, color=0x3498db
    )

# --- MAIN EXECUTION ---

async def main():
    print(f"{timestamp()} Script started.")
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
    run_weekly_report(all_xp) # Correctly gated for Monday
    run_monthly_report(all_xp)
    print(f"{timestamp()} Script finished.")

if __name__ == "__main__":
    asyncio.run(main())
