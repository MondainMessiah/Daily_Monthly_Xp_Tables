import os
import json
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo # <-- ADDED THIS IMPORT
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import requests

# --- CONFIGURATION ---
CHAR_FILE = "characters.txt"
JSON_PATH = "xp_log.json"
BEST_DAILY_XP_PATH = "best_daily_xp.json"

# --- HELPER FUNCTIONS ---
def timestamp():
    """Returns a formatted timestamp string for logging."""
    return datetime.now(ZoneInfo("Europe/London")).strftime("[%Y-%m-%d %H:%M:%S]")

def xp_str_to_int(xp_str):
    """Converts a formatted XP string (e.g., '+1,234,567') to an integer."""
    try:
        return int(xp_str.replace(",", "").replace("+", "").strip())
    except (ValueError, AttributeError):
        print(f"{timestamp()} Warning: Could not convert '{xp_str}' to int. Returning 0.")
        return 0

def get_ordinal(n):
    """Returns the ordinal string for a number (e.g., 1st, 2nd, 3rd, 4th)."""
    if 10 <= n % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return f"{n}{suffix}"

def load_json(path, fallback):
    """Loads a JSON file, returning a fallback dictionary if it fails."""
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"{timestamp()} Failed to load {path}: {e}")
    return fallback

def save_json(path, data):
    """Saves a dictionary to a JSON file."""
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"{timestamp()} Saved data to {path}.")

def post_to_discord_embed(title, description, fields=None, color=0xf1c40f, footer=""):
    """Posts a rich embed message to a Discord webhook."""
    print(f"{timestamp()} Posting to Discord. Title: '{title}'")
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print(f"{timestamp()} ERROR: DISCORD_WEBHOOK_URL not set in environment variables.")
        return

    embed = {"title": title, "description": description, "color": color}
    if footer:
        embed["footer"] = {"text": footer}
    if fields:
        embed["fields"] = fields

    try:
        resp = requests.post(webhook_url, json={"embeds": [embed]}, timeout=10)
        if resp.status_code in (200, 204):
            print(f"{timestamp()} Posted to Discord successfully!")
        else:
            print(f"{timestamp()} ERROR: Discord post failed! Status: {resp.status_code}, Response: {resp.text}")
    except Exception as e:
        print(f"{timestamp()} ERROR: Exception posting to Discord: {e}")

# --- SCRAPING LOGIC ---

async def scrape_xp_tab9(char_name, page):
    """Scrapes the experience history for a single character from GuildStats."""
    url = f"https://guildstats.eu/character?nick={char_name.replace(' ', '+')}&tab=9"
    print(f"{timestamp()} Scraping {char_name}")
    try:
        await page.goto(url)
        await page.wait_for_selector("#tabs1 > .newTable", timeout=10000)
    except Exception:
        print(f"{timestamp()} Could not find XP table for {char_name}.")
        return {}

    content = await page.content()
    soup = BeautifulSoup(content, "html.parser")
    table = soup.select_one("#tabs1 > .newTable")
    if not table: return {}

    xp_data = {tds[0].get_text(strip=True): tds[1].get_text(strip=True) for row in table.find_all("tr")[1:] if len((tds := row.find_all("td"))) >= 2}
    print(f"{timestamp()} Scraped {len(xp_data)} entries for {char_name}.")
    return xp_data

# --- REPORTING LOGIC ---

def run_daily_report(all_xp):
    """Calculates and posts the daily XP leaderboard and personal bests."""
    print(f"{timestamp()} --- Starting Daily Report ---")
    
    latest_dates = [max(xp.keys()) for xp in all_xp.values() if xp]
    if not latest_dates:
        print(f"{timestamp()} No valid XP data found. Skipping daily report.")
        return

    latest_date = max(latest_dates)
    daily_ranking = []
    for name, xp_data in all_xp.items():
        xp_raw = xp_data.get(latest_date)
        if xp_raw and "+" in xp_raw:
            xp_val = xp_str_to_int(xp_raw)
            if xp_val > 0:
                daily_ranking.append((name, xp_val))

    if not daily_ranking:
        print(f"{timestamp()} No XP gains found for {latest_date}. Posting notice.")
        post_to_discord_embed("Tibia Daily XP Leaderboard", f"No XP gains on {latest_date}.", color=0x636e72)
        return

    daily_ranking.sort(key=lambda x: x[1], reverse=True)
    
    # Post Daily Leaderboard
    medals = ["🥇", "🥈", "🥉"]
    fields = [
        {"name": f"{(medals[i] if i < 3 else get_ordinal(i + 1))} **{name}**", "value": f"+{xp_val:,} XP", "inline": False}
        for i, (name, xp_val) in enumerate(daily_ranking)
    ]
    post_to_discord_embed(
        "🟡🟢🔵 Tibia Daily XP Leaderboard 🔵🟢🟡",
        f"👑 **Top Gainer:** **{daily_ranking[0][0]}** 👑\n🗓️ **Date:** {latest_date}",
        fields=fields, color=0xf1c40f
    )

    # Check for Personal Bests
    best_daily = load_json(BEST_DAILY_XP_PATH, {})
    updated = False
    for name, xp_val in daily_ranking:
        if xp_val > best_daily.get(name, {}).get("xp", 0):
            print(f"{timestamp()} New personal best for {name}: {xp_val:,} XP")
            best_daily[name] = {"xp": xp_val, "date": latest_date}
            updated = True
            post_to_discord_embed(
                "🏅 New Personal Best!",
                f"**{name}** just achieved a new XP record: **+{xp_val:,} XP** on {latest_date}! 🚀",
                color=0x2ecc71, footer="Tibia XP Tracker"
            )
    if updated:
        save_json(BEST_DAILY_XP_PATH, best_daily)
    print(f"{timestamp()} --- Daily Report Finished ---")

def run_weekly_report(all_xp):
    """Calculates and posts the weekly XP leaderboard."""
    print(f"{timestamp()} --- Starting Weekly Report ---")
    
    # Determine the start and end of the current week
    today = datetime.now(ZoneInfo("Europe/London"))
    start_of_week = today - timedelta(days=today.weekday())  # Monday of the week
    end_of_week = start_of_week + timedelta(days=6)  # Sunday of the week
    week_range = [start_of_week.strftime("%Y-%m-%d"), end_of_week.strftime("%Y-%m-%d")]

    print(f"{timestamp()} Current week: {week_range[0]} - {week_range[1]}")
    
    # Calculate weekly gains
    weekly_ranking = []
    for name, xp_data in all_xp.items():
        weekly_total = sum(
            xp_str_to_int(xp) 
            for date, xp in xp_data.items() 
            if week_range[0] <= date <= week_range[1] and "+" in xp
        )
        if weekly_total > 0:
            weekly_ranking.append((name, weekly_total))

    if not weekly_ranking:
        print(f"{timestamp()} No XP gains recorded for the week. Posting notice.")
        post_to_discord_embed(
            "Tibia Weekly XP Leaderboard",
            f"No XP gains recorded for the week {week_range[0]} - {week_range[1]}.",
            color=0x636e72
        )
        return

    # Sort rankings
    weekly_ranking.sort(key=lambda x: x[1], reverse=True)

    # Create leaderboard
    medals = ["🥇", "🥈", "🥉"]
    fields = [
        {"name": f"{(medals[i] if i < 3 else get_ordinal(i + 1))} **{name}**", "value": f"Weekly Total: **+{xp_val:,} XP**", "inline": False}
        for i, (name, xp_val) in enumerate(weekly_ranking)
    ]

    # Post to Discord
    post_to_discord_embed(
        f"🏆 Tibia Weekly XP Leaderboard 🏆",
        f"Here are the XP gains for the week {week_range[0]} - {week_range[1]}!\n\n👑 **Top Weekly Gainer:** **{weekly_ranking[0][0]}**",
        fields=fields, color=0x1abc9c, footer="Tibia Weekly XP Tracker"
    )
    print(f"{timestamp()} --- Weekly Report Finished ---")

def run_monthly_report(all_xp):
    """On the 1st of the month, calculates and posts the PREVIOUS month's total XP leaderboard."""
    print(f"{timestamp()} --- Checking for Monthly Report ---")
    
    # Use your local timezone to check the date
    today = datetime.now(ZoneInfo("Europe/London")) # <-- MODIFIED THIS LINE

    # This report should only run on the first day of the month.
    if today.day != 1:
        print(f"{timestamp()} Not the 1st of the month ({get_ordinal(today.day)}). Skipping monthly report.")
        return

    print(f"{timestamp()} Today is the 1st! Generating previous month's report.")
    
    # Calculate previous month's date information
    last_day_of_prev_month = today.replace(day=1) - timedelta(days=1)
    prev_month_str = last_day_of_prev_month.strftime("%Y-%m") # e.g., "2025-07"
    prev_month_name = last_day_of_prev_month.strftime("%B %Y") # e.g., "July 2025"
    
    print(f"{timestamp()} Calculating totals for {prev_month_name} ({prev_month_str})")

    monthly_ranking = []
    for name, xp_data in all_xp.items():
        monthly_total = sum(xp_str_to_int(xp) for date, xp in xp_data.items() if date.startswith(prev_month_str) and "+" in xp)
        if monthly_total > 0:
            monthly_ranking.append((name, monthly_total))

    if not monthly_ranking:
        print(f"{timestamp()} No XP gains found for {prev_month_name}.")
        post_to_discord_embed(
            f"🏆 Tibia Monthly Report: {prev_month_name} 🏆",
            "No XP gains were recorded for anyone last month. 😴",
            color=0x95a5a6
        )
        return
        
    monthly_ranking.sort(key=lambda x: x[1], reverse=True)
    
    # Post Monthly Leaderboard
    medals = ["🥇", "🥈", "🥉"]
    fields = [
        {"name": f"{(medals[i] if i < 3 else get_ordinal(i + 1))} **{name}**", "value": f"Total Monthly Gain: **+{total_xp:,} XP**", "inline": False}
        for i, (name, total_xp) in enumerate(monthly_ranking)
    ]
    post_to_discord_embed(
        f"🏆 Tibia Monthly Report: {prev_month_name} 🏆",
        f"Here are the final XP totals for last month!\n\n👑 **Top Gainer of the Month:** **{monthly_ranking[0][0]}**",
        fields=fields, color=0x3498db, footer="Tibia Monthly XP Tracker"
    )
    print(f"{timestamp()} --- Monthly Report Finished ---")

# --- MAIN EXECUTION ---

async def main():
    print(f"{timestamp()} Starting script.")
    if not os.path.exists(CHAR_FILE) or os.path.getsize(CHAR_FILE) == 0:
        print(f"{timestamp()} ERROR: {CHAR_FILE} is missing or empty. Exiting.")
        return
        
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

    # Run the daily report every time
    run_daily_report(all_xp)
    
    # Run the weekly report every time
    run_weekly_report(all_xp)

    # Run the monthly report check every time
    run_monthly_report(all_xp)

    print(f"{timestamp()} Script execution completed.")

if __name__ == "__main__":
    asyncio.run(main())
