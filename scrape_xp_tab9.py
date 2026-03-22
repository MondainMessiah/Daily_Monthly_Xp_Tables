import os, json, requests, sys
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

# --- COLORS ---
CLR_GOLD = 0xFFD700
CLR_SILVER = 0xC0C0C0
CLR_BRONZE = 0xCD7F32
CLR_RED = 0xFF0000
CLR_MAIN = 0x2ecc71 

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
        with open(path, "r") as f:
            data = json.load(f)
            return data if data else (fallback if fallback is not None else {})
    except: return fallback if fallback is not None else {}

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def parse_xp(val):
    try: return int(str(val).replace(",", "").replace("+", "").strip())
    except: return 0

def make_bar(val, max_val):
    if max_val <= 0: return "⬛" * 10
    filled = round((val / max_val) * 10)
    return "🟩" * filled + "⬛" * (10 - filled)

# --- DISCORD POSTER ---
def send_discord_post(title, date_label, ranking, team_total, post_type="daily"):
    print(f"📡 Posting {title} to Discord...")
    if not ranking: return
    
    embeds_list = []
    max_gain = ranking[0]['gain']
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    medal_colors = {0: CL_GOLD, 1: CL_SILVER, 2: CL_BRONZE}

    # 1. HEADER BOX
    header_embed = {
        "title": f"🏆 {title} 🏆",
        "description": f"🗓️ Period: **{date_label}**",
        "color": CLR_MAIN
    }
    embeds_list.append(header_embed)

    # 2. STREAK LOGIC
    streak_footer_part = ""
    if post_type == "daily":
        streaks = load_json(STREAKS_PATH, {"daily": {"last_winner": "", "count": 0}})
        winner = ranking[0]['name']
        s_data = streaks.get("daily", {"last_winner": "", "count": 0})
        
        # Check if streak is broken
        if s_data["last_winner"] != "" and s_data["last_winner"] != winner:
            if s_data["count"] >= 2:
                # NEW RED EMBED FOR STREAK BREAKER
                embeds_list.append({
                    "title": "⚔️ STREAK BROKEN ⚔️",
                    "description": f"**{winner}** has just ended **{s_data['last_winner']}'s** `{s_data['count']}` day winning streak!",
                    "color": CLR_RED
                })
            s_data["last_winner"] = winner
            s_data["count"] = 1
        else:
            s_data["last_winner"] = winner
            s_data["count"] += 1
        
        save_json(STREAKS_PATH, streaks)
        
        # Streak Icon Logic
        s_icon = "👑" if s_data['count'] >= 5 else "🔥"
        streak_footer_part = f" | Streak: {s_icon} {s_data['count']}"

    # 3. PLAYER CARDS
    for i, item in enumerate(ranking[:3]):
        name, gain, rank = item['name'], item['gain'], item.get('rank', '???')
        move = item.get('move', '⏺️')
        pct = int((gain / max_gain) * 100) if max_gain > 0 else 0
        move_str = f" ({move})" if move != "⏺️" else ""

        embeds_list.append({
            "author": {"name": f"{medals[i]} {name}"},
            "description": f"🌍 **World Rank: #{rank}**{move_str}\n`+{gain:,} XP` earned\n{make_bar(gain, max_gain)} `{pct}%`",
            "color": medal_colors.get(i, CLR_MAIN)
        })

    # 4. OTHER GAINS & FOOTER
    others = [f"**{it['name']}** (+{it['gain']:,} XP)" for it in ranking[3:] if it['gain'] > 0]
    
    # Updated Footer with Disclaimer and Streak
    footer_text = f"Total: {team_total:,} XP | World: {WORLD}{streak_footer_part}\n⚠️ Only players in Top 1000 can be tracked"
    
    footer_embed = {
        "color": CLR_MAIN,
        "footer": {"text": footer_text}
    }
    
    if others:
        footer_embed["title"] = "--- Other Gains ---"
        footer_embed["description"] = "\n".join(others)
    else:
        footer_embed["description"] = "No other significant gains today."

    embeds_list.append(footer_embed)

    payload = {"embeds": embeds_list}
    r = requests.post(os.environ.get("DISCORD_WEBHOOK_URL"), json=payload)
    print(f"✅ Discord Status: {r.status_code}")

# --- MAIN ENGINE ---
def main():
    print("🚀 Starting Bot Engine...")
    dates = get_dates(); yest = dates['yesterday']
    logs = load_json(LOG_PATH); totals = load_json(TOTALS_PATH); state = load_json(STATE_PATH)
    
    if not CHAR_FILE.exists(): return
    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]
    
    api_ranks = []; current_stats = {}; found_count = 0
    for page in range(1, 21):
        if found_count == len(chars): break
        try:
            r = requests.get(f"https://api.tibiadata.com/v4/highscores/{WORLD}/experience/all/{page}", timeout=15)
            data = r.json()
            items = data.get("highscores", {}).get("highscore_list", [])
            for entry in items:
                name = entry.get("name")
                if name and any(name.lower() == c.lower() for c in chars):
                    curr_xp, curr_rank = entry.get("value", 0), int(entry.get("rank", 0))
                    last_entry = totals.get(name, {"xp": 0, "rank": curr_rank})
                    if isinstance(last_entry, (int, float)): last_entry = {"xp": last_entry, "rank": curr_rank}
                    
                    last_xp, last_rank = last_entry.get("xp", 0), last_entry.get("rank", curr_rank)
                    
                    if curr_rank < last_rank: move = f"🔼 {last_rank - curr_rank}"
                    elif curr_rank > last_rank: move = f"🔽 {curr_rank - last_rank}"
                    else: move = "⏺️"

                    gain = curr_xp - last_xp if last_xp > 0 else 0
                    api_ranks.append({"name": name, "gain": gain, "rank": curr_rank, "move": move})
                    if gain > 0:
                        if name not in logs: logs[name] = {}
                        logs[name][yest] = f"+{gain:,}"
                    current_stats[name] = {"xp": curr_xp, "rank": curr_rank, "move": move}
                    found_count += 1
        except: break

    totals.update(current_stats); save_json(TOTALS_PATH, totals); save_json(LOG_PATH, logs)

    # Check for Daily Post
    if state.get("last_daily") != yest:
        daily_list = [x for x in api_ranks if x['gain'] > 0]
        if not daily_list:
            for name in chars:
                val = parse_xp(logs.get(name, {}).get(yest, 0))
                if val > 0:
                    st = current_stats.get(name, {"rank": "???", "move": "⏺️"})
                    daily_list.append({"name": name, "gain": val, "rank": st['rank'], "move": st['move']})
        
        if daily_list:
            daily_list.sort(key=lambda x: x['gain'], reverse=True)
            send_discord_post("Daily Champion", yest, daily_list, sum(x['gain'] for x in daily_list), "daily")
            state["last_daily"] = yest

    # Weekly Logic (Monday)
    if dates['is_monday'] and state.get("last_weekly") != yest:
        last_7 = [(dates['obj'] - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, 8)]
        weekly_list = []
        for name in chars:
            w_sum = sum(parse_xp(logs.get(name, {}).get(d, 0)) for d in last_7)
            if w_sum > 0:
                weekly_list.append({"name": name, "gain": w_sum, "rank": current_stats.get(name, {}).get("rank", "???")})
        if weekly_list:
            weekly_list.sort(key=lambda x: x['gain'], reverse=True)
            send_discord_post("Weekly Champion", f"Week ending {yest}", weekly_list, sum(x['gain'] for x in weekly_list), "weekly")
            state["last_weekly"] = yest

    # Monthly Logic (1st)
    if dates['is_first_of_month'] and state.get("last_monthly") != yest:
        m_label = (dates['obj'] - timedelta(days=1)).strftime("%Y-%m")
        monthly_list = []
        for name in chars:
            m_sum = sum(parse_xp(v) for d, v in logs.get(name, {}).items() if d.startswith(m_label))
            if m_sum > 0:
                monthly_list.append({"name": name, "gain": m_sum, "rank": current_stats.get(name, {}).get("rank", "???")})
        if monthly_list:
            monthly_list.sort(key=lambda x: x['gain'], reverse=True)
            send_discord_post("Monthly Champion", (dates['obj'] - timedelta(days=1)).strftime("%B %Y"), monthly_list, sum(x['gain'] for x in monthly_list), "monthly")
            state["last_monthly"] = yest

    save_json(STATE_PATH, state)
    print("🏁 Job Complete.")

if __name__ == "__main__":
    main()
