import os
import json
import requests
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

def load_json(path, fallback=None):
    if not path.exists(): return fallback if fallback is not None else {}
    try:
        with open(path, "r") as f: return json.load(f)
    except: return fallback if fallback is not None else {}

def save_json(path, data):
    with open(path, "w") as f: json.dump(data, f, indent=2)

def parse_xp(val):
    try: return int(str(val).replace(",", "").replace("+", "").strip())
    except: return 0

def make_bar(val, max_val):
    if max_val <= 0: return "⬛" * 10
    filled = round((val / max_val) * 10)
    return "🟩" * filled + "⬛" * (10 - filled)

def get_ranking_sum(logs, date_list, chars):
    rank = []
    for name in chars:
        history = logs.get(name, {})
        total = sum(parse_xp(history.get(d, 0)) for d in date_list)
        if total > 0: rank.append((name, total))
    return sorted(rank, key=lambda x: x[1], reverse=True)

# --- DISCORD POSTER ---
def send_discord_post(title, date_label, ranking, team_total=0, team_change=""):
    if not ranking: return
    
    max_xp = ranking[0][1]
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    fields = []
    description_addon = ""

    # 1. PROCESS STREAKS (Daily Only)
    streak_display = ""
    if "Daily" in title:
        streaks = load_json(STREAKS_PATH, {"daily": {"last_winner": "", "count": 0}})
        if "daily" not in streaks: streaks["daily"] = {"last_winner": "", "count": 0}
        winner_name = ranking[0][0]
        daily = streaks["daily"]

        if daily.get("last_winner") == winner_name:
            daily["count"] += 1
        else:
            if daily.get("last_winner") and daily.get("count", 0) >= 2:
                description_addon = f"\n⚔️ **{winner_name}** has ended **{daily['last_winner']}'s** `{daily['count']}` day streak!"
            daily["last_winner"], daily["count"] = winner_name, 1
        
        save_json(STREAKS_PATH, streaks)
        icon = "👑" if daily['count'] >= 5 else "🔥"
        streak_display = f" {icon} `{daily['count']}`"

    # 2. BUILD TOP 3
    for i, (name, xp) in enumerate(ranking[:3]):
        pct = int((xp / max_xp) * 100) if max_xp > 0 else 0
        s = streak_display if i == 0 and "Daily" in title else ""
        fields.append({
            "name": f"{medals[i]} **{name}**{s}",
            "value": f"`+{xp:,} XP`\n{make_bar(xp, max_xp)} `{pct}%`"
        })

    # 3. OTHER GAINS (Cleaned - No numbering)
    others = [f"**{n}** (+{v:,} XP)" for n, v in ranking[3:5]]
    if others:
        fields.append({"name": "--- Other Gains ---", "value": "\n".join(others)})

    # 4. FOOTER (Cleaned legend)
    if "Daily" in title:
        footer_text = f"Team Total: {team_total:,} XP ({team_change} vs last daily)\n"
    else:
        footer_text = f"Team Total: {team_total:,} XP\n"
        
    footer_text += "⭐ = New PB | 🔥 = 1-4 Streak | 👑 = 5+ Streak"

    payload = {
        "embeds": [{
            "title": f"🏆 {title} 🏆",
            "description": f"🗓️ Date: **{date_label}**{description_addon}",
            "fields": fields,
            "color": 0x2ecc71,
            "footer": {"text": footer_text}
        }]
    }
    
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if webhook:
        requests.post(webhook, json=payload)

# --- MAIN ENGINE ---
def main():
    dates = get_dates()
    logs = load_json(LOG_PATH)
    state = load_json(STATE_PATH)
    
    if not CHAR_FILE.exists(): return
    with open(CHAR_FILE) as f: 
        chars = [l.strip() for l in f if l.strip()]

    # A. DAILY RESULTS
    yest = dates['yesterday']
    if state.get("last_daily") != yest:
        rank_y = get_ranking_sum(logs, [yest], chars)
        if rank_y:
            total_y = sum(v for n, v in rank_y)
            rank_db = get_ranking_sum(logs, [dates['day_before']], chars)
            total_db = sum(v for n, v in rank_db)
            change = f"{((total_y - total_db)/total_db)*100:+.1f}%" if total_db > 0 else "0%"
            
            send_discord_post("Daily Champion", yest, rank_y, total_y, change)
            state["last_daily"] = yest
            save_json(STATE_PATH, state)

    # B. WEEKLY RESULTS (Mondays)
    if dates['is_monday'] and state.get("last_weekly") != yest:
        last_7 = [(dates['obj'] - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, 8)]
        rank_w = get_ranking_sum(logs, last_7, chars)
        if rank_w:
            send_discord_post("Weekly Champion", f"Week of {yest}", rank_w, sum(v for n, v in rank_w))
            state["last_weekly"] = yest
            save_json(STATE_PATH, state)

    # C. MONTHLY RESULTS (1st of the Month)
    if dates['is_first'] and state.get("last_monthly") != yest:
        first_of_last = (dates['obj'].replace(day=1) - timedelta(days=1)).replace(day=1)
        month_str = first_of_last.strftime("%Y-%m")
        # Find all dates in logs that match last month
        all_dates = []
        if chars:
            all_dates = [d for d in logs.get(chars[0], {}).keys() if d.startswith(month_str)]
        
        rank_m = get_ranking_sum(logs, all_dates, chars)
        if rank_m:
            send_discord_post("Monthly Champion", first_of_last.strftime("%B %Y"), rank_m, sum(v for n, v in rank_m))
            state["last_monthly"] = yest
            save_json(STATE_PATH, state)

if __name__ == "__main__":
    main()
