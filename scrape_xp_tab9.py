import os
import json
import asyncio
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
        "euro": dt.strftime("%d/%m/%Y") # 20/03/2026
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

# --- THE DEEP SEARCH ENGINE ---
def find_xp_in_dict(obj, target_date):
    """Recursively hunts through a dictionary for the XP gain of a specific date."""
    if isinstance(obj, dict):
        # Look for objects that have both a date and an experience field
        # TibiaRise typically uses 'date' and 'experienceGained'
        if obj.get('date') == target_date or obj.get('datetime') == target_date:
            xp = obj.get('experienceGained') or obj.get('expGained') or obj.get('experience')
            if xp is not None:
                return xp
        for val in obj.values():
            result = find_xp_in_dict(val, target_date)
            if result is not None: return result
    elif isinstance(obj, list):
        for item in obj:
            result = find_xp_in_dict(item, target_date)
            if result is not None: return result
    return None

async def scrape_tibiarise(char_name, session, target):
    slug = char_name.replace(' ', '%20')
    url = f"https://tibiarise.app/en/character/{slug}"
    
    try:
        response = await session.get(url, timeout=15)
        if response.status_code != 200: return {}

        soup = BeautifulSoup(response.text, "html.parser")
        script = soup.find("script", id="__NEXT_DATA__")
        
        if script:
            data = json.loads(script.string)
            # Search for the XP using both the Euro format and ISO format
            xp_gain = find_xp_in_dict(data, target["euro"])
            if xp_gain is None:
                xp_gain = find_xp_in_dict(data, target["iso"])

            if xp_gain is not None:
                formatted_xp = f"+{int(xp_gain):,}"
                print(f"✅ {char_name}: Found {formatted_xp} XP")
                return {target["iso"]: formatted_xp}
                
        print(f"⚠️ {char_name}: Data for {target['euro']} not found in JSON.")
    except Exception as e:
        print(f"⚠️ {char_name}: Error - {str(e)}")
    return {}

# --- EMBED FORMATTING ---
def check_pb(category, name, current_xp):
    pbs = load_json(PB_PATH, {"daily": {}, "weekly": {}, "monthly": {}})
    cat_pbs = pbs.setdefault(category, {})
    record = cat_pbs.get(name, 0)
    if current_xp > record:
        cat_pbs[name] = current_xp
        save_json(PB_PATH, pbs)
        return " `⭐` " if record > 0 else ""
    return ""

def update_streak(category, winner_name):
    all_streaks = load_json(STREAKS_PATH, {"daily": {}, "weekly": {}, "monthly": {}})
    cat_data = all_streaks.get(category, {"last_winner": "", "count": 0})
    if cat_data["last_winner"] == winner_name:
        cat_data["count"] += 1
    else:
        cat_data["last_winner"], cat_data["count"] = winner_name, 1
    save_json(STREAKS_PATH, all_streaks)
    return " `👑` " if cat_data["count"] >= 5 else f" `🔥 {cat_data['count']}` "

def create_fields(ranking, category, badge):
    fields = []
    max_xp = ranking[0][1]
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    for i, (name, xp) in enumerate(ranking[:3]):
        pct = (xp / max_xp) if max_xp > 0 else 0
        bar = "🟩" * round(pct * 10) + "⬛" * (10 - round(pct * 10))
        pb = check_pb(category, name, xp)
        fields.append({"name": f"{medals[i]} **{name}{pb}{badge if i==0 else ''}**", "value": f"`+{xp:,} XP`\n{bar} `{int(pct*100)}%`"})
    
    others = [f"`{idx}.` **{n}** (`+{v:,} XP`){check_pb(category, n, v)}" for idx, (n, v) in enumerate(ranking[3:], 4) if v > 0]
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
    
    rank = sorted([(n, int(d[iso].replace(",","").replace("+",""))) for n, d in all_xp.items() if iso in d], key=lambda x: x[1], reverse=True)
    
    # Check if ANYONE has a result (even 0)
    if rank:
        # But we only post if someone gained XP
        if any(r[1] > 0 for r in rank):
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
            print("😴 Everyone found, but all had 0 XP gain.")
    else:
        print("❌ Could not find any data for any character.")

if __name__ == "__main__":
    asyncio.run(main())
