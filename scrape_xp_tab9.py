import requests
import json
import os
from bs4 import BeautifulSoup
from datetime import datetime

CHAR_FILE = "characters.txt"
JSON_PATH = "xp_log.json"

# Tibia style colors and icons
TIBIA_ICON = "https://www.tibia.com/img/tibiacom/tibia-logo-big.png"
GOLD = 0xFFD700

def scrape_xp_tab9(char_name):
    url = f"https://guildstats.eu/character?nick={char_name.replace(' ', '+')}&tab=9"
    response = requests.get(url)
    soup = BeautifulSoup(response.text, "html.parser")
    tabs1_div = soup.find("div", id="tabs1")
    if not tabs1_div:
        print(f"No tabs1 div found for {char_name} on tab 9.")
        return {}
    table = tabs1_div.find("table", class_="newTable")
    if not table:
        print(f"No XP table found for {char_name} on tab 9.")
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
        print("No XP changes.")
        return False
    with open(JSON_PATH, "w") as f:
        json.dump(data, f, indent=2)
    print("XP data updated.")
    return True

def post_to_discord_tibia_style(title, leaderboard_lines, top_gainer, date_str):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("DISCORD_WEBHOOK_URL environment variable not set. Skipping Discord notification.")
        return
    embed = {
        "title": f"🏆 {title} ({date_str})",
        "description": "\n".join(leaderboard_lines) + f"\n\n**Top Gainer:** **{top_gainer}** 🎉\n*Keep grinding, heroes!*",
        "color": GOLD,
        "footer": {
            "text": "Tibia XP Leaderboard • tibia.com style",
            "icon_url": TIBIA_ICON
        },
        "thumbnail": {"url": TIBIA_ICON}
    }
    payload = {
        "username": "Tibia Notifications",
        "avatar_url": TIBIA_ICON,
        "embeds": [embed],
        "allowed_mentions": {"parse": []}
    }
    try:
        resp = requests.post(webhook_url, json=payload)
        if resp.status_code in (200, 204):
            print("Posted to Discord successfully.")
        else:
            print(f"Failed to post to Discord: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"Exception posting to Discord: {e}")

def xp_str_to_int(xp_str):
    try:
        return int(xp_str.replace(",", "").replace("+", "").strip())
    except Exception:
        return 0

if __name__ == "__main__":
    characters = load_characters()
    all_xp = {}

    for name in characters:
        print(f"Scraping {name}...")
        all_xp[name] = scrape_xp_tab9(name)

    if not all_xp:
        print("No data scraped for any characters.")
        exit()

    if save_if_changed(all_xp):
        # Determine latest date with XP data across all characters
        latest_dates = [max(xp.keys()) for xp in all_xp.values() if xp]
        if not latest_dates:
            print("No XP dates found.")
            exit()
        latest_date = max(latest_dates)

        # Prepare leaderboard with XP change, up arrow, only increases
        daily_xp_ranking = []
        for name, xp_dict in all_xp.items():
            xp_raw = xp_dict.get(latest_date, None)
            if not xp_raw or "+" not in xp_raw:
                continue  # Skip if no gain
            xp_val = xp_str_to_int(xp_raw)
            if xp_val <= 0:
                continue  # Only positive increases
            line_arrow = "⬆️"
            daily_xp_ranking.append((name, xp_val, line_arrow, xp_raw))

        # Sort descending by XP
        daily_xp_ranking.sort(key=lambda x: x[1], reverse=True)

        if not daily_xp_ranking:
            print("No XP increases today.")
            post_to_discord_tibia_style(
                "Daily XP Leaderboard", 
                ["📉 No XP increases for any tracked characters."],
                "N/A",
                latest_date
            )
            exit()

        medals = ["🥇", "🥈", "🥉"]
        medaled_output = []
        for idx, (name, xp_val, arrow, xp_raw) in enumerate(daily_xp_ranking):
            medal = medals[idx] if idx < 3 else ""
            bold_name = f"**{name}**" if idx < 3 else name
            xp_disp = f"+{xp_val:,}"
            line = f"{medal} {bold_name}: {xp_disp} XP {arrow}".strip()
            medaled_output.append(line)

        top_gainer = daily_xp_ranking[0][0] if daily_xp_ranking else "N/A"

        # Tibia-styled Discord embed
        post_to_discord_tibia_style(
            "Daily XP Leaderboard",
            medaled_output,
            top_gainer,
            latest_date
        )

        # Commit & push changes to GitHub
        os.system("git config user.name github-actions")
        os.system("git config user.email github-actions@github.com")
        os.system("git add xp_log.json")
        commit_message = f"Daily XP update {latest_date}\n" + "\n".join(medaled_output)
        os.system(f'git commit -m "{commit_message}" || echo "No changes to commit"')
        os.system("git pull --rebase || echo 'Nothing to rebase'")
        os.system("git push || echo 'Push failed (possibly due to no new commit or branch protection)'")
