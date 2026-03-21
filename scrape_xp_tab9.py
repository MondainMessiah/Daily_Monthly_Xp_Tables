import os
import json
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
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

def get_target_date():
    return (datetime.now(ZoneInfo(TIMEZONE)) - timedelta(days=1)).strftime("%Y-%m-%d")

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

# --- TIBIARISE SCRAPER ---
async def scrape_tibiarise(char_name, session, target_date):
    # TibiaRise usually uses spaces or %20 in URLs
    formatted_name = char_name.replace(' ', '%20')
    urls_to_try = [
        f"https://tibiarise.app/character/{formatted_name}",
        f"https://tibiarise.app/en/character/{formatted_name}"
    ]
    
    for url in urls_to_try:
        try:
            response = await session.get(url, timeout=15)
            if response.status_code != 200:
                continue # If 404, try the /en/ version loop

            html = response.text
            soup = BeautifulSoup(html, "html.parser")
            
            # Diagnostic Check: Is the date even on this page?
            if target_date not in html:
                continue

            # Universal Hunter for Tabular Data
            for tr in soup.find_all("tr"):
                row_text = tr.get_text(separator=" ", strip=True)
                if target_date in row_text:
                    tds = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                    for td in tds:
                        clean_val = td.replace(",", "").replace(" ", "").replace("+", "").strip()
                        # Looking for the XP gain (must be a number, usually has a + or is a massive number)
                        if clean_val.isdigit() and ("+" in td or int(clean_val) > 1000):
                            formatted_xp = f"+{int(clean_val):,}"
                            print(f"✅ {char_name}: Found {target_date} ({formatted_xp})")
                            return {target_date: formatted_xp}
            
            # If we get here, the date is on the page, but NOT in a standard <tr> table!
            # Let's print the raw HTML around the date so we can calibrate the parser.
            idx = html.find(target_date)
            context = html[max(0, idx-50):min(len(html), idx+150)]
            print(f"⚠️ {char_name}: Date found, but layout is unknown. HTML Context:\n{context}")
            return {}

        except Exception as e:
            print(f"⚠️ {char_name}: ERROR - {str(e)}")
            
    print(f"⚠️ {char_name}: Could not find XP data for {target_date}.")
    return {}

# --- LOGIC & FORMATTING FUNCTIONS ---
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
    target_date = get_target_date()
    today = datetime.now(ZoneInfo(TIMEZONE))
    
    needs_daily = not has_posted("daily", target_date)
    needs_weekly = (today.weekday() == 0) and not has_posted("weekly", target_date)
    needs_monthly = (today.day == 1) and not has_posted("monthly", target_date)

    if not (needs_daily or needs_weekly or needs_monthly):
        print(f"⏩ Memory Check: Already posted everything required for {target_date}. Exiting.")
        return 
        
    print(f"🎯 Target: {target_date}")
    
    if not CHAR_FILE.exists(): 
        post_to_discord({"content": f"🚨 **Bot Error:** I cannot find the `characters.txt` file."})
        return

    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]
    print(f"👥 Loaded {len(chars)} characters from characters.txt")
    
    all_xp = load_json(JSON_PATH, {})
    
    # We impersonate Chrome to blend in nicely
    async with AsyncSession(impersonate="chrome120") as session:
        for name in chars:
            new_data = await scrape_tibiarise(name, session, target_date)
            if new_data:
                if name not in all_xp: all_xp[name] = {}
                all_xp[name].update(new_data)
            
            # Tiny delay to be polite to the TibiaRise servers
            await asyncio.sleep(1)
            
    save_json(JSON_PATH, all_xp)
    
    # --- PROCESS DAILY LOGIC & ALERTS ---
    if needs_daily:
        rank_d = sorted([(n, int(d[target_date].replace(",","").replace("+",""))) for n, d in all_xp.items() if target_date in d], key=lambda x: x[1], reverse=True)
        rank_d = [r for r in rank_d if r[1] > 0]

        if rank_d:
            badge, announce = update_streak("daily", rank_d[0][0])
            footer, color = calculate_growth("daily", sum(r[1] for r in rank_d))
            post_to_discord({"embeds": [{"title": "🏆 Daily Champion 🏆", "description": f"🗓️ Date: {target_date}{announce}", "fields": create_fields(rank_d, "daily", badge), "color": color, "footer": {"text": footer}}]})
            mark_posted("daily", target_date)
            print("✅ Daily embed posted successfully!")
        else:
            print(f"⚠️ No data found for {target_date}.")
            attempts = increment_attempts(target_date)
            max_attempts = 5
            if attempts < max_attempts:
                post_to_discord({"content": f"⚠️ **Data Missing:** TibiaRise hasn't updated `{target_date}` yet. I will automatically check again in one hour. *(Attempt {attempts}/{max_attempts})*"})
            elif attempts == max_attempts:
                post_to_discord({"content": f"❌ **Data Missing:** TibiaRise still hasn't updated `{target_date}` and I have reached my maximum of {max_attempts} attempts. I will try again tomorrow."})

    # --- PROCESS WEEKLY & MONTHLY LOGIC ---
    if needs_weekly and has_posted("daily", target_date): 
        s = (today - timedelta(days=7)).strftime("%Y-%m-%d")
        e = (today - timedelta(days=1)).strftime("%Y-%m-%d")
        rank_w = sorted([(n, sum(int(v.replace(",", "").replace("+", "")) for d, v in dates.items() if s <= d <= e and "+" in v)) for n, dates in all_xp.items()], key=lambda x: x[1], reverse=True)
        rank_w = [r for r in rank_w if r[1] > 0]
        if rank_w:
            badge, announce = update_streak("weekly", rank_w[0][0])
            footer, color = calculate_growth("weekly", sum(r[1] for r in rank_w))
            post_to_discord({"embeds": [{"title": "🏆 Weekly Champion 🏆", "description": f"🗓️ {s} to {e}{announce}", "fields": create_fields(rank_w, "weekly", badge), "color": color, "footer": {"text": footer}}]})
            mark_posted("weekly", target_date)

    if needs_monthly and has_posted("daily", target_date):
        prev_month = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        rank_m = sorted([(n, sum(int(v.replace(",", "").replace("+", "")) for d, v in dates.items() if d.startswith(prev_month) and "+" in v)) for n, dates in all_xp.items()], key=lambda x: x[1], reverse=True)
        rank_m = [r for r in rank_m if r[1] > 0]
        if rank_m:
            badge, announce = update_streak("monthly", rank_m[0][0])
            footer, color = calculate_growth("monthly", sum(r[1] for r in rank_m))
            post_to_discord({"embeds": [{"title": "🏆 Monthly Champion 🏆", "description": f"🗓️ {prev_month}{announce}", "fields": create_fields(rank_m, "monthly", badge), "color": color, "footer": {"text": footer}}]})
            mark_posted("monthly", target_date)

if __name__ == "__main__":
    asyncio.run(main())
