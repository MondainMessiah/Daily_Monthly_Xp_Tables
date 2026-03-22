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
def send_discord_post(title, date_label, ranking, team_total):
    if not ranking: return
    print(f"📡 Sending Discord Post for {date_label}...")
    
    max_gain = ranking[0]['gain']
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    fields = []
    
    # Streak Logic
    streaks = load_json(STREAKS_PATH, {"daily": {"last_winner": "", "count": 0}})
    winner = ranking[0]['name']
    daily = streaks.get("daily", {"last_winner": "", "count": 0})
    
    if daily["last_winner"] == winner: daily["count"] += 1
    else: daily["last_winner"], daily["count"] = winner, 1
    
    streaks["daily"] = daily
    save_json(STREAKS_PATH, streaks)
    icon = "👑" if daily['count'] >= 5 else "🔥"
    
    for i, item in enumerate(ranking[:3]):
        name, gain, rank, move = item['name'], item['gain'], item['rank'], item['move']
        pct = int((gain / max_gain) * 100) if max_gain > 0 else 0
        s = f" {icon} `{daily['count']}`" if i == 0 else ""
        
        # Format the movement string
        move_str = f" ({move})" if move != "⏺️" else ""
        
        fields.append({
            "name": f"{medals[i]} **{name}**{s}", 
            "value": f"🌍 **World Rank: #{rank}**{move_str}\n`+{gain:,} XP` earned\n{make_bar(gain, max_gain)} `{pct}%`"
        })

    others = [f"**{it['name']}** (Rank #{it['rank']} | +{it['gain']:,} XP)" for it in ranking[3:] if it['gain'] > 0]
    if others: fields.append({"name": "--- Other Gains ---", "value": "\n".join(others)})

    payload = {
        "embeds": [{
            "title": f"🏆 {title} 🏆", 
            "description": f"🗓️ Date: **{date_label}**", 
            "fields": fields, 
            "color": 0x2ecc71, 
            "footer": {"text": f"Team Total: {team_total:,} XP | World: {WORLD}"}
        }]
    }
    requests.post(os.environ.get("DISCORD_WEBHOOK_URL"), json=payload)

# --- MAIN ---
def main():
    dates = get_dates()
    yest = dates['yesterday']
    print(f"🚀 Bot Running | Tracking {WORLD} Rank Movement")

    logs = load_json(LOG_PATH)
    totals = load_json(TOTALS_PATH)
    state = load_json(STATE_PATH)
    
    if not CHAR_FILE.exists(): return
    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]

    new_ranks = []
    found_count = 0
    temp_data = {} # To map current stats
    
    # 1. SCAN API HIGHSCORES
    for page in range(1, 21):
        if found_count == len(chars): break
        url = f"https://api.tibiadata.com/v4/highscores/{WORLD}/experience/all/{page}"
        try:
            r = requests.get(url, timeout=15)
            data = r.json()
            items = data.get("highscores", {}).get("highscore_list", [])
            for entry in items:
                name = entry.get("name")
                if name in chars:
                    curr_xp = entry.get("value") or entry.get("experience") or 0
                    curr_rank = int(entry.get("rank", 0))
                    
                    # Get last data (handling old format where it was just an int)
                    last_entry = totals.get(name, {"xp": 0, "rank": 0})
                    if isinstance(last_entry, int): last_entry = {"xp": last_entry, "rank": curr_rank}
                    
                    last_xp = last_entry.get("xp", 0)
                    last_rank = last_entry.get("rank", curr_rank)

                    # Calculate movement
                    if curr_rank < last_rank: move = f"🔼 {last_rank - curr_rank}"
                    elif curr_rank > last_rank: move = f"🔽 {curr_rank - last_rank}"
                    else: move = "⏺️"

                    if last_xp > 0:
                        gain = curr_xp - last_xp
                        if gain >= 0:
                            if name not in logs: logs[name] = {}
                            logs[name][yest] = f"+{gain:,}"
                            new_ranks.append({"name": name, "gain": gain, "rank": curr_rank, "move": move})
                            print(f"✅ {name}: +{gain:,} XP (Rank #{curr_rank} {move})")
                    
                    temp_data[name] = {"xp": curr_xp, "rank": curr_rank}
                    found_count += 1
        except: break

    # Update totals with the new dictionary format
    totals.update(temp_data)
    save_json(TOTALS_PATH, totals)
    save_json(LOG_PATH, logs)

    # 2. POST DAILY RESULTS
    if state.get("last_daily") != yest:
        if not new_ranks:
            for name in chars:
                val = parse_xp(logs.get(name, {}).get(yest, 0))
                if val > 0:
                    d = temp_data.get(name, {"rank": "???", "move": "⏺️"})
                    new_ranks.append({"name": name, "gain": val, "rank": d['rank'], "move": d['move']})

        if new_ranks:
            new_ranks.sort(key=lambda x: x['gain'], reverse=True)
            total_xp = sum(item['gain'] for item in new_ranks)
            send_discord_post("Daily Champion", yest, new_ranks, total_xp)
            state["last_daily"] = yest
            save_json(STATE_PATH, state)
            print("🎉 Success!")

if __name__ == "__main__":
    main()
