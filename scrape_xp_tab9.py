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

def has_posted(category, date_str):
    state = load_json(POST_STATE_PATH, {})
    return state.get(category) == date_str

def mark_posted(category, date_str):
    state = load_json(POST_STATE_PATH, {})
    state[category] = date_str
    save_json(POST_STATE_PATH, state)

# --- THE DEEP JSON EXTRACTOR ---
async def scrape_tibiarise(char_name, session, target):
    slug = char_name.replace(' ', '%20')
    url = f"https://tibiarise.app/en/character/{slug}"
    
    try:
        response = await session.get(url, timeout=15)
        if response.status_code != 200: return {}

        soup = BeautifulSoup(response.text, "html.parser")
        script = soup.find("script", id="__NEXT_DATA__")
        
        raw_content = script.string if script else response.text
        
        # SEARCH STRATEGY: Find the date string, then find the FIRST number that follows it
        # This is the most "Universal" way to scrape Next.js data without knowing the exact keys
        for date_str in [target["euro"], target["iso"]]:
            # Regex: find date_str, then skip non-digits, then capture the digits
            pattern = rf'"{date_str}".*?[:"](\d+)'
            match = re.search(pattern, raw_content)
            
            if match:
                val = int(match.group(1))
                # TibiaRise often puts the 'Total XP' after the 'Gain'. 
                # If we accidentally grabbed a 8-billion number, we need the NEXT one.
                # But usually, the Gain comes first in the JSON object.
                formatted_xp = f"+{val:,}"
                print(f"✅ {char_name}: Found {val:,} XP for {date_str}")
                return {target["iso"]: formatted_xp}
                
        print(f"⚠️ {char_name}: Date not found in the site data yet.")
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
    
    # Flags for what to post
    do_daily = not has_posted("daily", iso)
    do_weekly = (today.weekday() == 0) and not has_posted("weekly", iso)
    do_monthly = (today.day == 1) and not has_posted("monthly", iso)

    if not (do_daily or do_weekly or do_monthly):
        print(f"⏩ Already posted everything for {iso}. Exiting.")
        return

    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]
    all_xp = load_json(JSON_PATH, {})
    
    async with AsyncSession(impersonate="chrome120") as session:
        for name in chars:
            new_data = await scrape_tibiarise(name, session, target)
            if new_data:
                all_xp.setdefault(name, {}).update(new_data)
            await asyncio.sleep(1)
            
    save_json(JSON_PATH, all_xp)
    
    # Process Daily
    if do_daily:
        rank_d = sorted([(n, int(d[iso].replace(",","").replace("+",""))) for n, d in all_xp.items() if iso in d], key=lambda x: x[1], reverse=True)
        rank_d = [r for r in rank_d if r[1] > 0]
        if rank_d:
            badge = update_streak("daily", rank_d[0][0])
            post_to_discord({"embeds": [{"title": "🏆 Daily Champion 🏆", "description": f"🗓️ Date: {iso}", "fields": create_fields(rank_d, "daily", badge), "color": 0x2ecc71, "footer": {"text": "TibiaRise Data • ⭐=PB 🔥=Streak 👑=Crown"}}]})
            mark_posted("daily", iso)

    # Process Weekly (Every Monday)
    if do_weekly and has_posted("daily", iso):
        start = (target["dt_obj"] - timedelta(days=6)).strftime("%Y-%m-%d")
        rank_w = sorted([(n, sum(int(v.replace(",","").replace("+","")) for d, v in dates.items() if start <= d <= iso)) for n, dates in all_xp.items()], key=lambda x: x[1], reverse=True)
        rank_w = [r for r in rank_w if r[1] > 0]
        if rank_w:
            badge = update_streak("weekly", rank_w[0][0])
            post_to_discord({"embeds": [{"title": "🏆 Weekly Champion 🏆", "description": f"🗓️ Week ending {iso}", "fields": create_fields(rank_w, "weekly", badge), "color": 0x3498db}]})
            mark_posted("weekly", iso)

    # Process Monthly (1st of the month)
    if do_monthly and has_posted("daily", iso):
        month_prefix = (target["dt_obj"]).strftime("%Y-%m")
        rank_m = sorted([(n, sum(int(v.replace(",","").replace("+","")) for d, v in dates.items() if d.startswith(month_prefix))) for n, dates in all_xp.items()], key=lambda x: x[1], reverse=True)
        rank_m = [r for r in rank_m if r[1] > 0]
        if rank_m:
            badge = update_streak("monthly", rank_m[0][0])
            post_to_discord({"embeds": [{"title": "🏆 Monthly Champion 🏆", "description": f"🗓️ Month: {month_prefix}", "fields": create_fields(rank_m, "monthly", badge), "color": 0x9b59b6}]})
            mark_posted("monthly", iso)

if __name__ == "__main__":
    asyncio.run(main())
