import os
import json
import asyncio
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
import requests

# --- SETTINGS ---
BASE_DIR = Path(__file__).resolve().parent
CHAR_FILE = BASE_DIR / "characters.txt"
JSON_PATH = BASE_DIR / "xp_log.json"
PB_PATH = BASE_DIR / "personal_bests.json"
STREAKS_PATH = BASE_DIR / "streaks.json"
TOTALS_HISTORY_PATH = BASE_DIR / "totals_history.json"
POST_STATE_PATH = BASE_DIR / "post_state.json"
TIMEZONE = "Europe/London"

def get_target_info():
    dt = datetime.now(ZoneInfo(TIMEZONE)) - timedelta(days=1)
    return {
        "iso": dt.strftime("%Y-%m-%d"),
        "euro": dt.strftime("%d/%m/%Y"), # 20/03/2026
        "short_year": dt.strftime("%d/%m/%y") # 20/03/26
    }

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

def mark_posted(category, date_str):
    state = load_json(POST_STATE_PATH, {})
    state[category] = date_str
    save_json(POST_STATE_PATH, state)

# --- THE WIRE DECODER ---
async def scrape_tibiarise(char_name, session, target):
    slug = char_name.replace(' ', '%20')
    url = f"https://tibiarise.app/en/character/{slug}"
    
    try:
        response = await session.get(url, timeout=15)
        if response.status_code != 200:
            print(f"⚠️ {char_name}: HTTP {response.status_code}")
            return {}

        full_body = response.text
        
        # We search the ENTIRE page source (including hidden scripts)
        # We look for the date, then skip the Level (790) and find the Gain.
        # Based on your screenshot: Date -> XP Gain -> Level
        # In the code it usually looks like: "20/03/2026", "0", "790"
        
        found_xp = None
        # Try both European and ISO date formats
        for date_str in [target["euro"], target["iso"], target["short_year"]]:
            # Regex: Find the date, then look for the next two numeric values
            # pattern: date_str followed by any characters, then a number (XP), then maybe another number (Level)
            # We use [^0-9\-+]* to skip over quotes, commas, and labels
            pattern = rf'"{date_str}"[^0-9\-+]*?([\-+]?[0-9,]+)'
            match = re.search(pattern, full_body)
            
            if match:
                raw_val = match.group(1).replace(",", "")
                found_xp = int(raw_val)
                break

        if found_xp is not None:
            formatted_xp = f"+{found_xp:,}" if found_xp >= 0 else f"{found_xp:,}"
            print(f"✅ {char_name}: Found {formatted_xp} XP for {target['euro']}")
            return {target["iso"]: formatted_xp}
            
        print(f"⚠️ {char_name}: Date {target['euro']} was not found in the page source.")
        
    except Exception as e:
        print(f"⚠️ {char_name}: Error - {str(e)}")
    return {}

# --- LOGIC & RANKING ---
def check_pb(category, name, xp):
    pbs = load_json(PB_PATH, {"daily": {}, "weekly": {}, "monthly": {}})
    cat_pbs = pbs.setdefault(category, {})
    old_pb = cat_pbs.get(name, 0)
    if xp > old_pb:
        cat_pbs[name] = xp
        save_json(PB_PATH, pbs)
        return " `⭐` " if old_pb > 0 else ""
    return ""

def update_streak(category, winner):
    streaks = load_json(STREAKS_PATH, {"daily": {}, "weekly": {}, "monthly": {}})
    data = streaks.setdefault(category, {"last_winner": "", "count": 0})
    if data["last_winner"] == winner:
        data["count"] += 1
    else:
        data["last_winner"], data["count"] = winner, 1
    save_json(STREAKS_PATH, streaks)
    return " `👑` " if data["count"] >= 5 else f" `🔥 {data['count']}` "

def create_fields(rank, category, badge):
    fields = []
    max_xp = rank[0][1]
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    for i, (name, xp) in enumerate(rank[:3]):
        pct = (xp / max_xp) if max_xp > 0 else 0
        bar = "🟩" * round(pct * 10) + "⬛" * (10 - round(pct * 10))
        pb = check_pb(category, name, xp)
        fields.append({"name": f"{medals[i]} **{name}{pb}{badge if i==0 else ''}**", "value": f"`+{xp:,} XP`\n{bar} `{int(pct*100)}%`", "inline": False})
    
    others = [f"`{idx}.` **{n}** (`+{v:,} XP`){check_pb(category, n, v)}" for idx, (n, v) in enumerate(rank[3:], 4) if v > 0]
    if others: fields.append({"name": "--- Others ---", "value": "\n".join(others)})
    return fields

# --- MAIN ---
async def main():
    target = get_target_info()
    iso = target["iso"]
    
    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]
    all_xp = load_json(JSON_PATH, {})
    
    async with AsyncSession(impersonate="chrome120") as session:
        for name in chars:
            new_data = await scrape_tibiarise(name, session, target)
            if new_data:
                all_xp.setdefault(name, {}).update(new_data)
            await asyncio.sleep(1)
            
    save_json(JSON_PATH, all_xp)
    
    # Process Ranking
    rank = sorted([(n, int(d[iso].replace(",","").replace("+",""))) for n, d in all_xp.items() if iso in d], key=lambda x: x[1], reverse=True)
    
    if rank:
        # Check if anyone actually GAINED xp (to avoid 0-xp-posts)
        if any(r[1] > 0 for r in rank):
            badge = update_streak("daily", rank[0][0])
            post_to_discord({
                "embeds": [{
                    "title": "🏆 Daily Champion 🏆",
                    "description": f"🗓️ Date: {target['euro']}",
                    "fields": create_fields([r for r in rank if r[1] > 0], "daily", badge),
                    "color": 0x2ecc71,
                    "footer": {"text": "TibiaRise Data • ⭐=PB 🔥=Streak 👑=Crown"}
                }]
            })
            mark_posted("daily", iso)
            print("✅ Discord Post Sent!")
        else:
            print("😴 Everyone found, but gains were 0. No post sent.")
    else:
        print("❌ Could not extract data for any characters.")

if __name__ == "__main__":
    asyncio.run(main())
