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
        response = requests.get(url, timeout=15)
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
    for row in table.find_all("tr")[1:]:  # skip header
        tds = row.find_all("td")
        if len(tds) < 2:
            continue
        date = tds[0].get_text(strip=True)
        xp_change = tds[1].get_text(strip=True)
        xp_data[date] = xp_change
    return xp_data

def load_characters():
    with open(CHAR_FILE, "r") as f:
        return [line.strip() for line in f if line.strip()]

def load_existing():
    if os.path.exists(JSON_PATH):
        with open(JSON_PATH, "r") as f:
            return json.load(f)
    return {}

def save_if_changed(data):
    old = load_existing()
    if data == old:
        print(f"{timestamp()} No XP changes.")
        return False
    with open(JSON_PATH, "w") as f:
        json.dump(data, f, indent=2)
    print(f"{timestamp()} XP data updated.")
    return True

def post_to_discord_embed(title, description, fields=None, color=0xf1c40f, footer=""):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print(f"{timestamp()} DISCORD_WEBHOOK_URL environment variable not set. Skipping Discord notification.")
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
    payload = {
        "embeds": [embed]
    }
    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        if resp.status_code in (200, 204):
            print(f"{timestamp()} Posted to Discord successfully.")
        else:
            print(f"{timestamp()} Failed to post to Discord: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"{timestamp()} Exception posting to Discord: {e}")

def xp_str_to_int(xp_str):
    try:
        return int(xp_str.replace(",", "").replace("+", "").strip())
    except Exception:
        return 0

def load_monthly_xp(characters):
    data = {}
    if os.path.exists(MONTHLY_XP_PATH):
        try:
            with open(MONTHLY_XP_PATH, "r") as f:
                data = json.load(f)
        except Exception as e:
            print(f"{timestamp()} Failed to load {MONTHLY_XP_PATH}, resetting: {e}")
            data = {}
    if not isinstance(data, dict):
        data = {}
    if "month" not in data or not isinstance(data["month"], str):
        data["month"] = ""
    if "totals" not in data or not isinstance(data["totals"], dict):
        data["totals"] = {name: 0 for name in characters}
    for name in characters:
        if name not in data["totals"]:
            data["totals"][name] = 0
    return data

def save_monthly_xp(data):
    with open(MONTHLY_XP_PATH, "w") as f:
        json.dump(data, f, indent=2)

def load_best_daily_xp():
    if os.path.exists(BEST_DAILY_XP_PATH):
        try:
            with open(BEST_DAILY_XP_PATH, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"{timestamp()} Failed to load {BEST_DAILY_XP_PATH}, resetting: {e}")
    return {}

def save_best_daily_xp(data):
    with open(BEST_DAILY_XP_PATH, "w") as f:
        json.dump(data, f, indent=2)

def get_current_month():
    return datetime.datetime.now().strftime("%Y-%m")

def get_ordinal(n):
    if 10 <= n % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1:'st',2:'nd',3:'rd'}.get(n%10, 'th')
    return f"{n}{suffix}"

def run_git_command(args, timeout=30):
    try:
        print(f"{timestamp()} Running git command: {' '.join(['git'] + args)}")
        subprocess.run(["git"] + args, check=True, timeout=timeout)
        print(f"{timestamp()} Git command succeeded: {' '.join(args)}")
    except subprocess.CalledProcessError as e:
        print(f"{timestamp()} Git command failed: {' '.join(args)}; {e}")
    except subprocess.TimeoutExpired:
        print(f"{timestamp()} Git command timed out: {' '.join(args)}")

if __name__ == "__main__":
    characters = load_characters()
    all_xp = {}

    for name in characters:
        all_xp[name] = scrape_xp_tab9(name)

    if not all_xp:
        print(f"{timestamp()} No data scraped for any characters.")
        exit()

    if save_if_changed(all_xp):
        latest_dates = [max(xp.keys()) for xp in all_xp.values() if xp]
        if not latest_dates:
            print(f"{timestamp()} No XP dates found.")
            exit()
        latest_date = max(latest_dates)
        daily_xp_ranking = []
        for name, xp_dict in all_xp.items():
            xp_raw = xp_dict.get(latest_date, None)
            if not xp_raw or "+" not in xp_raw:
                continue
            xp_val = xp_str_to_int(xp_raw)
            if xp_val <= 0:
                continue
            line_arrow = "⬆️"
            daily_xp_ranking.append((name, xp_val, line_arrow, xp_raw))
        daily_xp_ranking.sort(key=lambda x: x[1], reverse=True)
        if not daily_xp_ranking:
            print(f"{timestamp()} No XP increases today.")
            post_to_discord_embed(
                "Tibia Daily XP Leaderboard",
                f"📉 No XP increases for any tracked characters on {latest_date}.",
                color=0x636e72
            )
            exit()

        # --- NEW: Update best_daily_xp.json ---
        best_daily_xp = load_best_daily_xp()
        for name, xp_val, _, _ in daily_xp_ranking:
            prev_best = best_daily_xp.get(name)
            if (not prev_best) or (xp_val > prev_best["xp"]):
                best_daily_xp[name] = {
                    "xp": xp_val,       # Store as integer, no commas
                    "date": latest_date
                }
        save_best_daily_xp(best_daily_xp)
        # --- END NEW ---

        medals = ["🥇", "🥈", "🥉"]
        fields = []
        for idx, (name, xp_val, arrow, xp_raw) in enumerate(daily_xp_ranking):
            prefix = medals[idx] if idx < 3 else get_ordinal(idx+1)
            bold_name = f"**{name}**"
            xp_disp = f"+{xp_val:,} XP"
            value = f"{xp_disp} {arrow}"
            fields.append({
                "name": f"{prefix} {bold_name}",
                "value": value,
                "inline": False
            })

        top_gainer = f"**{daily_xp_ranking[0][0]}**" if daily_xp_ranking else "N/A"

        title = "🟡🟢🔵 Tibia Daily XP Leaderboard 🔵🟢🟡"
        description = (
            f"👑 **Top Gainer:** {top_gainer} 👑\n"
            f"📅 **Date:** {latest_date}"
        )
        post_to_discord_embed(
            title=title,
            description=description,
            fields=fields,
            color=0xf1c40f,
            footer=""
        )

        # --- Monthly leaderboard logic ---
        monthly_xp = load_monthly_xp(characters)
        current_month = get_current_month()
        if monthly_xp["month"] != current_month:
            print(f"{timestamp()} New month detected ({current_month}), resetting monthly totals.")
            monthly_xp = {"month": current_month, "totals": {name: 0 for name in characters}}
        for name, xp_dict in all_xp.items():
            xp_raw = xp_dict.get(latest_date, None)
            if not xp_raw or "+" not in xp_raw:
                continue
            xp_val = xp_str_to_int(xp_raw)
            if xp_val <= 0:
                continue
            monthly_xp["totals"][name] = monthly_xp["totals"].get(name, 0) + xp_val
        save_monthly_xp(monthly_xp)

        today = datetime.date.today()
        last_day = calendar.monthrange(today.year, today.month)[1]
        if today.day == last_day:
            monthly_ranking = sorted(monthly_xp["totals"].items(), key=lambda x: x[1], reverse=True)
            monthly_fields = []
            for idx, (name, total_xp) in enumerate(monthly_ranking):
                if total_xp <= 0:
                    continue
                prefix = medals[idx] if idx < 3 else get_ordinal(idx+1)
                bold_name = f"**{name}**"
                monthly_fields.append({
                    "name": f"{prefix} {bold_name}",
                    "value": f"+{total_xp:,} XP",
                    "inline": False
                })
            monthly_top = f"**{monthly_ranking[0][0]}**" if monthly_ranking else ""
            monthly_title = "🟡🟢🔵 Total Monthly XP Table 🔵🟢🟡 "
            monthly_description = (
                f"👑 **Top Gainer:** {monthly_top} 👑\n"
                f"📅 **Month:** {current_month}"
            )
            post_to_discord_embed(
                title=monthly_title,
                description=monthly_description,
                fields=monthly_fields,
                color=0x2980b9,
                footer=""
            )

        # Commit & push changes to GitHub
        run_git_command(["config", "user.name", "github-actions"])
        run_git_command(["config", "user.email", "github-actions@github.com"])
        run_git_command(["add", "xp_log.json", "monthly_xp.json", "best_daily_xp.json"])
        commit_message = f"Daily XP update {latest_date}"
        run_git_command(["commit", "-m", commit_message])
        run_git_command(["pull", "--rebase"])
        run_git_command(["push"])
    else:
        print(f"{timestamp()} No changes detected; skipping Discord post and Git push.")
