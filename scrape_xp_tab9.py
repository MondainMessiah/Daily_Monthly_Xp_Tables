import os
import json
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

# --- CONFIG ---
BASE_DIR = Path(__file__).resolve().parent
CHAR_FILE = BASE_DIR / "characters.txt"
LOG_PATH = BASE_DIR / "xp_log.json"
TOTALS_PATH = BASE_DIR / "xp_totals.json"
STATE_PATH = BASE_DIR / "post_state.json"
STREAKS_PATH = BASE_DIR / "streaks.json"
TIMEZONE = "Europe/London"

def get_dates():
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
    # At 09:15 AM on the 22nd, we are reporting for the 21st.
    return {
        "today": now.strftime("%Y-%m-%d"),
        "yesterday": (now - timedelta(days=1)).strftime("%Y-%m-%d"),
        "day_before": (now - timedelta(days=2)).strftime("%Y-%m-%d"),
        "is_monday": now.weekday() == 0,
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

# --- DISCORD POSTER ---
def send_discord_post(title, date_label, ranking, team_total, team_change):
    print(f"📡 Sending Discord Post for {date_label}...")
    max_xp = ranking[0][1]
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    fields = []
    description_addon = ""

    if "Daily" in title:
        streaks = load_json(STREAKS_PATH, {"daily": {"last_winner": "", "count": 0}})
        winner = ranking[0][0]
        daily = streaks.get("daily", {"last_winner": "", "count": 0})
        if daily["last_winner"] == winner: daily["count"] += 1
        else:
            if daily["count"] >= 2: description_addon = f"\n⚔️ **{winner}** ended **{daily['last_winner']}'s** `{daily['count']}` day streak!"
            daily["last_winner"], daily["count"] = winner, 1
        streaks["daily"] = daily
        save_json(STREAKS_PATH, streaks)
        icon = "👑" if daily['count'] >= 5 else "🔥"
        streak_str = f" {icon} `{daily['count']}`"
    else: streak_str = ""

    for i, (name, xp) in enumerate(ranking[:3]):
        pct = int((xp / max_xp) * 100)
        s = streak_str if i == 0 and "Daily" in title else ""
        fields.append({"name": f"{medals[i]} **{name}**{s}", "value": f"`+{xp:,} XP`\n{make_bar(xp, max_xp)} `{pct}%`", "inline": False})

    others = [f"**{n}** (+{v:,} XP)" for n, v in ranking[3:5] if v > 0]
    if others: fields.append({"name": "--- Other Gains ---", "value": "\n".join(others)})

    footer = f"Team Total: {team_total:,} XP ({team_change} vs last daily)\n⭐ = New PB | 🔥 = 1-4 Streak | 👑 = 5+ Streak"
    payload = {"embeds": [{"title": f"🏆 {title} 🏆", "description": f"🗓️ Date: **{date_label}**{description_addon}", "fields": fields, "color": 0x2ecc71, "footer": {"text": footer}}]}
    requests.post(os.environ.get("DISCORD_WEBHOOK_URL"), json=payload)

# --- MAIN ENGINE ---
def main():
    dates = get_dates()
    yest = dates['yesterday']
    print(f"🚀 Starting Bot | Today: {dates['today']} | Reporting for: {yest}")

    logs = load_json(LOG_PATH)
    totals = load_json(TOTALS_PATH)
    state = load_json(STATE_PATH)
    
    if not CHAR_FILE.exists():
        print("❌ Error: characters.txt missing!")
        return
    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]

    # 1. FETCH & RECORD (Save as Yesterday's Work)
    print(f"📡 Fetching current XP for {len(chars)} players...")
    rank_y = []
    total_y = 0

    for name in chars:
        current_total = 0
        url = f"https://api.tibiadata.com/v4/character/{name.replace(' ', '%20')}"
        try:
            r = requests.get(url, timeout=10)
            current_total = r.json().get("character", {}).get("character", {}).get("experience", 0)
        except: continue

        if current_total > 0:
            prev_total = totals.get(name, 0)
            if prev_total > 0:
                gain = current_total - prev_total
                if gain >= 0:
                    if name not in logs: logs[name] = {}
                    logs[name][yest] = f"+{gain:,}"
                    rank_y.append((name, gain))
                    total_y += gain
                    print(f"✅ {name}: +{gain:,}")
            totals[name] = current_total

    save_json(TOTALS_PATH, totals)
    save_json(LOG_PATH, logs)

    # 2. POST DAILY
    if state.get("last_daily") != yest and rank_y:
        rank_y.sort(key=lambda x: x[1], reverse=True)
        # Calc Team Change %
        total_db = 0
        for name in chars: total_db += parse_xp(logs.get(name, {}).get(dates['day_before'], 0))
        change = f"{((total_y - total_db)/total_db)*100:+.1f}%" if total_db > 0 else "0%"
        
        send_discord_post("Daily Champion", yest, rank_y, total_y, change)
        state["last_daily"] = yest
        save_json(STATE_PATH, state)
        print("🎉 Daily Post Sent!")
    else:
        print("⏭️ Daily post skipped (already sent or no data).")

    # 3. WEEKLY (Mondays)
    if dates['is_monday'] and state.get("last_weekly") != yest:
        last_7 = [(dates['obj'] - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, 8)]
        rank_w = []
        for name in chars:
            w_sum = sum(parse_xp(logs.get(name, {}).get(d, 0)) for d in last_7)
            if w_sum > 0: rank_w.append((name, w_sum))
        if rank_w:
            rank_w.sort(key=lambda x: x[1], reverse=True)
            send_discord_post("Weekly Champion", f"Week ending {yest}", rank_w, sum(v for n,v in rank_w), "N/A")
            state["last_weekly"] = yest
            save_json(STATE_PATH, state)

if __name__ == "__main__":
    main()
