import os
import json
import requests
import urllib.parse
from bs4 import BeautifulSoup
import re
import time
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from playwright.sync_api import sync_playwright

# --- CONFIGURATION ---
BASE_DIR = Path(__file__).resolve().parent
CHAR_FILE = BASE_DIR / "characters.txt"
LOG_PATH = BASE_DIR / "xp_log.json"
STATE_PATH = BASE_DIR / "post_state.json"
STREAKS_PATH = BASE_DIR / "streaks.json"
PB_PATH = BASE_DIR / "personal_bests.json"
TIMEZONE = "Europe/London"
MAX_XP_THRESHOLD = 200000000 

# --- 🎬 GIF CONFIGURATION ---
KING_GIFS = [
    "https://i.giphy.com/vX79ZAsCNe6n6.gif",      # Robert Baratheon
    "https://i.giphy.com/p6jVTOTCo63cs.gif",      # Joffrey Baratheon
    "https://i.giphy.com/8v3EErE79ZOpq.gif",      # Robb Stark
    "https://i.giphy.com/26vUJAbhM8kHhA8X6.gif",   # Jon Snow
    "https://i.giphy.com/l41YedIBvT817KOF2.gif"    # Tommen Baratheon
]

def get_dates():
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
    
    if now.hour < 10:
        target_date = now - timedelta(days=2)
    else:
        target_date = now - timedelta(days=1)
        
    return {
        "yesterday_iso": target_date.strftime("%Y-%m-%d"),
        "yesterday_display": target_date.strftime("%d-%m-%y"),
        "month_filter": target_date.strftime("%Y-%m"),
        "is_monday": now.weekday() == 0,
        "is_first": now.day == 1,
        "month_name": target_date.strftime("%B")
    }

# ==========================================
# 🛠️ THE DATA SCRAPER (Explicit Fallback Parser)
# ==========================================
def fetch_data_playwright(page, name, dates):
    target_date = dates['yesterday_iso']  # e.g., "2026-10-17"
    print(f"🌐 Fetching profile directly for {name} targeting date {target_date}...")
    
    encoded_name = urllib.parse.quote(name)
    profile_url = f"https://tibiastats.pl/en/character/{encoded_name}"
    
    try:
        page.goto(profile_url, wait_until="networkidle", timeout=30000)
        time.sleep(2)
        
        try:
            exp_tab = page.wait_for_selector("button:has-text('Experience')", timeout=5000)
            if exp_tab:
                exp_tab.click()
                time.sleep(2)
        except Exception:
            pass

        soup = BeautifulSoup(page.content(), 'html.parser')
        rows = soup.find_all('tr')
        
        target_row = None
        
        for row in rows:
            tds = row.find_all('td')
            if len(tds) >= 3 and target_date in tds[0].get_text().strip():
                target_row = row
                break
                
        if not target_row:
            for row in rows:
                tds = row.find_all('td')
                if len(tds) >= 3 and re.search(r"\d{4}-\d{2}-\d{2}", tds[0].get_text()):
                    target_row = row
                    print(f"DEBUG {name}: Exact date {target_date} not in table. Fallback to latest entry -> {tds[0].get_text().strip()}")
                    break

        if target_row:
            tds = target_row.find_all('td')
            gain_cell = tds[2]
            span_el = gain_cell.find('span')
            gain_text = span_el.get_text().strip() if span_el else gain_cell.get_text().strip()
            
            digits = "".join(c for c in gain_text if c.isdigit())
            if digits:
                gain_val = int(digits)
                if gain_val < MAX_XP_THRESHOLD:
                    if '-' in gain_text or 'trending-down' in str(gain_cell):
                        gain_val = -gain_val
                    print(f"DEBUG {name}: Successfully parsed XP gain -> {gain_val:,}")
                    return gain_val

        print(f"DEBUG {name}: Could not locate any XP entry.")
        return 0
    except Exception as e:
        print(f"Error scraping {name} via Playwright: {e}")
        return 0

# ==========================================
# 🔥 ENGINES (Streak / PB / Post)
# ==========================================
def update_personal_best(name, current_gain):
    pb_data = load_json(PB_PATH, {})
    current_gain = int(current_gain)
    if current_gain <= 0: return False
    old_pb = pb_data.get(name, 0)
    if current_gain > old_pb:
        pb_data[name] = current_gain
        save_json(PB_PATH, pb_data)
        return True
    return False

def update_period_streak(category, winner_name):
    all_streaks = load_json(STREAKS_PATH, {"daily":{}, "weekly":{}, "monthly":{}, "reigning_king": ""})
    data = all_streaks.get(category, {})
    last_winner = data.get("last_winner", "")
    last_count = data.get("count", 0)
    reigning_king = all_streaks.get("reigning_king", "")
    
    broken_msg, king_msg, event_gif = "", "", None
    
    if last_winner.strip().lower() != winner_name.strip().lower():
        if last_count >= 2 and category == "daily":
            broken_msg = f"\n💔 **{last_winner}**'s streak of **{last_count}** was broken by **{winner_name}**!"
        new_count = 1
    else:
        new_count = last_count + 1
        
    if category == "daily" and new_count >= 3:
        selected_gif = random.choice(KING_GIFS)
        if winner_name.strip().lower() != reigning_king.strip().lower():
            king_msg = f"\n👑 **A NEW KING HAS BEEN CROWNED!** 👑\n**{winner_name}** has usurped the throne with a 3-day streak!"
            all_streaks["reigning_king"] = winner_name
            event_gif = selected_gif
        else:
            king_msg = f"\n👑 **THE KING EXTENDS HIS REIGN!** 👑\n**{winner_name}** is on a **{new_count} day** streak!"
            event_gif = selected_gif
            
    all_streaks[category] = {"last_winner": winner_name, "count": new_count}
    save_json(STREAKS_PATH, all_streaks)
    
    updated_king = all_streaks.get("reigning_king", "")
    return new_count, broken_msg, king_msg, event_gif, updated_king, winner_name

def make_bar(val, max_val):
    if max_val <= 0: return "⬛" * 10
    filled = max(0, min(10, round((val / max_val) * 10)))
    return "🟩" * filled + "⬛" * (10 - filled)

def send_discord_post(title, subtitle, ranking, color, dates, streak_cat=None, pb_list=None):
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook or not ranking: return
    pb_list = pb_list or []
    max_xp = ranking[0][1]
    curr_total = sum(item[1] for item in ranking)
    
    broken_msg, king_msg, final_gif, current_king, streak_holder, streak_count = "", "", None, "", "", 0
    if streak_cat:
        count, b_msg, k_msg, e_gif, king, holder = update_period_streak(streak_cat, ranking[0][0])
        broken_msg, king_msg, final_gif, current_king, streak_holder, streak_count = b_msg, k_msg, e_gif, king, holder, count
    else:
        current_king = load_json(STREAKS_PATH, {}).get("reigning_king", "")

    full_desc = subtitle
    if broken_msg: full_desc += broken_msg
    if king_msg: full_desc += king_msg

    fields = []
    medals = ["🥇", "🥈", "🥉"]
    for i, (name, xp) in enumerate(ranking[:3]):
        pb_star = " ⭐️" if name in pb_list else ""
        person_tags = ""
        if name.strip().lower() == current_king.strip().lower():
            person_tags += " 👑"
        if streak_cat and name.strip().lower() == streak_holder.strip().lower() and streak_count >= 2:
            person_tags += f" 🔥 {streak_count}"

        pct = int((xp / max_xp) * 100) if max_xp > 0 else 0
        fields.append({
            "name": f"{medals[i]} {name}{person_tags}{pb_star}",
            "value": f"`{xp:+,} XP`\n{make_bar(xp, max_xp)} `{pct}%`",
            "inline": False
        })

    others = []
    for name, xp in ranking[3:10]:
        others.append(f"**{name}** (`{xp:+,} XP`){' ⭐️' if name in pb_list else ''}")
    if others: fields.append({"name": "--- Other Gains ---", "value": "\n".join(others), "inline": False})

    legend = "⭐️=PB | 🔥=Streak"
    if streak_cat == "daily":
        legend += " | 👑=King"
    footer_text = f"Team Total: {curr_total:,} XP\n{legend}"

    main_embed = {
        "title": f"🏆 {title} 🏆",
        "description": full_desc,
        "fields": fields,
        "color": color,
        "footer": {"text": footer_text}
    }
    if final_gif:
        main_embed["image"] = {"url": final_gif}

    requests.post(webhook, json={"embeds": [main_embed]})

def get_summed_xp(logs, chars, days=None, month_prefix=None):
    rankings = []
    today = datetime.now(ZoneInfo(TIMEZONE))
    target_dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, (days or 7) + 1)] if not month_prefix else []
    
    for name in chars:
        char_history = logs.get(name, {})
        total = 0
        if month_prefix:
            for d, v in char_history.items():
                if d.startswith(month_prefix):
                    digits = "".join(c for c in str(v) if c.isdigit())
                    if digits:
                        total += int(digits) * (-1 if str(v).startswith('-') else 1)
        else:
            for d in target_dates:
                v = char_history.get(d)
                if v:
                    digits = "".join(c for c in str(v) if c.isdigit())
                    if digits:
                        total += int(digits) * (-1 if str(v).startswith('-') else 1)
        if total != 0:
            rankings.append((name, total))
            
    rankings.sort(key=lambda x: x[1], reverse=True)
    return rankings

def load_json(path, fallback=None):
    if not path.exists(): return fallback or {}
    try:
        with open(path, "r") as f:
            content = f.read().strip(); return json.loads(content) if content else (fallback or {})
    except: return fallback or {}

def save_json(path, data):
    with open(path, "w") as f: json.dump(data, f, indent=2)

def main():
    dates = get_dates(); logs, state = load_json(LOG_PATH), load_json(STATE_PATH)
    if not CHAR_FILE.exists(): return
    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]

    print(f"🌐 Starting Playwright scraper for target date {dates['yesterday_iso']}...")
    current_scrapes = {}; daily_pb_achievers = []; total_non_zero = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
        page = context.new_page()

        for name in chars:
            gain = fetch_data_playwright(page, name, dates)
            current_scrapes[name] = gain
            if gain != 0: total_non_zero += 1
            time.sleep(1)

        browser.close()

    if total_non_zero == 0:
        print(f"🛑 ANTI-ZERO TRIGGERED.")
        return 

    for name, gain in current_scrapes.items():
        if name not in logs: logs[name] = {}
        logs[name][dates['yesterday_iso']] = f"{gain:+,}"
        if gain > 0 and update_personal_best(name, gain): daily_pb_achievers.append(name)
    
    save_json(LOG_PATH, logs)

    daily_ranks = [(name, gain) for name, gain in current_scrapes.items() if gain != 0]
    daily_ranks.sort(key=lambda x: x[1], reverse=True)
    top_daily_winner = daily_ranks[0][0] if daily_ranks else ""

    all_streaks = load_json(STREAKS_PATH, {"daily":{}, "weekly":{}, "monthly":{}, "reigning_king": ""})
    reigning_king = all_streaks.get("reigning_king", "")
    king_died_msg = ""
    
    if reigning_king:
        king_xp = current_scrapes.get(reigning_king, 0)
        if king_xp <= 0:
            if king_xp < 0:
                king_died_msg = f"\n\n💀 **THE KING HAS DIED IN BATTLE!** 💀\n**{reigning_king}** lost `{king_xp:+,} XP` and was stripped of the crown!"
            else:
                king_died_msg = f"\n\n👑❌ **THE KING WAS INACTIVE!** 👑❌\n**{reigning_king}** gained `0 XP` and forfeited the crown!"
            if all_streaks.get("daily", {}).get("last_winner", "").strip().lower() == reigning_king.strip().lower():
                all_streaks["daily"] = {"last_winner": "", "count": 0}
            reigning_king = ""

    if not reigning_king and top_daily_winner:
        all_streaks["reigning_king"] = top_daily_winner
        if king_died_msg:
            king_died_msg += f"\n👑 **{top_daily_winner}** has instantly seized the vacant throne as the new King!"
        else:
            king_died_msg = f"\n\n👑 **{top_daily_winner}** has claimed the vacant throne!"
        save_json(STREAKS_PATH, all_streaks)
    elif king_died_msg:
        save_json(STREAKS_PATH, all_streaks)

    if dates['is_monday'] and state.get("last_weekly") != dates['yesterday_iso']:
        r = get_summed_xp(logs, chars, days=7)
        if r: send_discord_post("Weekly XP Totals", "🗓️ Period: **Last 7 Days**", r, 0x3498db, dates, "weekly")
        state["last_weekly"] = dates['yesterday_iso']

    if dates['is_first'] and state.get("last_monthly") != dates['yesterday_iso']:
        r = get_summed_xp(logs, chars, month_prefix=dates['month_filter'])
        if r: send_discord_post("Monthly XP Totals", f"🗓️ Month: **{dates['month_name']}**", r, 0xf1c40f, dates, "monthly")
        state["last_monthly"] = dates['yesterday_iso']

    if daily_ranks and state.get("last_daily") != dates['yesterday_iso']:
        sub_text = f"🗓️ Date: **{dates['yesterday_display']}**"
        if king_died_msg:
            sub_text += king_died_msg
        send_discord_post("Daily Champion", sub_text, daily_ranks, 0x2ecc71, dates, "daily", pb_list=daily_pb_achievers)
        state["last_daily"] = dates['yesterday_iso']

    save_json(STATE_PATH, state)

if __name__ == "__main__":
    main()
