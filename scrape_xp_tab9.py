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
# 🛠️ THE GOOGLE BRIDGE SCRAPER (SHARPSHOOTER)
# ==========================================
def fetch_guildstats_gain(name, target_date):
    """
    Routes the request through the Google Apps Script Bridge to bypass 403s.
    Targets the internal 'experience' tab for the most direct data.
    """
    bridge_url = os.environ.get("GOOGLE_BRIDGE_URL")
    if not bridge_url:
        print("❌ ERROR: GOOGLE_BRIDGE_URL secret is missing from GitHub!")
        return "NO_URL"

    # Encoding name for the URL (GuildStats prefers + for spaces)
    formatted_name = name.replace(' ', '+')
    
    # Internal endpoint discovered from the page source
    target_url = f"https://guildstats.eu/include/character/tab.php?nick={formatted_name}&tab=experience"
    
    # Final URL sent to your Google Script
    final_url = f"{bridge_url}?url={urllib.parse.quote(target_url)}"
    
    try:
        # Increased timeout because the bridge does a double-fetch for cookies
        r = requests.get(final_url, timeout=45)
        
        if r.status_code != 200:
            print(f"⚠️ Bridge returned status {r.status_code} for {name}")
            return 0
            
        # THE HEAT-SEEKING REGEX:
        # Targets the date, skips HTML tags, and grabs the XP number.
        # Handles both comma (1,000,000) and dot (1.000.000) formats.
        pattern = rf"{target_date}.*?>\s*([+-]?[\d,.]+)"
        match = re.search(pattern, r.text, re.IGNORECASE | re.DOTALL)
        
        if match:
            # Clean formatting: remove separators and the '+' sign
            clean_val = match.group(1).replace(',', '').replace('.', '').replace('+', '')
            return int(clean_val)
        
        return 0
    except Exception as e:
        print(f"⚠️ Request failed for {name}: {e}")
        return 0

# ==========================================

def get_dates():
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
    return {
        "today": now.strftime("%Y-%m-%d"),
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
    # Clamp between 0 and 10
    filled = max(0, min(10, filled))
    return "🟩" * filled + "⬛" * (10 - filled)

# --- DISCORD POSTER ---
def send_discord_post(title, date_label, ranking, team_total, team_change):
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook or not ranking: 
        print("⚠️ Skipping Discord post: No ranking or Webhook URL.")
        return

    max_xp = ranking[0][1]
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    fields = []
    description_addon = ""

    # 1. PROCESS STREAKS
    streaks = load_json(STREAKS_PATH, {"daily": {"last_winner": "", "count": 0}})
    if "daily" not in streaks: streaks["daily"] = {"last_winner": "", "count": 0}
    
    winner_name = ranking[0][0]
    daily = streaks["daily"]

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
    footer_text = f"Team Total: {team_total:,} XP ({team_change} vs last daily)\n"
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
    
    r = requests.post(webhook, json=payload)
    if r.status_code in [200, 204]:
        print("🚀 Discord post sent successfully!")
    else:
        print(f"❌ Discord error: {r.status_code}")

# --- MAIN ENGINE ---
def main():
    dates = get_dates()
    logs = load_json(LOG_PATH)
    state = load_json(STATE_PATH)
    
    if not CHAR_FILE.exists():
        print("❌ Error: characters.txt not found.")
        return
        
    with open(CHAR_FILE) as f: 
        chars = [l.strip() for l in f if l.strip()]

    # --- STEP 1: SCRAPE DATA VIA GOOGLE BRIDGE ---
    print(f"🌐 Using Google Bridge to fetch gains for {dates['yesterday']}...")
    
    success_count = 0
    for name in chars:
        # We fetch fresh data from the bridge
        gain = fetch_guildstats_gain(name, dates['yesterday'])
        
        if isinstance(gain, int):
            if name not in logs: logs[name] = {}
            # Update the log for yesterday
            logs[name][dates['yesterday']] = f"+{gain:,}"
            print(f"✅ {name}: {gain:,} XP (Scraped)")
            success_count += 1
            # Brief pause to be polite to the bridge
            time.sleep(2)
        elif gain == "NO_URL":
            return
        else:
            print(f"⚪ {name}: No update found on GuildStats.")

    if success_count > 0:
        save_json(LOG_PATH, logs)
    else:
        print("⛔ No data could be scraped. Aborting Discord post.")
        return

    # --- STEP 2: CALCULATE RANKINGS ---
    rank_y = []
    total_y, total_db = 0, 0

    for name in chars:
        history = logs.get(name, {})
        val_y = parse_xp(history.get(dates['yesterday'], 0))
        val_db = parse_xp(history.get(dates['day_before'], 0))
        
        if val_y > 0: 
            rank_y.append((name, val_y))
        total_y += val_y
        total_db += val_db

    if not rank_y: 
        print(f"❌ No valid XP gains in log for {dates['yesterday']}.")
        return

    rank_y.sort(key=lambda x: x[1], reverse=True)

    # --- STEP 3: POST TO DISCORD ---
    # Only post if we haven't posted for this date yet
    if state.get("last_daily") != dates['yesterday']:
        change = f"{((total_y - total_db)/total_db)*100:+.1f}%" if total_db > 0 else "0%"
        send_discord_post("Daily Champion", dates['yesterday'], rank_y, total_y, change)
        
        state["last_daily"] = dates['yesterday']
        save_json(STATE_PATH, state)
    else:
        print(f"⏭️ Skipping Discord post: Already posted for {dates['yesterday']}.")

if __name__ == "__main__":
    main()
