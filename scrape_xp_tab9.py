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
# 🛠️ THE GOOGLE BRIDGE SCRAPER (V2 SHARPSHOOTER)
# ==========================================
def fetch_guildstats_gain(name, target_date):
    """
    Routes request through Google Bridge to bypass 403s.
    Uses an advanced regex to skip the Level column and grab the Experience Gain.
    """
    bridge_url = os.environ.get("GOOGLE_BRIDGE_URL")
    if not bridge_url:
        print("❌ ERROR: GOOGLE_BRIDGE_URL secret is missing!")
        return "NO_URL"

    # GuildStats prefers '+' for spaces in names
    formatted_name = name.replace(' ', '+')
    target_url = f"https://guildstats.eu/include/character/tab.php?nick={formatted_name}&tab=experience"
    final_url = f"{bridge_url}?url={urllib.parse.quote(target_url)}"
    
    try:
        # Higher timeout because the bridge performs a cookie-handshake
        r = requests.get(final_url, timeout=45)
        
        if r.status_code != 200:
            print(f"⚠️ Bridge returned {r.status_code} for {name}")
            return 0

        # REGEX V2 LOGIC:
        # 1. Finds the date (e.g., 2026-03-22).
        # 2. Skip the first </td> (the date cell).
        # 3. Skip the next <td>...</td> entirely (the Level cell).
        # 4. Capture the number in the FOLLOWING cell (the XP gain).
        pattern = rf"{target_date}.*?</td>.*?<td.*?>.*?</td>.*?<td.*?>\s*([+-]?[\d,.]+)"
        match = re.search(pattern, r.text, re.IGNORECASE | re.DOTALL)
        
        if match:
            raw_val = match.group(1)
            # Remove commas/dots and the '+' sign
            clean_val = raw_val.replace(',', '').replace('.', '').replace('+', '')
            
            # Final Safety: If it's a tiny number (like '3'), try an alternate 'greedy' search
            # for a number specifically starting with a + or - (the Gain signature)
            if len(clean_val) < 4 and "+" not in raw_val and "-" not in raw_val:
                alt_pattern = rf"{target_date}.*?([+-][\d,.]+)"
                alt_match = re.search(alt_pattern, r.text, re.IGNORECASE | re.DOTALL)
                if alt_match:
                    clean_val = alt_match.group(1).replace(',', '').replace('.', '').replace('+', '')

            return int(clean_val)
        return 0
    except Exception as e:
        print(f"⚠️ {name} Scrape Error: {e}")
        return 0

# ==========================================

def get_dates():
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
    return {
        "yesterday": (now - timedelta(days=1)).strftime("%Y-%m-%d"),
        "day_before": (now - timedelta(days=2)).strftime("%Y-%m-%d"),
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
    try: return int(str(val).replace(",", "").replace("+", "").replace(".", "").strip())
    except: return 0

def make_bar(val, max_val):
    if max_val <= 0: return "⬛" * 10
    filled = round((val / max_val) * 10)
    filled = max(0, min(10, filled))
    return "🟩" * filled + "⬛" * (10 - filled)

# --- DISCORD POSTER ---
def send_discord_post(title, date_label, ranking, team_total, team_change):
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook or not ranking: return

    max_xp = ranking[0][1]
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    fields = []
    description_addon = ""

    # 1. PROCESS STREAKS
    streaks = load_json(STREAKS_PATH, {"daily": {"last_winner": "", "count": 0}})
    winner_name = ranking[0][0]
    daily = streaks.get("daily", {"last_winner": "", "count": 0})

    if daily.get("last_winner") == winner_name:
        daily["count"] += 1
    else:
        if daily.get("last_winner") and daily.get("count", 0) >= 2:
            description_addon = f"\n⚔️ **{winner_name}** ended **{daily['last_winner']}'s** `{daily['count']}` day streak!"
        daily["last_winner"], daily["count"] = winner_name, 1
    
    save_json(STREAKS_PATH, streaks)
    icon = "👑" if daily['count'] >= 5 else "🔥"
    streak_display = f" {icon} `{daily['count']}`"

    # 2. BUILD TOP 3
    for i, (name, xp) in enumerate(ranking[:3]):
        pct = int((xp / max_xp) * 100) if max_xp > 0 else 0
        s = streak_display if i == 0 else ""
        fields.append({
            "name": f"{medals[i]} **{name}**{s}",
            "value": f"`+{xp:,} XP`\n{make_bar(xp, max_xp)} `{pct}%`",
            "inline": False
        })

    # 3. OTHER GAINS
    others = [f"**{n}** (+{v:,} XP)" for n, v in ranking[3:10] if v > 0]
    if others:
        fields.append({"name": "--- Other Gains ---", "value": "\n".join(others)})

    # 4. FOOTER
    footer_text = f"Total: {team_total:,} XP ({team_change})\n"
    footer_text += "🔥 = 1-4 Streak | 👑 = 5+ Streak"

    payload = {
        "embeds": [{
            "title": f"🏆 {title} 🏆",
            "description": f"🗓️ Date: **{date_label}**{description_addon}",
            "fields": fields,
            "color": 0x2ecc71,
            "footer": {"text": footer_text}
        }]
    }
    requests.post(webhook, json=payload)

# --- MAIN ENGINE ---
def main():
    dates = get_dates()
    logs = load_json(LOG_PATH)
    state = load_json(STATE_PATH)
    
    if not CHAR_FILE.exists(): return
    with open(CHAR_FILE) as f: chars = [l.strip() for l in f if l.strip()]

    print(f"🌐 Fetching fresh data via Google Bridge for {dates['yesterday']}...")
    
    success_count = 0
    for name in chars:
        gain = fetch_guildstats_gain(name, dates['yesterday'])
        
        if isinstance(gain, int):
            if name not in logs: logs[name] = {}
            # Update log with the real number
            logs[name][dates['yesterday']] = f"+{gain:,}"
            print(f"✅ {name}: {gain:,} XP (Scraped)")
            success_count += 1
            time.sleep(2) # Pause for the bridge
        elif gain == "NO_URL": return
        else:
            print(f"⚪ {name}: No daily gain found.")

    if success_count > 0:
        save_json(LOG_PATH, logs)
    else:
        print("⛔ Scrape failed for all characters. Aborting post.")
        return

    # RANK AND POST
    rank_y = []
    total_y, total_db = 0, 0
    for name in chars:
        h = logs.get(name, {})
        y = parse_xp(h.get(dates['yesterday'], 0))
        db = parse_xp(h.get(dates['day_before'], 0))
        if y > 0: rank_y.append((name, y))
        total_y += y; total_db += db

    if rank_y and state.get("last_daily") != dates['yesterday']:
        rank_y.sort(key=lambda x: x[1], reverse=True)
        change = f"{((total_y - total_db)/total_db)*100:+.1f}%" if total_db > 0 else "0%"
        send_discord_post("Daily Champion", dates['yesterday'], rank_y, total_y, change)
        state["last_daily"] = dates['yesterday']
        save_json(STATE_PATH, state)
        print("🚀 Scrape and Discord Post complete.")

if __name__ == "__main__":
    main()
