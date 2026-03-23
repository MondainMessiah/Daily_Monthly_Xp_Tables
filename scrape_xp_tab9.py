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
PB_PATH = BASE_DIR / "personal_bests.json" # <--- Your PB file
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
# ⭐ THE PB ENGINE (V31 - Dedicated File)
# ==========================================
def handle_pb_check(name, current_gain):
    """Reads from personal_bests.json and updates if a record is broken."""
    pb_data = load_json(PB_PATH, {})
    
    # Get old PB (if it exists)
    old_pb = pb_data.get(name, 0)
    
    if current_gain > old_pb:
        # Save new record immediately
        pb_data[name] = current_gain
        save_json(PB_PATH, pb_data)
        
        # Only show the star if they actually had a previous record (prevents star on 1st run)
        return True if old_pb > 0 else False
        
    return False

# ==========================================
# 🔥 TRIPLE-TRACK STREAK ENGINE
# ==========================================
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
# 📊 SUMMARY LOGIC
# ==========================================
def get_summed_xp(logs, chars, days_to_look_back):
    rankings = []
    tz = ZoneInfo(TIMEZONE)
    today = datetime.now(tz)
    target_dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, days_to_look_back + 1)]

    for name in chars:
        char_history = logs.get(name, {})
        total_period_xp = 0
        for d in target_dates:
            val = char_history.get(d, "0")
            clean_val = "".join(c for c in str(val) if c.isdigit())
            if clean_val:
                num = int(clean_val)
                total_period_xp += -num if str(val).startswith('-') else num
        if total_period_xp != 0:
            rankings.append((name, total_period_xp))
    rankings.sort(key=lambda x: x[1], reverse=True)
    return rankings

def send_discord_post(title, ranking, color, streak_cat=None):
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook or not ranking: return
    
    max_xp = ranking[0][1]
    total_xp = sum(item[1] for item in ranking)
    fields = []
    
    streak_label = ""
    if streak_cat:
        icon, count = update_period_streak(streak_cat, ranking[0][0])
        if count > 1 or streak_cat == "daily":
            streak_label = f" {icon} `{count}`"

    for i, (name, xp) in enumerate(ranking[:5]):
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
        m = medals[i] if i < 5 else "🔹"
        
        # ⭐ PB Check using the dedicated file
        # (We only show stars on the Daily Champion post to keep it special)
        pb_star = " ⭐️" if (streak_cat == "daily" and handle_pb_check(name, xp)) else ""
        
        display_name = f"**{name}**{streak_label}{pb_star}" if (i == 0) else f"**{name}**{pb_star}"
        pct = int((xp / max_xp) * 100) if max_xp > 0 else 0
        bar = "🟩" * round(pct/10) + "⬛" * (10 - round(pct/10))
        
        fields.append({
            "name": f"{m} {display_name}",
            "value": f"`{xp:+,} XP`\n{bar} `{pct}%`",
            "inline": False if i < 3 else True
        })

    payload = {
        "embeds": [{
            "title": f"🏆 {title} 🏆",
            "fields": fields,
            "color": color,
            "footer": {"text": f"Total Team Progress: {total_xp:+,} XP | ⭐️ = New Personal Best"}
        }]
    }
    requests.post(webhook, json=payload)

# ==========================================

def get_dates():
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
    return {
        "yesterday_iso": (now - timedelta(days=1)).strftime("%Y-%m-%d"),
        "is_monday": now.weekday() == 0,
        "is_first": now.day == 1,
        "month_name": (now - timedelta(days=1)).strftime("%B")
    }

def load_json(path, fallback=None):
    if not path.exists(): return fallback if fallback is not None else {}
    try:
        with open(path, "r") as f: 
            content = f.read().strip()
            if not content: return fallback
            return json.loads(content)
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

    # 1. WEEKLY
    if dates['is_monday'] and state.get("last_weekly") != dates['yesterday_iso']:
        weekly_ranks = get_summed_xp(logs, chars, 7)
        if weekly_ranks:
            send_discord_post("Weekly Power Ranking", weekly_ranks, 0x3498db, streak_cat="weekly")
            state["last_weekly"] = dates['yesterday_iso']

    # 2. MONTHLY
    if dates['is_first'] and state.get("last_monthly") != dates['yesterday_iso']:
        monthly_ranks = get_summed_xp(logs, chars, 31)
        if monthly_ranks:
            send_discord_post(f"Monthly Champion: {dates['month_name']}", monthly_ranks, 0xf1c40f, streak_cat="monthly")
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
        send_discord_post("Daily Champion", daily_ranks, 0x2ecc71, streak_cat="daily")
        state["last_daily"] = dates['yesterday_iso']

    save_json(STATE_PATH, state)

if __name__ == "__main__":
    main()
