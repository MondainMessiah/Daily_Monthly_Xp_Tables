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

# --- THE DATA HUNTER ---
async def scrape_tibiarise(char_name, session, target):
    slug = char_name.replace(' ', '%20')
    url = f"https://tibiarise.app/en/character/{slug}"
    iso_key = target["iso"]
    euro_date = target["euro"]

    try:
        response = await session.get(url, timeout=15)
        if response.status_code != 200:
            print(f"⚠️ {char_name}: HTTP {response.status_code}")
            return {}

        # RECON: Look for the hidden __NEXT_DATA__ JSON
        soup = BeautifulSoup(response.text, "html.parser")
        script_tag = soup.find("script", id="__NEXT_DATA__")
        
        # If we can't find the JSON, we'll try a raw text search as a fallback
        data_source = script_tag.string if script_tag else response.text
        
        # We search for the date, then look for the "exp" or "xp" number near it
        # This regex looks for the date followed by "experienceGained":NUMBER
        pattern = rf'"{euro_date}".*?experienceGained":(\d+)'
        match = re.search(pattern, data_source)
        
        if not match:
            # Try ISO format search (2026-03-20)
            pattern = rf'"{iso_key}".*?experienceGained":(\d+)'
            match = re.search(pattern, data_source)

        if match:
            xp_val = int(match.group(1))
            formatted_xp = f"+{xp_val:,}"
            print(f"✅ {char_name}: Found {formatted_xp} XP")
            return {iso_key: formatted_xp}

        # FINAL FALLBACK: Look for the date in the HTML table structure directly
        for tr in soup.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) >= 2 and euro_date in cells[0].get_text():
                # Column 1 is usually the 'XP Gained'
                val_text = cells[1].get_text(strip=True).replace(",", "").replace("+", "")
                if val_text.isdigit():
                    formatted_xp = f"+{int(val_text):,}"
                    print(f"✅ {char_name}: Found via Table -> {formatted_xp}")
                    return {iso_key: formatted_xp}

        print(f"⚠️ {char_name}: No data for {euro_date} found in JSON or Table.")
    except Exception as e:
        print(f"⚠️ {char_name}: Error - {str(e)}")
    return {}

# --- EMBED & RANKING LOGIC (Same as your stable version) ---
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
    
    rank = sorted([(n, int(d[iso].replace(",","").replace("+",""))) for n, d in all_xp.items() if iso in d], key=lambda x: x[1], reverse=True)
    
    # Check if ANYONE has data (even 0)
    if rank:
        # We only post to Discord if at least one player gained XP (> 0)
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
            print("😴 Data found, but everyone had 0 XP gain. No post sent.")
    else:
        print("❌ Could not extract data for any characters.")

if __name__ == "__main__":
    asyncio.run(main())
