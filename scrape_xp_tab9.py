import os
import json
import asyncio
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
POST_STATE_PATH = BASE_DIR / "post_state.json"
TIMEZONE = "Europe/London"

def get_target_formats():
    """Returns a list of potential date formats for matching."""
    dt = datetime.now(ZoneInfo(TIMEZONE)) - timedelta(days=1)
    return [
        dt.strftime("%Y-%m-%d"),       # 2026-03-20
        dt.strftime("%d.%m.%Y"),       # 20.03.2026
        dt.strftime("%d/%m/%Y"),       # 20/03/2026
        dt.strftime("%b %d, %Y"),      # Mar 20, 2026
        dt.strftime("%d %b %Y"),       # 20 Mar 2026
    ]

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

def has_posted(category, date_str):
    state = load_json(POST_STATE_PATH, {})
    return state.get(category) == date_str

def mark_posted(category, date_str):
    state = load_json(POST_STATE_PATH, {})
    state[category] = date_str
    save_json(POST_STATE_PATH, state)

def increment_attempts(date_str):
    state = load_json(POST_STATE_PATH, {})
    tracker = state.get("daily_attempts", {})
    count = tracker.get("count", 0) + 1 if tracker.get("date") == date_str else 1
    state["daily_attempts"] = {"date": date_str, "count": count}
    save_json(POST_STATE_PATH, state)
    return count

# --- TIBIARISE PLAYWRIGHT SCRAPER ---
async def scrape_tibiarise(char_name, page, target_formats):
    formatted_name = char_name.replace(' ', '%20')
    url = f"https://tibiarise.app/en/characters/{formatted_name}"
    iso_date = target_formats[0] # Internal JSON key
    
    try:
        print(f"🔍 Visiting: {url}")
        # Wait for the main content to load
        await page.goto(url, wait_until="networkidle", timeout=45000)
        await asyncio.sleep(4) # Extra buffer for React table rendering
        
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")
        
        # Hunt through every table row on the page
        for row in soup.find_all("tr"):
            row_text = row.get_text(separator=" ", strip=True)
            
            # If the row contains any of our date formats...
            if any(fmt in row_text for fmt in target_formats):
                tds = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
                
                # Filter for the XP column (must be > 1000 to avoid Level/Rank cols)
                for td in tds:
                    clean_val = td.replace(",", "").replace(" ", "").replace("+", "").strip()
                    if clean_val.isdigit() and int(clean_val) > 1000:
                        formatted_xp = f"+{int(clean_val):,}"
                        print(f"✅ {char_name}: Found {iso_date} ({formatted_xp})")
                        return {iso_date: formatted_xp}
                        
        print(f"⚠️ {char_name}: Data not found in tables.")
        return {}

    except Exception as e:
        print(f"⚠️ {char_name}: ERROR - {str(e)}")
        return {}

# --- LOGIC FUNCTIONS ---
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
        if cat_data["count"] == 5: msg = f"\n👑 **{winner_name}** earned the Crown!"
    else:
        if old_winner and old_count >= 3: msg = f"\n⚔️ **{winner_name}** ended **{old_winner}**'s `{old_count}` win streak!"
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
        fields.append({"name": f"{medals[i]} **{name}{pb}{streak_badge if i==0 else ''}**", "value": f"`+{xp_val:,} XP`\n{bar} `{int(percent*100)}%`", "inline": False})
    others = [f"`{idx}.` **{n}** (`+{v:,} XP`){check_pb(category, n, v)}" for idx, (n, v) in enumerate(ranking[3:], start=4) if v > 0]
    if others: fields.append({"name": "--- Other Gains ---", "value": "\n".join(others), "inline": False})
    return fields

# --- MAIN ENGINE ---
async def main():
    target_formats = get_target_formats()
    iso_date = target_formats[0]
    today = datetime.now(ZoneInfo(TIMEZONE))
    
    needs_daily = not has_posted("daily", iso_date)
    needs_weekly = (today.weekday() == 0) and not has_posted("weekly", iso_date)
    needs_monthly = (today.day == 1) and not has_posted("monthly", iso_date)

    if not (needs_daily or needs_weekly or needs_monthly):
        print(f"⏩ Memory Check: Already posted everything required for {iso_date}. Exiting.")
        return 
        
    print(f"🎯 Target Date: {iso_date}")
    
    if not CHAR_FILE.exists(): 
        print("❌ Error: characters.txt not found")
        return

    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]
    
    all_xp = load_json(JSON_PATH, {})
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Use a real user-agent to look human
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        page = await context.new_page()
        
        for name in chars:
            new_data = await scrape_tibiarise(name, page, target_formats)
            if new_data:
                if name not in all_xp: all_xp[name] = {}
                all_xp[name].update(new_data)
            await asyncio.sleep(2)
            
        await browser.close()
            
    save_json(JSON_PATH, all_xp)
    
    if needs_daily:
        rank_d = sorted([(n, int(d[iso_date].replace(",","").replace("+",""))) for n, d in all_xp.items() if iso_date in d], key=lambda x: x[1], reverse=True)
        rank_d = [r for r in rank_d if r[1] > 0]

        if rank_d:
            badge, announce = update_streak("daily", rank_d[0][0])
            footer, color = calculate_growth("daily", sum(r[1] for r in rank_d))
            post_to_discord({"embeds": [{"title": "🏆 Daily Champion 🏆", "description": f"🗓️ Date: {iso_date}{announce}", "fields": create_fields(rank_d, "daily", badge), "color": color, "footer": {"text": footer}}]})
            mark_posted("daily", iso_date)
            print("✅ Daily embed posted!")
        else:
            print(f"⚠️ No data found for {iso_date}.")
            attempts = increment_attempts(iso_date)
            if attempts < 5:
                post_to_discord({"content": f"⚠️ **Data Missing:** TibiaRise hasn't updated `{iso_date}` yet. (Attempt {attempts}/5)"})

    # Weekly/Monthly Logic (Standard)
    if needs_weekly and has_posted("daily", iso_date):
        s = (today - timedelta(days=7)).strftime("%Y-%m-%d")
        e = (today - timedelta(days=1)).strftime("%Y-%m-%d")
        rank_w = sorted([(n, sum(int(v.replace(",", "").replace("+", "")) for d, v in dates.items() if s <= d <= e and "+" in v)) for n, dates in all_xp.items()], key=lambda x: x[1], reverse=True)
        rank_w = [r for r in rank_w if r[1] > 0]
        if rank_w:
            badge, announce = update_streak("weekly", rank_w[0][0])
            footer, color = calculate_growth("weekly", sum(r[1] for r in rank_w))
            post_to_discord({"embeds": [{"title": "🏆 Weekly Champion 🏆", "description": f"🗓️ {s} to {e}{announce}", "fields": create_fields(rank_w, "weekly", badge), "color": color, "footer": {"text": footer}}]})
            mark_posted("weekly", iso_date)

    if needs_monthly and has_posted("daily", iso_date):
        prev_month = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        rank_m = sorted([(n, sum(int(v.replace(",", "").replace("+", "")) for d, v in dates.items() if d.startswith(prev_month) and "+" in v)) for n, dates in all_xp.items()], key=lambda x: x[1], reverse=True)
        rank_m = [r for r in rank_m if r[1] > 0]
        if rank_m:
            badge, announce = update_streak("monthly", rank_m[0][0])
            footer, color = calculate_growth("monthly", sum(r[1] for r in rank_m))
            post_to_discord({"embeds": [{"title": "🏆 Monthly Champion 🏆", "description": f"🗓️ {prev_month}{announce}", "fields": create_fields(rank_m, "monthly", badge), "color": color, "footer": {"text": footer}}]})
            mark_posted("monthly", iso_date)

if __name__ == "__main__":
    asyncio.run(main())
