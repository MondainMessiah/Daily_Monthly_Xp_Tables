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
        "euro": dt.strftime("%d/%m/%Y"),
        "dt_obj": dt
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

# --- THE DEEP JSON EXTRACTOR ---
async def scrape_tibiarise(char_name, session, target):
    slug = char_name.replace(' ', '%20')
    url = f"https://tibiarise.app/en/character/{slug}"
    iso_key = target["iso"]
    euro_date = target["euro"]

    try:
        response = await session.get(url, timeout=15)
        if response.status_code != 200: return {}

        soup = BeautifulSoup(response.text, "html.parser")
        script_tag = soup.find("script", id="__NEXT_DATA__")
        
        if script_tag:
            raw_content = script_tag.string
            
            # DIAGNOSTIC: If it fails, we want to see what the JSON structure looks like
            # We search for the date and capture 200 characters around it
            for d_str in [euro_date, iso_key]:
                idx = raw_content.find(d_str)
                if idx != -1:
                    # Found the date! Now let's grab the numbers nearby.
                    # We look for the closest "number": value
                    context = raw_content[max(0, idx-150):min(len(raw_content), idx+150)]
                    
                    # Search for numbers (XP gains are usually long digits or 0)
                    # We look for patterns like "experienceGained":0 or "xp":1234
                    matches = re.findall(r'[:"](\d+)["},]', context)
                    if matches:
                        # Usually, the XP gain is one of the first numbers near the date.
                        # We pick the one that is likely NOT the level (780-800)
                        for m in matches:
                            val = int(m)
                            if val == 0 or val > 10000: # 0 is valid, big numbers are XP
                                formatted_xp = f"+{val:,}"
                                print(f"✅ {char_name}: Found {formatted_xp} XP (Context Match)")
                                return {iso_key: formatted_xp}
            
            # If we still haven't found it, print the context for debugging
            print(f"⚠️ {char_name}: Date found but couldn't identify XP number.")
        else:
            print(f"⚠️ {char_name}: Could not find __NEXT_DATA__ script.")

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
    today = datetime.now(ZoneInfo(TIMEZONE))
    
    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]
    all_xp = load_json(JSON_PATH, {})
    
    async with AsyncSession(impersonate="chrome120") as session:
        for name in chars:
            new_data = await scrape_tibiarise(name, session, target)
            if new_data:
                all_xp.setdefault(name, {}).update(new_data)
            await asyncio.sleep(1)
            
    save_json(JSON_PATH, all_xp)
    
    rank = sorted([(n, int(d[iso].replace(",","").replace("+",""))) for n, d in all_xp.items() if iso in d], key=lambda x: x[1], reverse=True)
    
    if rank and any(r[1] > 0 for r in rank):
        badge = update_streak("daily", rank[0][0])
        post_to_discord({
            "embeds": [{
                "title": "🏆 Daily Champion 🏆",
                "description": f"🗓️ Date: {iso}",
                "fields": create_fields([r for r in rank if r[1] > 0], "daily", badge),
                "color": 0x2ecc71,
                "footer": {"text": "TibiaRise Data • ⭐=PB 🔥=Streak 👑=Crown"}
            }]
        })
        mark_posted("daily", iso)
        print("✅ Discord Post Sent!")
    else:
        print("😴 No significant XP gains found.")

if __name__ == "__main__":
    asyncio.run(main())
