import os
import json
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

# --- SETTINGS ---
BASE_DIR = Path(__file__).resolve().parent
LOG_PATH = BASE_DIR / "xp_log.json"
STATE_PATH = BASE_DIR / "post_state.json"
STREAKS_PATH = BASE_DIR / "streaks.json"
PB_PATH = BASE_DIR / "personal_bests.json"
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
    if path.exists():
        try:
            with open(path, "r") as f: return json.load(f)
        except: pass
    return fallback if fallback is not None else {}

def save_json(path, data):
    with open(path, "w") as f: json.dump(data, f, indent=2)

def parse_xp(val):
    """Converts '+28,888,627' into 28888627."""
    try:
        return int(str(val).replace(",", "").replace("+", "").strip())
    except: return 0

def make_bar(val, max_val):
    if max_val <= 0: return "⬛" * 10
    pct = (val / max_val)
    filled = round(pct * 10)
    return "🟩" * filled + "⬛" * (10 - filled)

# --- EMBED BUILDER ---
def send_dashboard(title, date_label, ranking, team_total, team_change):
    if not ranking or ranking[0][1] <= 0: return
    
    max_xp = ranking[0][1]
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    fields = []
    description_addon = ""

    # 1. PROCESS STREAKS (Daily Only)
    streak_display = ""
    if "Daily" in title:
        streaks = load_json(STREAKS_PATH, {"last_winner": "", "count": 0})
        winner_name = ranking[0][0]
        
        if streaks.get("last_winner") == winner_name:
            streaks["count"] += 1
        else:
            if streaks.get("count", 0) >= 2:
                description_addon = f"\n⚔️ **{winner_name}** has ended **{streaks['last_winner']}'s** `{streaks['count']}` day streak!"
            streaks["last_winner"], streaks["count"] = winner_name, 1
        
        save_json(STREAKS_PATH, streaks)
        icon = "👑" if streaks['count'] >= 5 else "🔥"
        # Black block background for the streak number
        streak_display = f" {icon} `{streaks['count']}`"

    # 2. TOP 3 (With black background XP values)
    for i, (name, xp) in enumerate(ranking[:3]):
        pct = int((xp / max_xp) * 100) if max_xp > 0 else 0
        s = streak_display if i == 0 and "Daily" in title else ""
        
        fields.append({
            "name": f"{medals[i]} **{name}**{s}",
            # Black background block for the gain
            "value": f"`+{xp:,} XP`\n{make_bar(xp, max_xp)} `{pct}%`",
            "inline": False
        })

    # 3. OTHER GAINS
    others = [f"**{idx+1}. {n}** (`+{v:,} XP`)" for idx, (n, v) in enumerate(ranking[3:5]) if v > 0]
    if others:
        fields.append({"name": "--- Other Gains ---", "value": "\n".join(others)})

    # 4. FOOTER (With black block legend)
    footer_text = f"Team Total: {team_total:,} XP ({team_change} vs last daily)\n"
    footer_text += "⭐ = New PB | `🔥 = 1-4 Streak` | `👑 = 5+ Streak`"

    payload = {
        "embeds": [{
            "title": f"🏆 {title} 🏆",
            "description": f"🗓️ Date: **{date_label}**{description_addon}",
            "fields": fields,
            "color": 0x2ecc71,
            "footer": {"text": footer_text}
        }]
    }
    requests.post(os.environ.get("DISCORD_WEBHOOK_URL"), json=payload)

# --- MAIN ---
def main():
    dates = get_dates()
    yest = dates["yesterday"]
    db = dates["day_before"]
    logs = load_json(LOG_PATH)
    state = load_json(STATE_PATH)
    
    # Extract yesterday's ranking
    rank_y = []
    total_y = 0
    total_db = 0
    
    for name, history in logs.items():
        val_y = parse_xp(history.get(yest, 0))
        val_db = parse_xp(history.get(db, 0))
        
        if val_y > 0: rank_y.append((name, val_y))
        total_y += val_y
        total_db += val_db

    if not rank_y:
        print(f"😴 No gains found for {yest} in xp_log.json.")
        return

    rank_y.sort(key=lambda x: x[1], reverse=True)

    # 1. DAILY POST
    if state.get("last_daily") != yest:
        change = f"{((total_y - total_db)/total_db)*100:+.1f}%" if total_db > 0 else "0%"
        send_dashboard("Daily Champion", yest, rank_y, total_y, change)
        state["last_daily"] = yest
        save_json(STATE_PATH, state)
        print("🚀 Daily post sent!")

    # 2. WEEKLY POST (Monday)
    if dates["is_monday"] and state.get("last_weekly") != yest:
        last_7 = [(dates["obj"] - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, 8)]
        # Re-using rank logic to sum 7 days
        w_rank = []
        for name, history in logs.items():
            w_sum = sum(parse_xp(history.get(d, 0)) for d in last_7)
            if w_sum > 0: w_rank.append((name, w_sum))
        w_rank.sort(key=lambda x: x[1], reverse=True)
        send_dashboard("Weekly Champion", f"Week of {yest}", w_rank, sum(v for n,v in w_rank), "")
        state["last_weekly"] = yest
        save_json(STATE_PATH, state)

if __name__ == "__main__":
    main()
