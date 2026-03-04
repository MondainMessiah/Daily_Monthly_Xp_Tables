import os
import json
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import requests

# --- DYNAMIC PATHING ---
BASE_DIR = Path(__file__).resolve().parent
CHAR_FILE = BASE_DIR / "characters.txt"
JSON_PATH = BASE_DIR / "xp_log.json"
PB_PATH = BASE_DIR / "personal_bests.json"
STREAKS_PATH = BASE_DIR / "streaks.json"
TOTALS_HISTORY_PATH = BASE_DIR / "totals_history.json"
TIMEZONE = "Europe/London"

# --- HELPER FUNCTIONS ---
def timestamp():
    return datetime.now(ZoneInfo(TIMEZONE)).strftime("[%Y-%m-%d %H:%M:%S]")

def load_json(path, fallback):
    if path.exists():
        try:
            with open(path, "r") as f: return json.load(f)
        except: pass
    return fallback

def save_json(path, data):
    with open(path, "w") as f: json.dump(data, f, indent=2)

def check_pb(category, name, current_xp):
    pbs = load_json(PB_PATH, {"daily": {}, "weekly": {}, "monthly": {}})
    cat_pbs = pbs.setdefault(category, {})
    record = cat_pbs.get(name, 0)
    if current_xp > record:
        cat_pbs[name] = current_xp
        save_json(PB_PATH, pbs)
        if record > 0: return " ⭐" # Space for padding
    return ""

def update_streak(category, winner_name):
    all_streaks = load_json(STREAKS_PATH, {"daily": {}, "weekly": {}, "monthly": {}})
    cat_data = all_streaks.get(category, {"last_winner": "", "count": 0})
    
    old_winner = cat_data["last_winner"]
    old_count = cat_data["count"]
    broken_msg = ""

    if old_winner == winner_name:
        cat_data["count"] += 1
    else:
        # Announce if a significant streak (3+) is broken
        if old_winner and old_count >= 3:
            broken_msg = f"\n⚔️ **{winner_name}** ended **{old_winner}**'s `{old_count}` win streak!"
        cat_data["last_winner"] = winner_name
        cat_data["count"] = 1
    
    all_streaks[category] = cat_data
    save_json(STREAKS_PATH, all_streaks)
    
    count = cat_data["count"]
    # 1-4 is 🔥, 5+ is 👑 with black background
    badge = f" `👑 {count}`" if count >= 5 else f" `🔥 {count}`"
    return badge, broken_msg

def calculate_growth(category, current_total):
    history = load_json(TOTALS_HISTORY_PATH, {})
    prev_total = history.get(category, 0)
    
    percent_str = ""
    color = 0xf1c40f # Default Gold
    
    if prev_total > 0:
        diff = current_total - prev_total
        percent_change = (diff / prev_total) * 100
        prefix = "+" if percent_change >= 0 else ""
        # Black background for %
        percent_str = f" (`{prefix}{percent_change:.1f}%` vs prev {category})"
        
        if percent_change > 0: color = 0x2ecc71 # Green
        elif percent_change < 0: color = 0xe74c3c # Red
    
    history[category] = current_total
    save_json(TOTALS_HISTORY_PATH, history)
    
    legend = "\n⭐ = New PB\n🔥 = 1-4 Win Streak\n👑 = 5+ Win Streak"
    return f"Team Total: `{current_total:,} XP`{percent_str}{legend}", color

def create_fields(ranking, category, streak_badge=""):
    fields = []
    if not ranking: return fields
    max_xp = ranking[0][1]
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}

    for i, (name, xp_val) in enumerate(ranking[:3]):
        percent = (xp_val / max_xp) if max_xp > 0 else 0
        num_green = round(percent * 10)
        bar = "🟩" * num_green + "⬛" * (10 - num_green)
        pb_badge = check_pb(category, name, xp_val)
        
        # Winner gets the streak badge
        badges = f"{pb_badge}{streak_badge if i == 0 else ''}"
        display_name = f"{name}{badges}"
        
        fields.append({
            "name": f"{medals[i]} **{display_name}**",
            "value": f"`+{xp_val:,} XP`\n{bar} `{int(percent*100)}%`",
            "inline": False
        })
    
    if len(ranking) > 3:
        others = []
        for idx, (n, v) in enumerate(ranking[3:], start=4):
            if v > 0:
                pb = check_pb(category, n, v)
                others.append(f"`{idx}.` **{n}** (`+{v:,} XP`){pb}")
        if others:
            fields.append({"name": "--- Other Gains ---", "value": "\n".join(others), "inline": False})
    return fields

def post_to_discord_embed(title, description, fields=None, color=0xf1c40f, footer=""):
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url: return
    payload = {"embeds": [{"title": title, "description": description, "fields": fields, "color": color, "footer": {"text": footer}}]}
    try: requests.post(url, json=payload, timeout=10)
    except: pass

async def scrape_xp_tab9(char_name, page):
    url = f"https://guildstats.eu/character?nick={char_name.replace(' ', '+')}&tab=9"
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_selector("#tabs1 > .newTable", timeout=15000)
        soup = BeautifulSoup(await page.content(), "html.parser")
        table = soup.select_one("#tabs1 > .newTable")
        return {tds[0].get_text(strip=True): tds[1].get_text(strip=True) for row in table.find_all("tr")[1:] if len((tds := row.find_all("td"))) >= 2}
    except: return {}

async def main():
    print(f"--- Process Started at {timestamp()} ---")
    if not CHAR_FILE.exists(): return

    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]
    
    # Load history to merge rather than overwrite
    all_xp = load_json(JSON_PATH, {})
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        for name in chars:
            new_data = await scrape_xp_tab9(name, page)
            if name not in all_xp: all_xp[name] = {}
            all_xp[name].update(new_data)
            print(f"🔍 Scraped {name}")
            await asyncio.sleep(1)
        await browser.close()
    
    save_json(JSON_PATH, all_xp)
    
    # Run Daily
    dates = [max(xp.keys()) for xp in all_xp.values() if xp]
    if dates:
        latest = max(dates)
        rank_d = sorted([(n, int(xp.get(latest).replace(",", "").replace("+", ""))) for n, xp in all_xp.items() if xp.get(latest) and "+" in xp.get(latest)], key=lambda x: x[1], reverse=True)
        if rank_d:
            badge, broken = update_streak("daily", rank_d[0][0])
            footer_txt, embed_color = calculate_growth("daily", sum(r[1] for r in rank_d))
            post_to_discord_embed("🏆 Daily Champion 🏆", f"🗓️ Date: {latest}{broken}", create_fields(rank_d, "daily", badge), embed_color, footer_txt)

    # Run Weekly (Mondays)
    from datetime import datetime, timedelta
    today = datetime.now(ZoneInfo(TIMEZONE))
    if today.weekday() == 0:
        s, e = (today - timedelta(days=7)).strftime("%Y-%m-%d"), (today - timedelta(days=1)).strftime("%Y-%m-%d")
        rank_w = sorted([(n, sum(int(v.replace(",", "").replace("+", "")) for d, v in xp.items() if s <= d <= e and "+" in v)) for n, xp in all_xp.items() if xp], key=lambda x: x[1], reverse=True)
        rank_w = [r for r in rank_w if r[1] > 0]
        if rank_w:
            badge, broken = update_streak("weekly", rank_w[0][0])
            footer_txt, embed_color = calculate_growth("weekly", sum(r[1] for r in rank_w))
            post_to_discord_embed("🏆 Weekly Champion 🏆", f"🗓️ {s} to {e}{broken}", create_fields(rank_w, "weekly", badge), embed_color, footer_txt)

    # Run Monthly (1st of the month)
    if today.day == 1:
        prev_month = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        rank_m = sorted([(n, sum(int(v.replace(",", "").replace("+", "")) for d, v in xp.items() if d.startswith(prev_month) and "+" in v)) for n, xp in all_xp.items() if xp], key=lambda x: x[1], reverse=True)
        rank_m = [r for r in rank_m if r[1] > 0]
        if rank_m:
            badge, broken = update_streak("monthly", rank_m[0][0])
            footer_txt, embed_color = calculate_growth("monthly", sum(r[1] for r in rank_m))
            post_to_discord_embed("🏆 Monthly Champion 🏆", f"🗓️ {prev_month}{broken}", create_fields(rank_m, "monthly", badge), embed_color, footer_txt)

    print(f"--- Process Finished at {timestamp()} ---")

if __name__ == "__main__":
    asyncio.run(main())
