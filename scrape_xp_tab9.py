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

# ==========================================
# 🛠️ THE GUILDSTATS TAILWIND SNIPER
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
        pattern = rf"{dates['yesterday_iso']}.*?text-(?:green|red)-400\">([+-][\d,.]+)"
        match = re.search(pattern, r.text, re.IGNORECASE | re.DOTALL)
        if match:
            raw_val = match.group(1)
            is_neg = '-' in raw_val
            clean_val = "".join(c for c in raw_val if c.isdigit())
            if clean_val:
                val = int(clean_val)
                if val > 500000000: return 0 
                return -val if is_neg else val
        return 0
    except: return 0

# ==========================================
# 🔥 PERSISTENCE ENGINES (PB & STREAKS)
# ==========================================
def handle_pb_check(name, current_gain):
    pb_data = load_json(PB_PATH, {})
    old_pb = pb_data.get(name, 0)
    if current_gain > old_pb:
        pb_data[name] = current_gain
        save_json(PB_PATH, pb_data)
        return True if old_pb > 0 else False
    return False

def update_period_streak(category, winner_name):
    all_streaks = load_json(STREAKS_PATH, {"daily":{}, "weekly":{}, "monthly":{}})
    if category not in all_streaks: all_streaks[category] = {}
    data = all_streaks[category]
    last_winner = data.get("last_winner", "")
    current_count = data.get("count", 0)
    if last_winner == winner_name:
        new_count = current_count + 1
    else:
        new_count = 1
    all_streaks[category] = {"last_winner": winner_name, "count": new_count}
    save_json(STREAKS_PATH, all_streaks)
    
    if category == "daily":
        icon = "👑" if new_count >= 5 else "🔥"
    else:
        icon = "🔥" if new_count > 1 else ""
    return icon, new_count

# ==========================================
# 📊 VISUAL POST ENGINE (V34)
# ==========================================
def make_bar(val, max_val):
    if max_val <= 0: return "⬛" * 10
    filled = max(0, min(10, round((val / max_val) * 10)))
    return "🟩" * filled + "⬛" * (10 - filled)

def send_discord_post(title, subtitle, ranking, color, logs, dates, streak_cat=None):
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook or not ranking: return
    
    max_xp = ranking[0][1]
    curr_total = sum(item[1] for item in ranking)
    
    # Calculate % Change (Only for Daily)
    footer_extra = ""
    if streak_cat == "daily":
        prev_total = 0
        for name, _ in ranking:
            v = logs.get(name, {}).get(dates['day_before_iso'], "0")
            clean = "".join(c for c in str(v) if c.isdigit())
            if clean: prev_total += int(clean)
        if prev_total > 0:
            diff = ((curr_total - prev_total) / prev_total) * 100
            footer_extra = f" ({diff:+.1f}% vs last daily)"

    streak_label = ""
    if streak_cat:
        icon, count = update_period_streak(streak_cat, ranking[0][0])
        if count > 1 or streak_cat == "daily":
            streak_label = f" {icon} {count}"

    fields = []
    medals = ["🥇", "🥈", "🥉"]
    for i, (name, xp) in enumerate(ranking[:3]):
        pb_star = " ⭐" if (streak_cat == "daily" and handle_pb_check(name, xp)) else ""
        s_label = streak_label if i == 0 else ""
        pct = int((xp / max_xp) * 100) if max_xp > 0 else 0
        
        fields.append({
            "name": f"{medals[i]} {name}{s_label}{pb_star}",
            "value": f"`{xp:+,} XP`\n{make_bar(xp, max_xp)} `{pct}%`",
            "inline": False
        })

    others = []
    for name, xp in ranking[3:10]:
        pb_star = " ⭐" if (streak_cat == "daily" and handle_pb_check(name, xp)) else ""
        others.append(f"**{name}** (`{xp:+,} XP`){pb_star}")
    
    if others:
        fields.append({"name": "--- Other Gains ---", "value": "\n".join(others), "inline": False})

    payload = {
        "embeds": [{
            "title": f"🏆 {title} 🏆",
            "description": subtitle,
            "fields": fields,
            "color": color,
            "footer": {
                "text": f"Team Total: {curr_total:,} XP{footer_extra}\n⭐ = New PB | 🔥 = 1-4 Streak | 👑 = 5+ Streak"
            }
        }]
    }
    requests.post(webhook, json=payload)

# ==========================================

def get_dates():
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
    yesterday_obj = now - timedelta(days=1)
    return {
        "yesterday_iso": yesterday_obj.strftime("%Y-%m-%d"),
        "yesterday_display": yesterday_obj.strftime("%d-%m-%y"),
        "day_before_iso": (now - timedelta(days=2)).strftime("%Y-%m-%d"),
        "is_monday": now.weekday() == 0,
        "is_first": now.day == 1,
        "month_name": yesterday_obj.strftime("%B")
    }

def load_json(path, fallback=None):
    if not path.exists(): return fallback if fallback is not None else {}
    try:
        with open(path, "r") as f: 
            content = f.read().strip()
            return json.loads(content) if content else fallback
    except: return fallback if fallback is not None else {}

def save_json(path, data):
    with open(path, "w") as f: json.dump(data, f, indent=2)

def main():
    dates = get_dates()
    logs, state = load_json(LOG_PATH, {}), load_json(STATE_PATH, {})
    if not CHAR_FILE.exists(): return
    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]

    print(f"🌐 Scraping for {dates['yesterday_iso']}...")
    scrape_success = False
    for name in chars:
        gain = fetch_guildstats_gain(name, dates)
        if gain != 0:
            if name not in logs: logs[name] = {}
            logs[name][dates['yesterday_iso']] = f"{gain:+,}"
            print(f"✅ {name}: {gain:+,} XP")
            scrape_success = True
            time.sleep(2)
    
    if scrape_success: save_json(LOG_PATH, logs)

    # 1. WEEKLY (Mondays)
    if dates['is_monday'] and state.get("last_weekly") != dates['yesterday_iso']:
        weekly_ranks = get_summed_xp(logs, chars, 7)
        if weekly_ranks:
            send_discord_post("Weekly Power Ranking", "📅 Period: **Last 7 Days**", weekly_ranks, 0x3498db, logs, dates, streak_cat="weekly")
            state["last_weekly"] = dates['yesterday_iso']

    # 2. MONTHLY (1st)
    if dates['is_first'] and state.get("last_monthly") != dates['yesterday_iso']:
        monthly_ranks = get_summed_xp(logs, chars, 31)
        if monthly_ranks:
            send_discord_post(f"Monthly Champion", f"📅 Month: **{dates['month_name']}**", monthly_ranks, 0xf1c40f, logs, dates, streak_cat="monthly")
            state["last_monthly"] = dates['yesterday_iso']

    # 3. DAILY
    daily_ranks = []
    for name in chars:
        v = logs.get(name, {}).get(dates['yesterday_iso'], "0")
        clean = "".join(c for c in str(v) if c.isdigit())
        if clean and int(clean) != 0:
            daily_ranks.append((name, int(clean) * (-1 if str(v).startswith('-') else 1)))

    if daily_ranks and state.get("last_daily") != dates['yesterday_iso']:
        daily_ranks.sort(key=lambda x: x[1], reverse=True)
        send_discord_post("Daily Champion", f"🗓️ Date: **{dates['yesterday_display']}**", daily_ranks, 0x2ecc71, logs, dates, streak_cat="daily")
        state["last_daily"] = dates['yesterday_iso']

    save_json(STATE_PATH, state)

def get_summed_xp(logs, chars, days):
    rankings = []
    today = datetime.now(ZoneInfo(TIMEZONE))
    target_dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, days + 1)]
    for name in chars:
        char_history = logs.get(name, {})
        total = 0
        for d in target_dates:
            val = char_history.get(d, "0")
            clean = "".join(c for c in str(val) if c.isdigit())
            if clean: total += int(clean) * (-1 if str(val).startswith('-') else 1)
        if total != 0: rankings.append((name, total))
    rankings.sort(key=lambda x: x[1], reverse=True)
    return rankings

if __name__ == "__main__":
    main()
