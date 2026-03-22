import os, json, requests
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
WORLD = "Celesta"
TIMEZONE = "Europe/London"

def get_dates():
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
    return {
        "today": now.strftime("%Y-%m-%d"),
        "yesterday": (now - timedelta(days=1)).strftime("%Y-%m-%d"),
        "is_monday": now.weekday() == 0,
        "is_first_of_month": now.day == 1,
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
def send_discord_post(title, date_label, ranking, team_total, post_type="daily"):
    if not ranking: return
    
    max_gain = ranking[0]['gain']
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    fields = []
    description = f"🗓️ Period: **{date_label}**"
    
    # --- STREAK LOGIC (Only for Daily) ---
    if post_type == "daily":
        streaks = load_json(STREAKS_PATH, {"daily": {"last_winner": "", "count": 0}})
        winner = ranking[0]['name']
        s_data = streaks["daily"]
        
        if s_data["last_winner"] == winner:
            s_data["count"] += 1
        else:
            # Announcement if a streak is broken
            if s_data["count"] >= 2:
                description += f"\n\n⚔️ **{winner}** has ended **{s_data['last_winner']}'s** `{s_data['count']}` day winning streak!"
            s_data["last_winner"] = winner
            s_data["count"] = 1
        
        streaks["daily"] = s_data
        save_json(STREAKS_PATH, streaks)
        
        streak_icon = "👑" if s_data['count'] >= 5 else "🔥"
        streak_text = f" {streak_icon} `{s_data['count']}`"
    else:
        streak_text = ""

    # Build Embed Fields
    for i, item in enumerate(ranking[:3]):
        name, gain, rank = item['name'], item['gain'], item.get('rank', '???')
        pct = int((gain / max_gain) * 100) if max_gain > 0 else 0
        s = streak_text if i == 0 and post_type == "daily" else ""
        
        fields.append({
            "name": f"{medals[i]} **{name}**{s}", 
            "value": f"🌍 World Rank: #{rank}\n`+{gain:,} XP` earned\n{make_bar(gain, max_gain)} `{pct}%`"
        })

    others = [f"**{it['name']}** (+{it['gain']:,} XP)" for it in ranking[3:] if it['gain'] > 0]
    if others: fields.append({"name": "--- Other Gains ---", "value": "\n".join(others)})

    payload = {
        "embeds": [{
            "title": f"🏆 {title} 🏆", 
            "description": description, 
            "fields": fields, 
            "color": 0x3498db if post_type != "daily" else 0x2ecc71, 
            "footer": {"text": f"Team Total: {team_total:,} XP | World: {WORLD}"}
        }]
    }
    requests.post(os.environ.get("DISCORD_WEBHOOK_URL"), json=payload)

# --- MAIN ---
def main():
    dates = get_dates()
    yest = dates['yesterday']
    logs = load_json(LOG_PATH)
    totals = load_json(TOTALS_PATH)
    state = load_json(STATE_PATH)
    
    if not CHAR_FILE.exists(): return
    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]

    # 1. API UPDATE
    api_ranks = []
    current_stats = {}
    for page in range(1, 21):
        url = f"https://api.tibiadata.com/v4/highscores/{WORLD}/experience/all/{page}"
        try:
            r = requests.get(url, timeout=15); data = r.json()
            items = data.get("highscores", {}).get("highscore_list", [])
            for entry in items:
                name = entry.get("name")
                if name in chars:
                    curr_xp, curr_rank = entry.get("value", 0), int(entry.get("rank", 0))
                    last_entry = totals.get(name, {"xp": 0, "rank": curr_rank})
                    if isinstance(last_entry, int): last_entry = {"xp": last_entry, "rank": curr_rank}
                    
                    gain = curr_xp - last_entry.get("xp", 0) if last_entry.get("xp", 0) > 0 else 0
                    if gain >= 0:
                        api_ranks.append({"name": name, "gain": gain, "rank": curr_rank})
                        if gain > 0:
                            if name not in logs: logs[name] = {}
                            logs[name][yest] = f"+{gain:,}"
                    
                    current_stats[name] = {"xp": curr_xp, "rank": curr_rank}
        except: break

    totals.update(current_stats); save_json(TOTALS_PATH, totals)
    save_json(LOG_PATH, logs)

    # 2. DAILY POST
    if state.get("last_daily") != yest:
        daily_list = api_ranks if any(x['gain'] > 0 for x in api_ranks) else []
        if not daily_list: # Fallback to log
            for name in chars:
                val = parse_xp(logs.get(name, {}).get(yest, 0))
                if val > 0: daily_list.append({"name": name, "gain": val, "rank": current_stats.get(name, {}).get("rank", "???")})
        
        if daily_list:
            daily_list.sort(key=lambda x: x['gain'], reverse=True)
            send_discord_post("Daily Champion", yest, daily_list, sum(x['gain'] for x in daily_list), "daily")
            state["last_daily"] = yest

    # 3. WEEKLY (Mondays)
    if dates['is_monday'] and state.get("last_weekly") != yest:
        last_7 = [(dates['obj'] - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, 8)]
        weekly_list = []
        for name in chars:
            w_sum = sum(parse_xp(logs.get(name, {}).get(d, 0)) for d in last_7)
            if w_sum > 0: weekly_list.append({"name": name, "gain": w_sum, "rank": current_stats.get(name, {}).get("rank", "???")})
        
        if weekly_list:
            weekly_list.sort(key=lambda x: x['gain'], reverse=True)
            send_discord_post("Weekly Champion", f"Week ending {yest}", weekly_list, sum(x['gain'] for x in weekly_list), "weekly")
            state["last_weekly"] = yest

    # 4. MONTHLY (1st of the month)
    if dates['is_first_of_month'] and state.get("last_monthly") != yest:
        # Calculate last month's name and year
        first_of_this_month = dates['obj'].replace(day=1)
        last_day_of_prev_month = first_of_this_month - timedelta(days=1)
        month_label = last_day_of_prev_month.strftime("%B %Y")
        
        monthly_list = []
        for name in chars:
            m_sum = sum(parse_xp(v) for d, v in logs.get(name, {}).items() if d.startswith(last_day_of_prev_month.strftime("%Y-%m")))
            if m_sum > 0: monthly_list.append({"name": name, "gain": m_sum, "rank": current_stats.get(name, {}).get("rank", "???")})
        
        if monthly_list:
            monthly_list.sort(key=lambda x: x['gain'], reverse=True)
            send_discord_post("Monthly Champion", month_label, monthly_list, sum(x['gain'] for x in monthly_list), "monthly")
            state["last_monthly"] = yest

    save_json(STATE_PATH, state)

if __name__ == "__main__":
    main()