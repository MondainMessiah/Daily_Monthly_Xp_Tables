import os
import json
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

# --- CONFIGURATION ---
BASE_DIR = Path(__file__).resolve().parent
CHAR_FILE = BASE_DIR / "characters.txt"
LOG_PATH = BASE_DIR / "xp_log.json"       # Historical Daily Gains
TOTALS_PATH = BASE_DIR / "xp_totals.json" # Last known total XP
STATE_PATH = BASE_DIR / "post_state.json"
STREAKS_PATH = BASE_DIR / "streaks.json"  # Streak memory
TIMEZONE = "Europe/London"

def get_dates():
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
    return {
        "today": now.strftime("%Y-%m-%d"),
        "yesterday": (now - timedelta(days=1)).strftime("%Y-%m-%d"),
        "day_before": (now - timedelta(days=2)).strftime("%Y-%m-%d"),
        "is_monday": now.weekday() == 0,
        "is_first": now.day == 1,
        "obj": now
    }

def load_json(path):
    if path.exists():
        try:
            with open(path, "r") as f: return json.load(f)
        except: pass
    return {}

def save_json(path, data):
    with open(path, "w") as f: json.dump(data, f, indent=2)

# --- VISUAL TOOLS ---
def make_bar(val, max_val):
    if max_val <= 0: return "⬛" * 10
    pct = (val / max_val)
    filled = round(pct * 10)
    return "🟩" * filled + "⬛" * (10 - filled)

# --- DATA ENGINE ---
def fetch_xp(name):
    url = f"https://api.tibiadata.com/v4/character/{name.replace(' ', '%20')}"
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            return r.json().get("character", {}).get("character", {}).get("experience", 0)
    except: pass
    return 0

def get_ranking(logs, date_list):
    rank = []
    for name, history in logs.items():
        total = sum(int(str(history.get(d, 0)).replace(",", "").replace("+", "")) for d in date_list)
        rank.append((name, total))
    return sorted(rank, key=lambda x: x[1], reverse=True)

# --- DISCORD EMBED BUILDER ---
def send_post(title, date_label, ranking, team_total, team_change):
    if not ranking or ranking[0][1] <= 0: return
    
    max_xp = ranking[0][1]
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    fields = []
    description_addon = ""

    # 1. PROCESS STREAK LOGIC (Daily Only)
    streak_display = ""
    if "Daily" in title:
        streaks = load_json(STREAKS_PATH)
        winner_name = ranking[0][0]
        old_winner = streaks.get("last_winner")
        old_count = streaks.get("count", 0)

        if old_winner == winner_name:
            streaks["count"] = old_count + 1
        else:
            # CHECK FOR STREAK ENDED
            if old_winner and old_count >= 2:
                description_addon = f"\n⚔️ **{winner_name}** has ended **{old_winner}'s** `{old_count}` day streak!"
            
            streaks["last_winner"] = winner_name
            streaks["count"] = 1
        
        save_json(STREAKS_PATH, streaks)
        
        icon = "`👑`" if streaks['count'] >= 5 else "`🔥`"
        streak_display = f" {icon} `{streaks['count']}`"

    # 2. BUILD TOP 3
    for i, (name, xp) in enumerate(ranking[:3]):
        pct = int((xp / max_xp) * 100) if max_xp > 0 else 0
        display_streak = streak_display if i == 0 and "Daily" in title else ""
        
        fields.append({
            "name": f"{medals[i]} **{name}**{display_streak}",
            "value": f"`+{xp:,} XP`\n{make_bar(xp, max_xp)} `{pct}%`",
            "inline": False
        })

    # 3. OTHER GAINS
    others = [f"**{idx+1}. {n}** (`+{v:,} XP`)" for idx, (n, v) in enumerate(ranking[3:5]) if v > 0]
    if others:
        fields.append({"name": "--- Other Gains ---", "value": "\n".join(others)})

    footer = f"Team Total: {team_total:,} XP ({team_change} vs last daily)"
    footer += "\n⭐ = New PB | `🔥 = 1-4 Streak` | `👑 = 5+ Streak`"

    payload = {
        "embeds": [{
            "title": f"🏆 {title} 🏆",
            "description": f"🗓️ Date: **{date_label}**{description_addon}",
            "fields": fields,
            "color": 0x2ecc71,
            "footer": {"text": footer}
        }]
    }
    requests.post(os.environ.get("DISCORD_WEBHOOK_URL"), json=payload)

# --- MAIN ENGINE ---
def main():
    dates = get_dates()
    logs = load_json(LOG_PATH)
    totals = load_json(TOTALS_PATH)
    state = load_json(STATE_PATH)
    
    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]

    # UPDATE LOGS
    print(f"📡 Updating API Totals for {dates['today']}...")
    for name in chars:
        current_total = fetch_xp(name)
        if current_total == 0: continue
        
        last_total = totals.get(name, 0)
        if last_total > 0:
            gain = current_total - last_total
            if gain >= 0:
                if name not in logs: logs[name] = {}
                logs[name][dates["today"]] = f"+{gain:,}"
        
        totals[name] = current_total
    
    save_json(TOTALS_PATH, totals)
    save_json(LOG_PATH, logs)

    # DAILY (Yesterday)
    yest = dates["yesterday"]
    if state.get("last_daily") != yest:
        rank_y = get_ranking(logs, [yest])
        if rank_y:
            team_y = sum(v for n, v in rank_y)
            rank_db = get_ranking(logs, [dates["day_before"]])
            team_db = sum(v for n, v in rank_db)
            change = f"{((team_y - team_db)/team_db)*100:+.1f}%" if team_db > 0 else "0%"
            
            send_post("Daily Champion", yest, rank_y, team_y, change)
            state["last_daily"] = yest
            save_json(STATE_PATH, state)

    # WEEKLY (Mondays)
    if dates["is_monday"] and state.get("last_weekly") != yest:
        last_7 = [(dates["obj"] - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, 8)]
        rank_w = get_ranking(logs, last_7)
        send_post("Weekly Champion", f"Week of {yest}", rank_w, sum(v for n, v in rank_w), "")
        state["last_weekly"] = yest
        save_json(STATE_PATH, state)

    # MONTHLY (1st)
    if dates["is_first"] and state.get("last_monthly") != yest:
        first_of_last = (dates["obj"].replace(day=1) - timedelta(days=1)).replace(day=1)
        month_str = first_of_last.strftime("%Y-%m")
        month_dates = [d for d in next(iter(logs.values())).keys() if d.startswith(month_str)]
        rank_m = get_ranking(logs, month_dates)
        send_post("Monthly Champion", first_of_last.strftime("%B %Y"), rank_m, sum(v for n, v in rank_m), "")
        state["last_monthly"] = yest
        save_json(STATE_PATH, state)

if __name__ == "__main__":
    main()
