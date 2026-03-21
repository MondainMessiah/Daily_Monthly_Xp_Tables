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
STREAKS_PATH = BASE_DIR / "streaks.json"
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

# --- DATA PROCESSING ---
def fetch_total_xp(name):
    url = f"https://api.tibiadata.com/v4/character/{name.replace(' ', '%20')}"
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            return r.json().get("character", {}).get("character", {}).get("experience", 0)
    except: pass
    return 0

def get_ranking(logs, date_list):
    """Calculates sums for a specific range of dates."""
    rank = []
    for name, history in logs.items():
        total = 0
        for d in date_list:
            val = history.get(d, "0").replace(",", "").replace("+", "")
            total += int(val)
        rank.append((name, total))
    return sorted(rank, key=lambda x: x[1], reverse=True)

# --- VISUAL DASHBOARD ---
def send_discord_post(title, date_label, ranking, team_change=None):
    if not ranking or ranking[0][1] <= 0: return
    
    max_xp = ranking[0][1]
    total_team_xp = sum(v for n, v in ranking)
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    fields = []

    # Top 3 with Full Bars
    for i, (name, xp) in enumerate(ranking[:3]):
        pct = int((xp / max_xp) * 100) if max_xp > 0 else 0
        bar_count = round(pct / 10)
        bar = "🟩" * bar_count + "⬛" * (10 - bar_count)
        
        streak_str = ""
        if "Daily" in title and i == 0:
            streaks = load_json(STREAKS_PATH)
            if streaks.get("last") == name: streaks["count"] += 1
            else: streaks["last"], streaks["count"] = name, 1
            save_json(STREAKS_PATH, streaks)
            streak_str = f" 🔥 {streaks['count']}" if streaks['count'] < 5 else f" 👑 {streaks['count']}"

        fields.append({
            "name": f"{medals[i]} **{name}**{streak_str}",
            "value": f"**+{xp:,} XP**\n{bar} `{pct}%`",
            "inline": False
        })

    # Others List
    others = [f"**{idx}. {n}** (`+{v:,} XP`)" for idx, (n, v) in enumerate(ranking[3:5], 4) if v > 0]
    if others:
        fields.append({"name": "--- Other Gains ---", "value": "\n".join(others)})

    footer = f"Team Total: {total_team_xp:,} XP"
    if team_change: footer += f" ({team_change} vs last daily)"
    footer += "\n⭐ = New PB | 🔥 = 1-4 Streak | 👑 = 5+ Streak"

    payload = {
        "embeds": [{
            "title": f"🏆 {title} 🏆",
            "description": f"🗓️ Date: **{date_label}**",
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

    # 1. FETCH & UPDATE LOGS (Safe Append)
    print(f"📡 Updating API Totals for {dates['today']}...")
    for name in chars:
        current_total = fetch_total_xp(name)
        if current_total == 0: continue
        
        prev_total = totals.get(name, 0)
        if prev_total > 0:
            gain = current_total - prev_total
            if gain >= 0:
                if name not in logs: logs[name] = {}
                logs[name][dates["today"]] = f"+{gain:,}"
        
        totals[name] = current_total
    
    save_json(TOTALS_PATH, totals)
    save_json(LOG_PATH, logs)

    # 2. DAILY POST (Yesterday)
    yest = dates["yesterday"]
    if state.get("last_daily") != yest:
        rank_y = get_ranking(logs, [yest])
        if rank_y:
            # Team Change Math
            team_y = sum(v for n, v in rank_y)
            rank_db = get_ranking(logs, [dates["day_before"]])
            team_db = sum(v for n, v in rank_db)
            change = f"{((team_y - team_db)/team_db)*100:+.1f}%" if team_db > 0 else "0%"
            
            send_discord_post("Daily Champion", yest, rank_y, change)
            state["last_daily"] = yest
            save_json(STATE_PATH, state)
            print(f"🚀 Daily Post Sent for {yest}!")

    # 3. WEEKLY POST (Mondays)
    if dates["is_monday"] and state.get("last_weekly") != yest:
        last_7 = [(dates["dt"] - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, 8)]
        rank_w = get_ranking(logs, last_7)
        send_discord_post("Weekly Champion", f"Week ending {yest}", rank_w)
        state["last_weekly"] = yest
        save_json(STATE_PATH, state)
        print("🚀 Weekly Post Sent!")

    # 4. MONTHLY POST (1st of the Month)
    if dates["is_first"] and state.get("last_monthly") != yest:
        first_last_month = (dates["dt"].replace(day=1) - timedelta(days=1)).replace(day=1)
        month_str = first_last_month.strftime("%Y-%m")
        month_dates = [d for d in next(iter(logs.values())).keys() if d.startswith(month_str)]
        rank_m = get_ranking(logs, month_dates)
        send_discord_post("Monthly Champion", first_last_month.strftime("%B %Y"), rank_m)
        state["last_monthly"] = yest
        save_json(STATE_PATH, state)
        print("🚀 Monthly Post Sent!")

if __name__ == "__main__":
    main()
