import os
import json
import requests
import re
import urllib.parse
import time
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

# --- 🎬 GIF CONFIGURATION ---
KING_GIF = "https://media.giphy.com/media/Sgx2d1QnSBnNEDnE96/giphy.gif"
BROKEN_GIF = "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExN3JueXZueXpueXpueXpueXpueXpueXpueXpueXpueXpueXpueXpueCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/hStvd5LiWCF3Y6No7C/giphy.gif"

# ==========================================
# 🛠️ SCRAPER & PB ENGINE
# ==========================================
def fetch_guildstats_gain(name, dates):
    bridge_url = os.environ.get("GOOGLE_BRIDGE_URL")
    if not bridge_url: return "NO_URL"
    formatted_name = name.replace(' ', '+')
    target_url = f"https://guildstats.eu/include/character/tab.php?nick={formatted_name}&tab=experience"
    final_url = f"{bridge_url}?url={urllib.parse.quote(target_url)}"
    try:
        r = requests.get(final_url, timeout=45)
        if r.status_code != 200: return 0
        rows = r.text.split('<tr')
        for row in rows:
            if dates['yesterday_iso'] in row:
                match = re.search(r"text-(?:green|red)-400\">([+-][\d,.]+)", row)
                if match:
                    raw_val = match.group(1)
                    is_neg = '-' in raw_val
                    clean_val = "".join(c for c in raw_val if c.isdigit())
                    if clean_val:
                        val = int(clean_val)
                        if val > MAX_XP_THRESHOLD: return 0
                        return -val if is_neg else val
        return 0
    except: return 0

def update_personal_best(name, current_gain):
    pb_data = load_json(PB_PATH, {})
    current_gain = int(current_gain)
    if current_gain <= 0: return False
    old_pb = pb_data.get(name, 0)
    if current_gain > old_pb:
        pb_data[name] = current_gain
        save_json(PB_PATH, pb_data)
        return True if old_pb > 0 else False
    return False

# ==========================================
# 🔥 THE DYNASTY ENGINE (V42)
# ==========================================
def update_period_streak(category, winner_name):
    """Manages streaks and the permanent Reigning King status."""
    all_streaks = load_json(STREAKS_PATH, {"daily":{}, "weekly":{}, "monthly":{}, "reigning_king": ""})
    
    data = all_streaks.get(category, {})
    last_winner = data.get("last_winner", "")
    last_count = data.get("count", 0)
    reigning_king = all_streaks.get("reigning_king", "")
    
    broken_msg, crown_msg, event_gif = "", "", None

    # Update Consecutive Win Count
    if last_winner == winner_name:
        new_count = last_count + 1
    else:
        if last_count >= 2:
            broken_msg = f"\n💔 **{last_winner}**'s streak of **{last_count}** was broken by **{winner_name}**!"
            if last_winner == reigning_king:
                broken_msg += " The King has fallen, but the crown remains in the vault..."
            event_gif = BROKEN_GIF
        new_count = 1
    
    # Check for Coronation (Daily Only)
    if category == "daily":
        if new_count >= 5:
            if winner_name != reigning_king:
                crown_msg = f"\n👑 **A NEW KING HAS BEEN CROWNED!** 👑\n**{winner_name}** has usurped the throne with a 5-day streak!"
                all_streaks["reigning_king"] = winner_name
            else:
                crown_msg = f"\n👑 **THE KING EXTENDS HIS REIGN!** 👑\n**{winner_name}** is on a **{new_count} day** win streak!"
            event_gif = KING_GIF

    # Save data
    all_streaks[category] = {"last_winner": winner_name, "count": new_count}
    save_json(STREAKS_PATH, all_streaks)
    
    # Return visual info for the winner
    icon = ""
    if category == "daily":
        icon = "👑" if winner_name == all_streaks["reigning_king"] else "🔥"
    elif new_count > 1:
        icon = "🔥"
        
    return icon, new_count, broken_msg, crown_msg, event_gif, all_streaks["reigning_king"]

# ==========================================
# 📊 VISUAL POST ENGINE
# ==========================================
def send_discord_post(title, subtitle, ranking, color, dates, streak_cat=None, pb_list=None):
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook or not ranking: return
    pb_list = pb_list or []
    max_xp = ranking[0][1]
    curr_total = sum(item[1] for item in ranking)
    
    streak_label, broken_msg, crown_msg, final_gif, current_king = "", "", "", None, ""
    
    if streak_cat:
        icon, count, b_msg, c_msg, e_gif, king = update_period_streak(streak_cat, ranking[0][0])
        broken_msg, crown_msg, final_gif, current_king = b_msg, c_msg, e_gif, king
        if count > 1 or streak_cat == "daily":
            streak_label = f" {icon} {count}"
    else:
        # Just check who is king for non-streak posts
        current_king = load_json(STREAKS_PATH, {}).get("reigning_king", "")

    full_desc = subtitle
    if broken_msg: full_desc += broken_msg
    if crown_msg: full_desc += crown_msg

    fields = []
    medals = ["🥇", "🥈", "🥉"]
    for i, (name, xp) in enumerate(ranking[:3]):
        pb_star = " ⭐️" if name in pb_list else ""
        
        # Determine labels: Winner gets the streak count, King gets a permanent crown
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
        pb_star = " ⭐️" if name in pb_list else ""
        king_tag = " 👑" if name == current_king else ""
        others.append(f"**{name}**{king_tag} (`{xp:+,} XP`){pb_star}")
    if others: fields.append({"name": "--- Other Gains ---", "value": "\n".join(others), "inline": False})

    embed = {
        "title": f"🏆 {title} 🏆", "description": full_desc, "fields": fields, "color": color,
        "footer": {"text": f"Team Total: {curr_total:,} XP\n⭐️ = New PB | 🔥 = Streak | 👑 = Reigning King"}
    }
    if final_gif: embed["image"] = {"url": final_gif}
    requests.post(webhook, json={"embeds": [embed]})

# ==========================================
# ⚙️ HELPERS
# ==========================================
def make_bar(val, max_val):
    if max_val <= 0: return "⬛" * 10
    filled = max(0, min(10, round((val / max_val) * 10)))
    return "🟩" * filled + "⬛" * (10 - filled)

def load_json(path, fallback=None):
    if not path.exists(): return fallback if fallback is not None else {}
    try:
        with open(path, "r") as f:
            content = f.read().strip()
            return json.loads(content) if content else fallback
    except: return fallback if fallback is not None else {}

def save_json(path, data):
    with open(path, "w") as f: json.dump(data, f, indent=2)

def get_dates():
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
    yesterday_obj = now - timedelta(days=1)
    return {
        "yesterday_iso": yesterday_obj.strftime("%Y-%m-%d"),
        "yesterday_display": yesterday_obj.strftime("%d-%m-%y"),
        "day_before_iso": (now - timedelta(days=2)).strftime("%Y-%m-%d"),
        "is_monday": now.weekday() == 0, "is_first": now.day == 1,
        "month_name": yesterday_obj.strftime("%B")
    }

def get_summed_xp(logs, chars, days):
    rankings = []
    today = datetime.now(ZoneInfo(TIMEZONE))
    target_dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, days + 1)]
    for name in chars:
        char_history = logs.get(name, {})
        total = 0
        for d in target_dates:
            v = char_history.get(d, "0")
            clean = "".join(c for c in str(v) if c.isdigit())
            if clean: total += int(clean) * (-1 if str(v).startswith('-') else 1)
        if total != 0: rankings.append((name, total))
    rankings.sort(key=lambda x: x[1], reverse=True)
    return rankings

def main():
    dates = get_dates()
    logs, state = load_json(LOG_PATH, {}), load_json(STATE_PATH, {})
    if not CHAR_FILE.exists(): return
    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]

    print(f"🌐 Scraping {dates['yesterday_iso']}...")
    daily_pb_achievers = []
    for name in chars:
        gain = fetch_guildstats_gain(name, dates)
        if name not in logs: logs[name] = {}
        logs[name][dates['yesterday_iso']] = f"{gain:+,}"
        if gain > 0 and update_personal_best(name, gain):
            daily_pb_achievers.append(name)
        time.sleep(1.5)
    
    save_json(LOG_PATH, logs)

    if dates['is_monday'] and state.get("last_weekly") != dates['yesterday_iso']:
        r = get_summed_xp(logs, chars, 7)
        if r: send_discord_post("Weekly Power Ranking", "📅 Period: **Last 7 Days**", r, 0x3498db, dates, "weekly")
        state["last_weekly"] = dates['yesterday_iso']

    if dates['is_first'] and state.get("last_monthly") != dates['yesterday_iso']:
        r = get_summed_xp(logs, chars, 31)
        if r: send_discord_post("Monthly Champion", f"📅 Month: **{dates['month_name']}**", r, 0xf1c40f, dates, "monthly")
        state["last_monthly"] = dates['yesterday_iso']

    daily_ranks = []
    for name in chars:
        v = logs.get(name, {}).get(dates['yesterday_iso'], "0")
        clean = "".join(c for c in str(v) if c.isdigit())
        if clean and int(clean) != 0:
            daily_ranks.append((name, int(clean) * (-1 if str(v).startswith('-') else 1)))

    if daily_ranks and state.get("last_daily") != dates['yesterday_iso']:
        daily_ranks.sort(key=lambda x: x[1], reverse=True)
        send_discord_post("Daily Champion", f"🗓️ Date: **{dates['yesterday_display']}**", daily_ranks, 0x2ecc71, dates, "daily", pb_list=daily_pb_achievers)
        state["last_daily"] = dates['yesterday_iso']

    save_json(STATE_PATH, state)

if __name__ == "__main__":
    main()
