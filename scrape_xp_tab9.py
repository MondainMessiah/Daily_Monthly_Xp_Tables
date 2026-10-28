import os
import json
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

# --- CONFIGURATION ---
BASE_DIR = Path(__file__).resolve().parent
CHAR_FILE = BASE_DIR / "characters.txt"
LOG_PATH = BASE_DIR / "xp_log.json"
STATE_PATH = BASE_DIR / "post_state.json"
STREAKS_PATH = BASE_DIR / "streaks.json"
PB_PATH = BASE_DIR / "personal_bests.json"
TIMEZONE = "Europe/London"
MAX_XP_THRESHOLD = 200000000 
WORLD_NAME = "Celesta"

def get_dates():
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
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
# 🛠️ MULTI-VOCATION TIBIA.COM HIGHSCORES SCRAPER
# ==========================================
def fetch_tibia_com_highscores(target_names):
    """
    Scrapes official Tibia.com highscores across all vocations for Celesta 
    to capture exact experience points.
    """
    found_chars = {}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    # Vocations: 0 = All, 1 = Knights, 2 = Paladins, 3 = Sorcerers, 4 = Druids
    professions = [0, 1, 2, 3, 4]
    
    for prof in professions:
        if len(found_chars) >= len(target_names):
            break
            
        page_num = 1
        # Scan top pages per vocation category to find our tracked characters
        while page_num <= 5:
            url = f"https://www.tibia.com/community/?subtopic=highscores&world={WORLD_NAME}&category=0&profession={prof}&currentpage={page_num}"
            try:
                response = requests.get(url, headers=headers, timeout=15)
                if response.status_code != 200:
                    break
                    
                soup = BeautifulSoup(response.text, 'html.parser')
                table = soup.find('table', {'class': 'Table3'})
                if not table:
                    tables = soup.find_all('table')
                    for t in tables:
                        if 'Points' in t.text and 'Name' in t.text:
                            table = t
                            break
                if not table:
                    break

                rows = table.find_all('tr')
                row_count = 0
                for row in rows:
                    cols = row.find_all('td')
                    if len(cols) >= 5:
                        name_anchor = cols[1].find('a')
                        if name_anchor:
                            char_name = name_anchor.get_text().strip()
                            xp_text = cols[4].get_text().strip().replace(',', '')
                            if char_name in target_names and xp_text.isdigit():
                                found_chars[char_name] = int(xp_text)
                                row_count += 1
                                
                if row_count == 0 and page_num > 1:
                    break
                    
                page_num += 1
            except Exception as e:
                print(f"Error fetching highscores profession {prof} page {page_num}: {e}")
                break
                
    return found_chars

# ==========================================
# 🔥 ENGINES (Streak / PB / Post)
# ==========================================
def load_json(path, fallback=None):
    if not path.exists(): return fallback or {}
    try:
        with open(path, "r") as f:
            content = f.read().strip(); return json.loads(content) if content else (fallback or {})
    except: return fallback or {}

def save_json(path, data):
    with open(path, "w") as f: json.dump(data, f, indent=2)

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
    
    broken_msg, king_msg = "", ""
    
    if last_winner.strip().lower() != winner_name.strip().lower():
        if last_count >= 2 and category == "daily":
            broken_msg = f"\n💔 **{last_winner}**'s streak of **{last_count}** was broken by **{winner_name}**!"
        new_count = 1
    else:
        new_count = last_count + 1
        
    if category == "daily" and new_count >= 3:
        if winner_name.strip().lower() != reigning_king.strip().lower():
            king_msg = f"\n👑 **A NEW KING HAS BEEN CROWNED!** 👑\n**{winner_name}** has usurped the throne with a 3-day streak!"
            all_streaks["reigning_king"] = winner_name
        else:
            king_msg = f"\n👑 **THE KING EXTENDS HIS REIGN!** 👑\n**{winner_name}** is on a **{new_count} day** streak!"
            
    all_streaks[category] = {"last_winner": winner_name, "count": new_count}
    save_json(STREAKS_PATH, all_streaks)
    
    updated_king = all_streaks.get("reigning_king", "")
    return new_count, broken_msg, king_msg, updated_king, winner_name

def make_bar(val, max_val):
    if max_val <= 0: return "⬛" * 10
    filled = max(0, min(10, round((val / max_val) * 10)))
    return "🟩" * filled + "⬛" * (10 - filled)

def send_discord_post(title, subtitle, ranking, color, dates, streak_cat=None, pb_list=None):
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook or not ranking: return
    pb_list = pb_list or []
    max_xp = ranking[0][1] if ranking[0][1] > 0 else 1
    curr_total = sum(item[1] for item in ranking)
    
    top_winner = ranking[0][0] if ranking[0][1] > 0 else ""
    
    broken_msg, king_msg, current_king, streak_holder, streak_count = "", "", "", "", 0
    if streak_cat and top_winner:
        count, b_msg, k_msg, king, holder = update_period_streak(streak_cat, top_winner)
        broken_msg, king_msg, current_king, streak_holder, streak_count = b_msg, k_msg, king, holder, count
    else:
        current_king = load_json(STREAKS_PATH, {}).get("reigning_king", "")

    full_desc = subtitle
    if broken_msg: full_desc += broken_msg
    if king_msg: full_desc += king_msg

    fields = []
    medals = ["🥇", "🥈", "🥉"]
    
    gainers = [item for item in ranking if item[1] > 0]
    zeroers = [item for item in ranking if item[1] <= 0]

    for i, (name, xp) in enumerate(gainers[:3]):
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
    for name, xp in gainers[3:]:
        others.append(f"**{name}** (`{xp:+,} XP`){' ⭐️' if name in pb_list else ''}")
    for name, xp in zeroers:
        others.append(f"**{name}** (`0 XP`) 💤")

    if others:
        fields.append({"name": "--- Other Characters ---", "value": "\n".join(others), "inline": False})

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
        rankings.append((name, total))
            
    rankings.sort(key=lambda x: x[1], reverse=True)
    return rankings

def main():
    dates = get_dates(); logs, state = load_json(LOG_PATH), load_json(STATE_PATH)
    if not CHAR_FILE.exists(): return
    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]

    print(f"🌐 Fetching official Tibia.com highscores for {len(chars)} characters on {WORLD_NAME}...")
    current_totals = fetch_tibia_com_highscores(chars)
    
    current_scrapes = {}
    daily_pb_achievers = []
    total_non_zero = 0

    yesterday = dates['yesterday_iso']
    state_totals = load_json(BASE_DIR / "totals.json", {})

    for name in chars:
        current_xp = current_totals.get(name)
        if current_xp is None:
            print(f"⚠️ {name}: Not found in Tibia.com highscores.")
            current_scrapes[name] = 0
            continue
            
        old_total = state_totals.get(name)
        
        if old_total is not None:
            gain = current_xp - old_total
            if gain < -MAX_XP_THRESHOLD or gain > MAX_XP_THRESHOLD:
                gain = 0
        else:
            gain = 0
            
        state_totals[name] = current_xp
        current_scrapes[name] = gain
        if gain != 0: 
            total_non_zero += 1

    save_json(BASE_DIR / "totals.json", state_totals)

    if total_non_zero == 0 and not current_totals:
        print(f"🛑 ANTI-ZERO TRIGGERED: Could not fetch highscores.")
        return 

    for name, gain in current_scrapes.items():
        if name not in logs: logs[name] = {}
        logs[name][yesterday] = f"{gain:+,}"
        if gain > 0 and update_personal_best(name, gain): daily_pb_achievers.append(name)
    
    save_json(LOG_PATH, logs)

    daily_ranks = [(name, gain) for name, gain in current_scrapes.items()]
    daily_ranks.sort(key=lambda x: x[1], reverse=True)
    top_daily_winner = daily_ranks[0][0] if daily_ranks and daily_ranks[0][1] > 0 else ""

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

    if dates['is_monday'] and state.get("last_weekly") != yesterday:
        r = get_summed_xp(logs, chars, days=7)
        if r: send_discord_post("Weekly XP Totals", "🗓️ Period: **Last 7 Days**", r, 0x3498db, dates, "weekly")
        state["last_weekly"] = yesterday

    if dates['is_first'] and state.get("last_monthly") != yesterday:
        r = get_summed_xp(logs, chars, month_prefix=dates['month_filter'])
        if r: send_discord_post("Monthly XP Totals", f"🗓️ Month: **{dates['month_name']}**", r, 0xf1c40f, dates, "monthly")
        state["last_monthly"] = yesterday

    if daily_ranks and state.get("last_daily") != yesterday:
        sub_text = f"🗓️ Date: **{dates['yesterday_display']}**"
        if king_died_msg:
            sub_text += king_died_msg
        send_discord_post("Daily Champion", sub_text, daily_ranks, 0x2ecc71, dates, "daily", pb_list=daily_pb_achievers)
        state["last_daily"] = yesterday

    save_json(STATE_PATH, state)

if __name__ == "__main__":
    main()
