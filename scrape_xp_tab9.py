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
PB_PATH = "personal_bests.json" # Tracks daily, weekly, and monthly PBs
STREAKS_PATH = "streaks.json"
TOTALS_HISTORY_PATH = "totals_history.json"
TIMEZONE = "Europe/London"

# --- HELPER FUNCTIONS ---
def load_json(path, fallback):
    if os.path.exists(path):
        try:
            with open(path, "r") as f: return json.load(f)
        except: pass
    return fallback

def save_json(path, data):
    with open(path, "w") as f: json.dump(data, f, indent=2)

def check_pb(category, name, current_xp):
    """Checks if current XP is a Personal Best. Returns suffix if true."""
    pbs = load_json(PB_PATH, {})
    cat_pbs = pbs.get(category, {})
    old_pb = cat_pbs.get(name, 0)
    
    if current_xp > old_pb and old_pb > 0:
        cat_pbs[name] = current_xp
        pbs[category] = cat_pbs
        save_json(PB_PATH, pbs)
        return " ⭐ **New PB!**"
    
    if name not in cat_pbs: # Initialize PB if they don't have one
        cat_pbs[name] = current_xp
        pbs[category] = cat_pbs
        save_json(PB_PATH, pbs)
    
    return ""

def update_streak(category, winner_name):
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

def calculate_growth(category, current_total):
    history = load_json(TOTALS_HISTORY_PATH, {})
    prev_total = history.get(category, 0)
    diff = current_total - prev_total
    prefix = "+" if diff >= 0 else ""
    history[category] = current_total
    save_json(TOTALS_HISTORY_PATH, history)
    if prev_total == 0:
        return f"Team Total: {current_total:,} XP"
    return f"Team Total: {current_total:,} XP ({prefix}{diff:,} vs prev {category})"

def create_fields(ranking, category, streak_text=""):
    fields = []
    if not ranking: return fields
    max_xp = ranking[0][1]
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}

    for i, (name, xp_val) in enumerate(ranking[:3]):
        percent = (xp_val / max_xp) if max_xp > 0 else 0
        num_green = round(percent * 10)
        bar = "🟩" * num_green + "⬛" * (10 - num_green)
        
        pb_badge = check_pb(category, name, xp_val)
        display_name = f"{name}{streak_text}{pb_badge}" if i == 0 else f"{name}{pb_badge}"
        
        fields.append({
            "name": f"{medals[i]} **{display_name}**",
            "value": f"+{xp_val:,} XP\n{bar} `{int(percent*100)}%`",
            "inline": False
        })

    if len(ranking) > 3:
        others_list = []
        for idx, (n, v) in enumerate(ranking[3:], start=4):
            if v > 0:
                pb_badge = check_pb(category, n, v)
                others_list.append(f"`{idx}.` **{n}** (+{v:,} XP){pb_badge}")
        
        if others_list:
            fields.append({"name": "--- Other Gains ---", "value": "\n".join(others_list), "inline": False})
    return fields

def post_to_discord_embed(title, description, fields=None, color=0xf1c40f, footer=""):
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url: return
    payload = {"embeds": [{"title": title, "description": description, "fields": fields, "color": color, "footer": {"text": footer}}]}
    try: requests.post(url, json=payload, timeout=10)
    except: pass

# --- SCRAPING (Helper from previous) ---
def xp_str_to_int(xp_str):
    try: return int(xp_str.replace(",", "").replace("+", "").strip())
    except: return 0

async def scrape_xp_tab9(char_name, page):
    url = f"https://guildstats.eu/character?nick={char_name.replace(' ', '+')}&tab=9"
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_selector("#tabs1 > .newTable", timeout=15000)
        soup = BeautifulSoup(await page.content(), "html.parser")
        table = soup.select_one("#tabs1 > .newTable")
        return {tds[0].get_text(strip=True): tds[1].get_text(strip=True) for row in table.find_all("tr")[1:] if len((tds := row.find_all("td"))) >= 2}
    except: return {}

# --- REPORTS ---
def run_daily_report(all_xp):
    dates = [max(xp.keys()) for xp in all_xp.values() if xp]
    if not dates: return
    latest = max(dates)
    ranking = sorted([(n, xp_str_to_int(xp.get(latest))) for n, xp in all_xp.items() if xp.get(latest) and "+" in xp.get(latest)], key=lambda x: x[1], reverse=True)
    if not ranking: return
    
    total_group_xp = sum(r[1] for r in ranking)
    footer_text = calculate_growth("daily", total_group_xp)
    count = update_streak("daily", ranking[0][0])
    streak = f" ({count}x 🥇)" if count > 1 else ""
    post_to_discord_embed("🏆 Daily Champion 🏆", f"🗓️ **Date:** {latest}", create_fields(ranking, "daily", streak), 0xf1c40f, footer_text)

def run_weekly_report(all_xp):
    today = datetime.now(ZoneInfo(TIMEZONE))
    if today.weekday() != 0: return 
    s, e = (today - timedelta(days=7)).strftime("%Y-%m-%d"), (today - timedelta(days=1)).strftime("%Y-%m-%d")
    ranking = sorted([(n, sum(xp_str_to_int(v) for d, v in xp.items() if s <= d <= e and "+" in v)) for n, xp in all_xp.items()], key=lambda x: x[1], reverse=True)
    ranking = [r for r in ranking if r[1] > 0]
    if not ranking: return
    
    total_group_xp = sum(r[1] for r in ranking)
    footer_text = calculate_growth("weekly", total_group_xp)
    count = update_streak("weekly", ranking[0][0])
    streak = f" ({count}x 🥇)" if count > 1 else ""
    post_to_discord_embed("🏆 Weekly Champion 🏆", f"🗓️ {s} to {e}", create_fields(ranking, "weekly", streak), 0x2ecc71, footer_text)

def run_monthly_report(all_xp):
    today = datetime.now(ZoneInfo(TIMEZONE))
    if today.day != 1: return
    prev_month_date = (today.replace(day=1) - timedelta(days=1))
    prev_str = prev_month_date.strftime("%Y-%m")
    ranking = sorted([(n, sum(xp_str_to_int(v) for d, v in xp.items() if d.startswith(prev_str) and "+" in v)) for n, xp in all_xp.items()], key=lambda x: x[1], reverse=True)
    ranking = [r for r in ranking if r[1] > 0]
    if not ranking: return
    
    total_group_xp = sum(r[1] for r in ranking)
    footer_text = calculate_growth("monthly", total_group_xp)
    count = update_streak("monthly", ranking[0][0])
    streak = f" ({count}x 🥇)" if count > 1 else ""
    post_to_discord_embed("🏆 Monthly Champion 🏆", f"🗓️ {prev_month_date.strftime('%B %Y')}", create_fields(ranking, "monthly", streak), 0x3498db, footer_text)

async def main():
    if not os.path.exists(CHAR_FILE): return
    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]
    all_xp = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        for name in chars:
            all_xp[name] = await scrape_xp_tab9(name, page)
            await asyncio.sleep(1)
        await browser.close()
    save_json(JSON_PATH, all_xp)
    run_daily_report(all_xp)
    run_weekly_report(all_xp)
    run_monthly_report(all_xp)

if __name__ == "__main__": asyncio.run(main())
