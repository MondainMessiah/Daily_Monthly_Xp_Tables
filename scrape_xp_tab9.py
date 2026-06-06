import os
import json
import requests
import re
import urllib.parse
import time
import random
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

# --- 🎬 GIF CONFIGURATION (VERIFIED GOT KING POOL) ---
KING_GIFS = [
    "https://i.giphy.com/vX79ZAsCNe6n6.gif",      # Robert Baratheon
    "https://i.giphy.com/p6jVTOTCo63cs.gif",      # Joffrey Baratheon
    "https://i.giphy.com/8v3EErE79ZOpq.gif",      # Robb Stark
    "https://i.giphy.com/26vUJAbhM8kHhA8X6.gif",   # Jon Snow
    "https://i.giphy.com/l41YedIBvT817KOF2.gif"    # Tommen Baratheon
]

# ==========================================
# 🛠️ THE DATA SCRAPER
# ==========================================
def fetch_data(name, dates):
    bridge_url = os.environ.get("GOOGLE_BRIDGE_URL")
    if not bridge_url: return 0
    formatted_name = "+".join([word.capitalize() for word in name.split()])
    target_url = f"https://guildstats.eu/include/character/tab.php?nick={formatted_name}&tab=experience"
    final_url = f"{bridge_url}?url={urllib.parse.quote(target_url)}"
    try:
        r = requests.get(final_url, timeout=45)
        if r.status_code != 200: return 0
        
        # Pull XP
        xp_gain = 0
        rows = r.text.split('<tr')
        for row in rows:
            if dates['yesterday_iso'] in row:
                match = re.search(r"text-(?:green|red)-400\">([+-][\d,.]+)", row)
                if match:
                    raw_val = match.group(1)
                    digits = "".join(c for c in raw_val if c.isdigit())
                    if digits:
                        val = int(digits)
                        if val < MAX_XP_THRESHOLD:
                            xp_gain = -val if '-' in raw_val else val
        return xp_gain
    except: return 0

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
    
    if last_winner != winner_name:
        if last_count >= 2 and category == "daily":
            broken_msg = f"\n💔 **{last_winner}**'s streak of **{last_count}** was broken by **{winner_name}**!"
            if last_winner == reigning_king:
                broken_msg += " The King has fallen..."
        new_count = 1
    else:
        new_count = last_count + 1
        
    if category == "daily" and new_count >= 5:
        selected_gif = random.choice(KING_GIFS)
        if winner_name != reigning_king:
            king_msg = f"\n👑 **A NEW KING HAS BEEN CROWNED!** 👑\n**{winner_name}** has usurped the throne!"
            all_streaks["reigning_king"] = winner_name
            event_gif = selected_gif
        else:
            king_msg = f"\n👑 **THE KING EXTENDS HIS REIGN!** 👑\n**{winner_name}** is on a **{new_count} day** streak!"
            event_gif = selected_gif
            
    all_streaks[category] = {"last_winner": winner_name, "count": new_count}
    save_json(STREAKS_PATH, all_streaks)
    
    updated_king = all_streaks.get("reigning_king", "")
    icon = "👑" if (category == "daily" and winner_name == updated_king) else ("🔥" if new_count >= 2 else "")
    return icon, new_count, broken_msg, king_msg, event_gif, updated_king

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
    
    streak_label, broken_msg, king_msg, final_gif, current_king = "", "", "", None, ""
    if streak_cat:
        icon, count, b_msg, k_msg, e_gif, king = update_period_streak(streak_cat, ranking[0][0])
        broken_msg, king_msg, final_gif, current_king = b_msg, k_msg, e_gif, king
        if icon == "👑": streak_label = f" {icon}"
        elif count >= 2: streak_label = f" {icon} {count}"
    else:
        current_king = load_json(STREAKS_PATH, {}).get("reigning_king", "")

    full_desc = subtitle
    if broken_msg: full_desc += broken_msg
    if king_msg: full_desc += king_msg

    fields = []
    medals = ["🥇", "🥈", "🥉"]
    for i, (name, xp) in enumerate(ranking[:3]):
        pb_star = " ⭐️" if name in pb_list else ""
        king_tag = " 👑" if (name == current_king and (i != 0 or streak_cat != "daily")) else ""
        s_label = streak_label if (i == 0 and streak_cat) else king_tag
        pct = int((xp / max_xp) * 100) if max_xp > 0 else 0
        fields.append({
            "name": f"{medals[i]} {name}{s_label}{pb_star}",
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

# ==========================================
# ⚙️ HELPERS & MAIN ENGINE
# ==========================================
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
                    val_str = str(v)
                    digits = "".join(c for c in val_str if c.isdigit())
                    if digits:
                        total += int(digits) * (-1 if val_str.startswith('-') else 1)
        else:
            for d in target_dates:
                v = char_history.get(d)
                if v:
                    val_str = str(v)
                    digits = "".join(c for c in val_str if c.isdigit())
                    if digits:
                        total += int(digits) * (-1 if val_str.startswith('-') else 1)
        
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

def get_dates():
    tz = ZoneInfo(TIMEZONE); now = datetime.now(tz); yesterday_obj = now - timedelta(days=1)
    return { "yesterday_iso": yesterday_obj.strftime("%Y-%m-%d"), "yesterday_display": yesterday_obj.strftime("%d-%m-%y"), "month_filter": yesterday_obj.strftime("%Y-%m"), "is_monday": now.weekday() == 0, "is_first": now.day == 1, "month_name": yesterday_obj.strftime("%B") }

def main():
    dates = get_dates(); logs, state = load_json(LOG_PATH), load_json(STATE_PATH)
    if not CHAR_FILE.exists(): return
    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]

    print(f"🌐 Scraping {dates['yesterday_iso']}...")
    current_scrapes = {}; daily_pb_achievers = []; total_non_zero = 0

    for name in chars:
        gain = fetch_data(name, dates)
        current_scrapes[name] = gain
        if gain != 0: total_non_zero += 1
        time.sleep(1.5)

    if total_non_zero == 0:
        print(f"🛑 ANTI-ZERO TRIGGERED."); return 

    for name, gain in current_scrapes.items():
        if name not in logs: logs[name] = {}
        logs[name][dates['yesterday_iso']] = f"{gain:+,}"
        if gain > 0 and update_personal_best(name, gain): daily_pb_achievers.append(name)
    
    save_json(LOG_PATH, logs)

    # ⚔️ KING DEATH ENGINE: Strip crown if King drops daily XP ⚔️
    all_streaks = load_json(STREAKS_PATH, {"daily":{}, "weekly":{}, "monthly":{}, "reigning_king": ""})
    reigning_king = all_streaks.get("reigning_king", "")
    king_died_msg = ""
    
    if reigning_king and current_scrapes.get(reigning_king, 0) < 0:
        loss_xp = current_scrapes[reigning_king]
        king_died_msg = f"\n\n💀 **THE KING HAS DIED IN BATTLE!** 💀\n**{reigning_king}** lost `{loss_xp:+,} XP` and has been stripped of the crown! The throne is vacant!"
        all_streaks["reigning_king"] = ""
        if all_streaks.get("daily", {}).get("last_winner") == reigning_king:
            all_streaks["daily"] = {"last_winner": "", "count": 0}
        save_json(STREAKS_PATH, all_streaks)

    if dates['is_monday'] and state.get("last_weekly") != dates['yesterday_iso']:
        r = get_summed_xp(logs, chars, days=7)
        if r: send_discord_post("Weekly XP Totals", "🗓️ Period: **Last 7 Days**", r, 0x3498db, dates, "weekly")
        state["last_weekly"] = dates['yesterday_iso']

    if dates['is_first'] and state.get("last_monthly") != dates['yesterday_iso']:
        r = get_summed_xp(logs, chars, month_prefix=dates['month_filter'])
        if r: send_discord_post("Monthly XP Totals", f"🗓️ Month: **{dates['month_name']}**", r, 0xf1c40f, dates, "monthly")
        state["last_monthly"] = dates['yesterday_iso']

    daily_ranks = [(name, gain) for name, gain in current_scrapes.items() if gain != 0]
    if daily_ranks and state.get("last_daily") != dates['yesterday_iso']:
        daily_ranks.sort(key=lambda x: x[1], reverse=True)
        
        sub_text = f"🗓️ Date: **{dates['yesterday_display']}**"
        if king_died_msg:
            sub_text += king_died_msg
            
        send_discord_post("Daily Champion", sub_text, daily_ranks, 0x2ecc71, dates, "daily", pb_list=daily_pb_achievers)
        state["last_daily"] = dates['yesterday_iso']

    save_json(STATE_PATH, state)

if __name__ == "__main__":
    main()
