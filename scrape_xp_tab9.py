import os
import json
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

# --- CONFIGURATION (Safe Vault) ---
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

# --- VISUAL DASHBOARD TOOLS ---
def make_bar(val, max_val):
    """Produces the visual progress bars. (image_0: Filled=🟩, Empty=⬛)"""
    if max_val <= 0: return "⬛" * 10
    pct_raw = (val / max_val) * 100
    filled_count = round(pct_raw / 10)
    return "🟩" * filled_count + "⬛" * (10 - filled_count)

# --- API & DATA ENGINE ---
def fetch_current_total_xp(name):
    # TibiaData API (reliability engine)
    url = f"https://api.tibiadata.com/v4/character/{name.replace(' ', '%20')}"
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            return r.json().get("character", {}).get("character", {}).get("experience", 0)
    except: pass
    return 0

def get_ranking_sum(logs, date_list):
    """Calculates ranking based on summing gains from a list of dates."""
    rank = {}
    for name, history in logs.items():
        total_range_gain = sum(int(history.get(d, "0").replace(",", "").replace("+", "")) for d in date_list)
        rank[name] = total_range_gain
    return sorted(rank.items(), key=lambda x: x[1], reverse=True)

# --- DISCORD EMBED BUILDER ---
def send_discord_xp_embed(title, date_label, ranking, team_total, team_change):
    if not ranking or ranking[0][1] <= 0: return
    
    max_xp = ranking[0][1]
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    fields = []

    # TOP 3 RANKING with Visual Bars and Streak Logic
    for i, (name, xp) in enumerate(ranking[:3]):
        # Percentage formatting
        pct = int((xp / max_xp) * 100) if max_xp > 0 else 0
        
        # --- STREAK LOGIC (Daily Only) ---
        streak_str = ""
        if "Daily" in title and i == 0:
            streaks = load_json(STREAKS_PATH)
            if streaks.get("last_winner") == name: 
                streaks["count"] += 1
            else: 
                streaks["last_winner"], streaks["count"] = name, 1
            save_json(STREAKS_PATH, streaks)
            
            # Formatting streak from image_1.png (Icon + Count in blocks)
            icon = "`👑`" if streaks['count'] >= 5 else "`🔥`"
            streak_str = f" {icon} `{streaks['count']}`"

        # --- RANK ROW FORMATTING (The backtick ` ` logic) ---
        fields.append({
            "name": f"{medals[i]} **{name}**{streak_str}",
            # image_1.png: Gain in block, Bar+Percentage in standard footer
            "value": f"`+{xp:,} XP`\n{make_bar(xp, max_xp)} `{pct}%`",
            "inline": False
        })

    # --- OTHER GAINS LIST (4-5) ---
    others = [f"**{idx+1}. {n}** (`+{v:,} XP`)" for idx, (n, v) in enumerate(ranking[3:5]) if v > 0]
    if others:
        fields.append({"name": "--- Other Gains ---", "value": "\n".join(others)})

    # --- FOOTER (image_1.png legend logic) ---
    team_footer = f"Team Total: {team_total:,} XP (`{team_change} vs last daily`)"
    team_footer += "\n⭐ = New PB | `🔥 = 1-4 Streak` | `👑 = 5+ Streak`"

    payload = {
        "embeds": [{
            "title": f"🏆 {title} 🏆",
            "description": f"🗓️ Date: **{date_label}**",
            "fields": fields,
            "color": 0x2ecc71,
            "footer": {"text": team_footer}
        }]
    }
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if webhook_url:
        requests.post(webhook_url, json=payload)

# --- MAIN ENGINE ---
def main():
    dates = get_dates()
    logs = load_json(LOG_PATH)
    totals = load_json(TOTALS_PATH)
    state = load_json(STATE_PATH)
    
    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]

    # 1. API UPDATE (Daily baseline update)
    print(f"📡 Updating baseline totals for {dates['today']}...")
    for name in chars:
        current_total = fetch_current_total_xp(name)
        if current_total == 0: continue
        
        last_total = totals.get(name, 0)
        if last_total > 0:
            gain = current_total - last_total
            if gain >= 0:
                if name not in logs: logs[name] = {}
                logs[name][dates["today"]] = f"+{gain:,}"
        
        totals[name] = current_total
    
    save_json(TOTALS_PATH, totals)
    save_json(LOG_PATH, logs) # SAFE: old history is preserved

    # 2. DAILY POST (Yesterday's results)
    yesterday = dates["yesterday"]
    if state.get("last_posted_daily") != yesterday:
        daily_ranking = get_ranking_sum(logs, [yesterday])
        if daily_ranking:
            # Calculate Team Total and % Change
            team_y = sum(v for n, v in daily_ranking)
            rank_db = get_ranking_sum(logs, [dates["day_before"]])
            team_db = sum(v for n, v in rank_db)
            
            change = f"{((team_y - team_db)/team_db)*100:+.1f}%" if team_db > 0 else "0%"
            
            send_discord_xp_embed("Daily Champion", yesterday, daily_ranking, team_y, change)
            state["last_posted_daily"] = yesterday
            save_json(STATE_PATH, state)
            print(f"🚀 Daily Post sent for {yesterday}!")

    # 3. WEEKLY POST (Fires every Monday)
    if dates["is_monday"] and state.get("last_posted_weekly") != yesterday:
        last_7_dates = [(dates["obj"] - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, 8)]
        weekly_ranking = get_ranking_sum(logs, last_7_dates)
        if weekly_ranking:
            send_discord_xp_embed("Weekly Champion", f"Week of {yesterday}", weekly_ranking, sum(v for n, v in weekly_ranking), "")
            state["last_posted_weekly"] = yesterday
            save_json(STATE_PATH, state)
            print("🚀 Weekly Summary sent!")

    # 4. MONTHLY POST (Fires on the 1st of the month)
    if dates["is_first"] and state.get("last_posted_monthly") != yesterday:
        # Get all dates from last month
        first_of_last_month = (dates["obj"].replace(day=1) - timedelta(days=1)).replace(day=1)
        # Assuming you have at least one character in logs to get a date pattern
        date_pattern = first_of_last_month.strftime("%Y-%m")
        month_dates = [d for d in next(iter(logs.values())).keys() if d.startswith(date_pattern)]
        
        if month_dates:
            monthly_ranking = get_ranking_sum(logs, month_dates)
            send_discord_xp_embed("Monthly Champion", first_last_month.strftime("%B %Y"), monthly_ranking, sum(v for n, v in monthly_ranking), "")
            state["last_posted_monthly"] = yesterday
            save_json(STATE_PATH, state)
            print("🚀 Monthly Summary sent!")

if __name__ == "__main__":
    main()
