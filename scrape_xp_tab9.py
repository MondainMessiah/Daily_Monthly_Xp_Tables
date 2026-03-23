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
        # Jump over the date and find the first colored XP gain
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
# 🔥 STREAK ENGINE (V28 - CRASH PROOF)
# ==========================================
def update_streak(winner_name):
    """Tracks consecutive daily wins. Re-initializes if file is corrupted."""
    # Load and ensure keys exist
    raw_data = load_json(STREAKS_PATH, {})
    
    # If the file is old/wrong, reset it to a clean state
    if "last_winner" not in raw_data or "count" not in raw_data:
        streaks = {"last_winner": "", "count": 0}
    else:
        streaks = raw_data

    if streaks["last_winner"] == winner_name:
        streaks["count"] += 1
    else:
        streaks["last_winner"] = winner_name
        streaks["count"] = 1
    
    save_json(STREAKS_PATH, streaks)
    
    icon = "👑" if streaks["count"] >= 5 else "🔥"
    return icon, streaks["count"]

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

def send_discord_post(title, ranking, color, is_daily=False):
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook or not ranking: return
    
    max_xp = ranking[0][1]
    total_xp = sum(item[1] for item in ranking)
    fields = []
    
    streak_label = ""
    if is_daily:
        icon, count = update_streak(ranking[0][0])
        streak_label = f" {icon} `{count}`"

    for i, (name, xp) in enumerate(ranking[:5]):
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
        m = medals[i] if i < 5 else "🔹"
        display_name = f"**{name}**{streak_label}" if (i == 0 and is_daily) else f"**{name}**"
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
            "footer": {"text": f"Team Total: {total_xp:+,} XP | 🔥 = Streak | 👑 = 5+ Day Streak"}
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
        with open(path, "r") as f: return json.load(f)
    except: return fallback if fallback is not None else {}

def save_json(path, data):
    with open(path, "w") as f: json.dump(data, f, indent=2)

def main():
    dates = get_dates()
    logs, state = load_json(LOG_PATH), load_json(STATE_PATH)
    if not CHAR_FILE.exists(): return
    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]

    print(f"🌐 Scraping for {dates['yesterday_iso']}...")
    success = False
    for name in chars:
        gain = fetch_guildstats_gain(name, dates)
        if gain != 0:
            if name not in logs: logs[name] = {}
            logs[name][dates['yesterday_iso']] = f"{gain:+,}"
            print(f"✅ {name}: {gain:+,} XP")
            success = True
            time.sleep(2)
    
    if success: save_json(LOG_PATH, logs)

    # 1. WEEKLY SUMMARY
    if dates['is_monday'] and state.get("last_weekly") != dates['yesterday_iso']:
        weekly_ranks = get_summed_xp(logs, chars, 7)
        if weekly_ranks:
            send_discord_post("Weekly Power Ranking", weekly_ranks, 0x3498db)
            state["last_weekly"] = dates['yesterday_iso']

    # 2. MONTHLY SUMMARY
    if dates['is_first'] and state.get("last_monthly") != dates['yesterday_iso']:
        monthly_ranks = get_summed_xp(logs, chars, 31)
        if monthly_ranks:
            send_discord_post(f"Monthly Champion: {dates['month_name']}", monthly_ranks, 0xf1c40f)
            state["last_monthly"] = dates['yesterday_iso']

    # 3. DAILY RANKING
    daily_ranks = []
    for name in chars:
        v = logs.get(name, {}).get(dates['yesterday_iso'], "0")
        clean = "".join(c for c in str(v) if c.isdigit())
        if clean and int(clean) != 0:
            daily_ranks.append((name, int(clean) * (-1 if str(v).startswith('-') else 1)))

    if daily_ranks and state.get("last_daily") != dates['yesterday_iso']:
        daily_ranks.sort
