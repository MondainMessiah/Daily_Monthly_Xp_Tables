import os
import json
import asyncio
from datetime import datetime, timedelta
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
        return "⭐" if record > 0 else ""
    return ""

def get_next_level_xp_needed(level):
    if level < 1: return 1
    def total_xp_at_lvl(l):
        return (50/3) * (l**3 - 6*l**2 + 17*l - 12)
    return total_xp_at_lvl(level + 1) - total_xp_at_lvl(level)

def update_streak(category, winner_name):
    all_streaks = load_json(STREAKS_PATH, {"daily": {}, "weekly": {}, "monthly": {}})
    cat_data = all_streaks.get(category, {"last_winner": "", "count": 0})
    if cat_data["last_winner"] == winner_name:
        cat_data["count"] += 1
    else:
        cat_data["last_winner"] = winner_name
        cat_data["count"] = 1
    all_streaks[category] = cat_data
    save_json(STREAKS_PATH, all_streaks)
    if cat_data["count"] >= 10: return "👑"
    elif cat_data["count"] > 1: return "🔥" * cat_data["count"]
    return ""

def calculate_growth(category, current_total):
    history = load_json(TOTALS_HISTORY_PATH, {})
    prev_total = history.get(category, 0)
    percent_str, color = "", 0xf1c40f
    if prev_total > 0:
        diff = current_total - prev_total
        p_change = (diff / prev_total) * 100
        percent_str = f" ({'+' if p_change >= 0 else ''}{p_change:.1f}% vs prev {category})"
        color = 0x2ecc71 if p_change >= 0 else 0xe74c3c
    history[category] = current_total
    save_json(TOTALS_HISTORY_PATH, history)
    legend = "\n⭐ = New PB | 🔥 = Streak | 👑 = 10+"
    return f"Team Total: {current_total:,} XP{percent_str}{legend}", color

def create_fields(ranking, category, streak_text=""):
    fields = []
    if not ranking: return fields
    max_xp = ranking[0][1]
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}

    for i, (name, xp_val, lvl) in enumerate(ranking[:3]):
        percent = (xp_val / max_xp) if max_xp > 0 else 0
        bar = "🟩" * round(percent * 10) + "⬛" * (10 - round(percent * 10))
        
        lvl_progress_str = ""
        if lvl > 0:
            req = get_next_level_xp_needed(lvl)
            prog = (xp_val / req) * 100
            lvl_progress_str = f" `(↑ {prog:.1f}% of Lvl {lvl})`"

        pb_badge = check_pb(category, name, xp_val)
        badges = f"{pb_badge}{streak_text if i == 0 else ''}"
        display_name = f"{name} {badges}" if badges else name
        
        fields.append({
            "name": f"{medals[i]} **{display_name}**",
            "value": f"+{xp_val:,} XP{lvl_progress_str}\n{bar} `{int(percent*100)}%`",
            "inline": False
        })
    
    if len(ranking) > 3:
        others = []
        for idx, (n, v, l) in enumerate(ranking[3:], start=4):
            if v > 0:
                others.append(f"`{idx}.` **{n}** (`+{v:,} XP`){check_pb(category, n, v)}")
        if others:
            fields.append({"name": "--- Other Gains ---", "value": "\n".join(others), "inline": False})
    return fields

async def scrape_char(char_name, page):
    url = f"https://guildstats.eu/character?nick={char_name.replace(' ', '+')}"
    char_data = {"level": 0, "gains": {}}
    try:
        # Get Level from Main Tab
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        lvl_txt = await page.locator("b:has-text('Level:')").evaluate("node => node.parentElement.innerText")
        char_data["level"] = int(''.join(filter(str.isdigit, lvl_txt)))
        
        # Get Gains from Tab 9
        await page.goto(f"{url}&tab=9", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_selector("#tabs1 > .newTable", timeout=15000)
        soup = BeautifulSoup(await page.content(), "html.parser")
        table = soup.select_one("#tabs1 > .newTable")
        char_data["gains"] = {tds[0].get_text(strip=True): tds[1].get_text(strip=True) 
                             for row in table.find_all("tr")[1:] 
                             if len((tds := row.find_all("td"))) >= 2}
    except Exception as e:
        print(f"Error scraping {char_name}: {e}")
    return char_data

async def main():
    print(f"--- Process Started at {timestamp()} ---")
    if not CHAR_FILE.exists(): return
    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]
    
    results = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        for name in chars:
            results[name] = await scrape_char(name, page)
            print(f"🔍 Scraped {name} (Lvl {results[name]['level']})")
            await asyncio.sleep(1)
        await browser.close()
    
    save_json(JSON_PATH, results)
    
    # Calculate Daily
    all_dates = []
    for r in results.values():
        all_dates.extend(r["gains"].keys())
    
    if all_dates:
        latest = max(all_dates)
        rank = sorted([(n, int(r["gains"].get(latest, "0").replace(",", "").replace("+", "")), r["level"]) 
                       for n, r in results.items() if r["gains"].get(latest) and "+" in r["gains"].get(latest)], 
                      key=lambda x: x[1], reverse=True)
        
        if rank:
            streak = update_streak("daily", rank[0][0])
            footer_txt, embed_color = calculate_growth("daily", sum(r[1] for r in rank))
            
            post_to_discord_embed(
                "🏆 Daily Champion 🏆", 
                f"🗓️ Date: {latest}", 
                create_fields(rank, "daily", streak), 
                embed_color, 
                footer_txt
            )

def post_to_discord_embed(title, description, fields, color, footer):
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        print("Webhook URL not found!")
        return
    payload = {
        "embeds": [{
            "title": title,
            "description": description,
            "fields": fields,
            "color": color,
            "footer": {"text": footer}
        }]
    }
    r = requests.post(url, json=payload, timeout=10)
    print(f"Discord Response: {r.status_code}")

if __name__ == "__main__":
    asyncio.run(main())
