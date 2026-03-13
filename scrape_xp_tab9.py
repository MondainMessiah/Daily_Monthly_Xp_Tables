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
    """Determines the most recent completed Tibia day."""
    now = datetime.now(ZoneInfo(TIMEZONE))
    # Server Save is 10:00 AM. If checking early, look for yesterday.
    if now.hour < 10 or (now.hour == 10 and now.minute < 30):
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

# --- THE SCRAPER ---
async def scrape_xp_tab9(char_name, page, target_date):
    url = f"https://guildstats.eu/character?nick={char_name.replace(' ', '+')}&tab=9"
    try:
        # Load page and wait for the specific table structure you provided
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_selector("#tabs1 .newTable", timeout=15000)
        
        content = await page.content()
        soup = BeautifulSoup(content, "html.parser")
        table = soup.select_one("#tabs1 .newTable tbody")
        
        char_data = {}
        if table:
            rows = table.find_all("tr")
            for row in rows:
                tds = row.find_all("td")
                if len(tds) >= 2:
                    # Logic for: <td>2026-03-12 <i class="fas fa-blank"></i></td>
                    date_text = tds[0].get_text(separator=" ", strip=True).split(" ")[0]
                    # Logic for: <td><span style="...">+824,106</span></td>
                    xp_text = tds[1].get_text(strip=True).replace(",", "").replace("+", "")
                    
                    try:
                        char_data[date_text] = int(xp_text)
                    extra:
                        char_data[date_text] = 0
        
        if target_date in char_data:
            val = char_data[target_date]
            print(f"✅ {char_name}: {val:,} XP")
            return val
        else:
            print(f"❓ {char_name}: {target_date} not found.")
            return 0
    except Exception as e:
        print(f"❌ {char_name}: Error ({type(e).__name__})")
        return 0

# --- RANKING LOGIC ---
def update_streak(category, winner_name):
    all_streaks = load_json(STREAKS_PATH, {"daily": {}, "weekly": {}, "monthly": {}})
    cat_data = all_streaks.get(category, {"last_winner": "", "count": 0})
    old_winner, old_count = cat_data["last_winner"], cat_data["count"]
    streak_msg = ""

    if old_winner == winner_name:
        cat_data["count"] += 1
        if cat_data["count"] == 5:
            streak_msg = f"\n👑 **{winner_name}** has reached a 5-win streak!"
    else:
        if old_winner and old_count >= 3:
            streak_msg = f"\n⚔️ **{winner_name}** ended **{old_winner}**'s `{old_count}` win streak!"
        cat_data["last_winner"], cat_data["count"] = winner_name, 1
    
    save_json(STREAKS_PATH, all_streaks)
    badge = " `👑` " if cat_data["count"] >= 5 else f" `🔥 {cat_data['count']}` "
    return badge, streak_msg

def check_pb(category, name, current_xp):
    pbs = load_json(PB_PATH, {"daily": {}, "weekly": {}, "monthly": {}})
    cat_pbs = pbs.setdefault(category, {})
    record = cat_pbs.get(name, 0)
    if current_xp > record:
        cat_pbs[name] = current_xp
        save_json(PB_PATH, pbs)
        return " `⭐` " if record > 0 else ""
    return ""

def calculate_growth(category, current_total):
    history = load_json(TOTALS_HISTORY_PATH, {})
    prev_total = history.get(category, 0)
    p_str, color = "", 0xf1c40f 
    if prev_total > 0:
        pc = ((current_total - prev_total) / prev_total) * 100
        p_str = f" ({'+' if pc >= 0 else ''}{pc:.1f}% vs last)"
        color = 0x2ecc71 if pc > 0 else 0xe74c3c
    history[category] = current_total
    save_json(TOTALS_HISTORY_PATH, history)
    return f"Team Total: {current_total:,} XP{p_str}\n⭐ = New PB | 🔥 = Streak | 👑 = 5+ Streak", color

def create_fields(ranking, category, streak_badge):
    fields = []
    if not ranking: return fields
    max_xp = ranking[0][1]
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    
    # Top 3 with Bars
    for i, (name, xp_val) in enumerate(ranking[:3]):
        percent = (xp_val / max_xp) if max_xp > 0 else 0
        bar = "🟩" * round(percent * 10) + "⬛" * (10 - round(percent * 10))
        pb = check_pb(category, name, xp_val)
        fields.append({
            "name": f"{medals[i]} **{name}{pb}{streak_badge if i==0 else ''}**",
            "value": f"`+{xp_val:,} XP`\n{bar} `{int(percent*100)}%`",
            "inline": False
        })
    
    # Others
    others = [f"`{idx}.` **{n}** (`+{v:,} XP`){check_pb(category, n, v)}" 
              for idx, (n, v) in enumerate(ranking[3:], start=4)]
    if others:
        fields.append({"name": "--- Other Gains ---", "value": "\n".join(others), "inline": False})
    
    return fields

# --- MAIN ENGINE ---
async def main():
    target_date = get_target_date()
    print(f"🎯 Target Date: {target_date}")
    
    if not CHAR_FILE.exists():
        print("Error: characters.txt missing.")
        return

    with open(CHAR_FILE) as f:
        chars = [l.strip() for l in f if l.strip()]
    
    final_rankings = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        for name in chars:
            xp_gain = await scrape_xp_tab9(name, page, target_date)
            if xp_gain > 0:
                final_rankings.append((name, xp_gain))
            await asyncio.sleep(1)
            
        await browser.close()
    
    final_rankings.sort(key=lambda x: x[1], reverse=True)

    if final_rankings:
        badge, announce = update_streak("daily", final_rankings[0][0])
        footer, color = calculate_growth("daily", sum(r[1] for r in final_rankings))
        
        webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
        if webhook_url:
            payload = {
                "embeds": [{
                    "title": "🏆 Daily Champion 🏆",
                    "description": f"🗓️ Date: {target_date}{announce}",
                    "fields": create_fields(final_rankings, "daily", badge),
                    "color": color,
                    "footer": {"text": footer}
                }]
            }
            requests.post(webhook_url, json=payload, timeout=10)
        print("✅ Discord post sent.")
    else:
        print(f"❌ No XP found for {target_date}. No post sent.")

if __name__ == "__main__":
    asyncio.run(main())
