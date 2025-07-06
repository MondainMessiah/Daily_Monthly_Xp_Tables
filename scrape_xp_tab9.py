import requests
import json
import os
from bs4 import BeautifulSoup
import datetime
import calendar
import subprocess
import time

CHAR_FILE = "characters.txt"
JSON_PATH = "xp_log.json"
MONTHLY_XP_PATH = "monthly_xp.json"
BEST_DAILY_XP_PATH = "best_daily_xp.json"

def timestamp():
    return time.strftime("[%Y-%m-%d %H:%M:%S]")

def scrape_xp_tab9(char_name):
    url = f"https://guildstats.eu/character?nick={char_name.replace(' ', '+')}&tab=9"
    print(f"{timestamp()} Scraping {char_name} from {url}")
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
    except Exception as e:
        print(f"{timestamp()} Error fetching data for {char_name}: {e}")
        return {}
    soup = BeautifulSoup(response.text, "html.parser")
    tabs1_div = soup.find("div", id="tabs1")
    if not tabs1_div:
        print(f"{timestamp()} No tabs1 div found for {char_name} on tab 9.")
        return {}
    table = tabs1_div.find("table", class_="newTable")
    if not table:
        print(f"{timestamp()} No XP table found for {char_name} on tab 9.")
        return {}
    xp_data = {}
    for row in table.find_all("tr")[1:]:
        tds = row.find_all("td")
        if len(tds) < 2:
            continue
        date = tds[0].get_text(strip=True)
        xp_change = tds[1].get_text(strip=True)
        xp_data[date] = xp_change
    return xp_data

def load_json(path, fallback):
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"{timestamp()} Failed to load {path}: {e}")
    return fallback

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def xp_str_to_int(xp_str):
    try:
        return int(xp_str.replace(",", "").replace("+", "").strip())
    except Exception:
        return 0

def get_current_month():
    return datetime.datetime.now().strftime("%Y-%m")

def get_ordinal(n):
    if 10 <= n % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1:'st',2:'nd',3:'rd'}.get(n%10, 'th')
    return f"{n}{suffix}"

def post_to_discord_embed(title, description, fields=None, color=0xf1c40f, footer=""):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print(f"{timestamp()} DISCORD_WEBHOOK_URL not set.")
        return
    embed = {
        "title": title,
        "description": description,
        "color": color
    }
    if footer:
        embed["footer"] = {"text": footer}
    if fields:
        embed["fields"] = fields
    payload = {"embeds": [embed]}
    try:
        resp = requests.post(webhook_url, json=payload, timeout=5)
        if resp.status_code in (200, 204):
            print(f"{timestamp()} Posted to Discord.")
        else:
            print(f"{timestamp()} Discord post failed: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"{timestamp()} Exception posting to Discord: {e}")

def run_git_command(args, timeout=30):
    try:
        print(f"{timestamp()} Running git: {' '.join(args)}")
        subprocess.run(["git"] + args, check=True, timeout=timeout)
    except Exception as e:
        print(f"{timestamp()} Git error: {e}")

if __name__ == "__main__":
    characters = load_json(CHAR_FILE, fallback=[] if not os.path.exists(CHAR_FILE) else open(CHAR_FILE).read().splitlines())
    all_xp = {name: scrape_xp_tab9(name) for name in characters}
    save_json("xp_log.json", all_xp)

    latest_dates = [max(xp.keys()) for xp in all_xp.values() if xp]
    if not latest_dates:
        print(f"{timestamp()} No valid XP data.")
        exit()

    latest_date = max(latest_dates)
    daily_ranking = []

    for name, xp_data in all_xp.items():
        xp_raw = xp_data.get(latest_date)
        if not xp_raw or "+" not in xp_raw:
            continue
        xp_val = xp_str_to_int(xp_raw)
        if xp_val > 0:
            daily_ranking.append((name, xp_val, "⬆️", xp_raw))

    daily_ranking.sort(key=lambda x: x[1], reverse=True)

    if not daily_ranking:
        post_to_discord_embed("Tibia Daily XP Leaderboard", f"No XP gains on {latest_date}.", color=0x636e72)
        exit()

    medals = ["🥇", "🥈", "🥉"]
    fields = []
    for idx, (name, xp_val, arrow, xp_raw) in enumerate(daily_ranking):
        prefix = medals[idx] if idx < 3 else get_ordinal(idx + 1)
        fields.append({
            "name": f"{prefix} **{name}**",
            "value": f"+{xp_val:,} XP {arrow}",
            "inline": False
        })

    post_to_discord_embed(
        "🟡🟢🔵 Tibia Daily XP Leaderboard 🔵🟢🟡",
        f"👑 **Top Gainer:** **{daily_ranking[0][0]}** 👑\n📅 **Date:** {latest_date}",
        fields=fields,
        color=0xf1c40f
    )

    # ---- Updated best_daily_xp.json logic ----
    best_daily = load_json(BEST_DAILY_XP_PATH, {})
    updated = False

    for name, xp_val, _, _ in daily_ranking:
        prev_best = best_daily.get(name, {})
        prev_val = prev_best.get("xp", 0)
        if xp_val > prev_val:
            print(f"{timestamp()} New best for {name}: {xp_val:,} XP on {latest_date} (prev: {prev_val:,})")
            best_daily[name] = {"xp": xp_val, "date": latest_date}
            updated = True

            # ✅ Post new personal best to Discord
            post_to_discord_embed(
                title="🏅 New Personal Best!",
                description=f"**{name}** just achieved a new XP record: **+{xp_val:,} XP** on {latest_date}! 🚀",
                color=0x2ecc71,
                footer="Tibia XP Tracker"
            )
        else:
            print(f"{timestamp()} No new best for {name} ({xp_val:,} XP <= {prev_val:,})")

    if updated:
        print(f"{timestamp()} Saving updated best_daily_xp.json")
        save_json(BEST_DAILY_XP_PATH, best_daily)
    else:
        print(f"{timestamp()} No changes to best_daily_xp.json")
