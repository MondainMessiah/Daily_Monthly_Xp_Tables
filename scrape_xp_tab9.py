import requests
import json
import os
from bs4 import BeautifulSoup

CHAR_FILE = "characters.txt"
JSON_PATH = "xp_log.json"

def scrape_xp_tab9(char_name):
    url = f"https://guildstats.eu/character?nick={char_name.replace(' ', '+')}&tab=9"
    response = requests.get(url)
    soup = BeautifulSoup(response.text, "html.parser")
    # Updated: Use the specific table path as per the provided XPath
    table = soup.select_one("body > main > div > div.container > div > div.row > div.col-md-6 > div > div:nth-of-type(3) > table")
    if not table:
        print(f"No XP data found for {char_name} on tab 9.")
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
        print("No XP changes.")
        return False
    with open(JSON_PATH, "w") as f:
        json.dump(data, f, indent=2)
    print("XP data updated.")
    return True

def post_to_discord(message):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("DISCORD_WEBHOOK_URL environment variable not set. Skipping Discord notification.")
        return
    payload = {"content": message}
    try:
        resp = requests.post(webhook_url, json=payload)
        if resp.status_code in (200, 204):
            print("Posted to Discord successfully.")
        else:
            print(f"Failed to post to Discord: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"Exception posting to Discord: {e}")

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

        # Prepare list of (name, xp_value) for the latest date
        daily_xp_ranking = []
        for name, xp_dict in all_xp.items():
            xp_str = xp_dict.get(latest_date, "0").replace(",", "").replace("+", "").strip()
            try:
                xp_val = int(xp_str)
            except ValueError:
                xp_val = 0
            daily_xp_ranking.append((name, xp_val))

        # Sort descending by XP
        daily_xp_ranking.sort(key=lambda x: x[1], reverse=True)

        # Assign medals for top 3
        medals = ["🥇", "🥈", "🥉"]
        medaled_output = []
        print(f"\n🏆 Daily XP Gains for {latest_date}:")
        for idx, (name, xp_val) in enumerate(daily_xp_ranking):
            medal = medals[idx] if idx < 3 else ""
            line = f"{medal} {name}: {xp_val:,} XP" if medal else f"{name}: {xp_val:,} XP"
            print(line)
            medaled_output.append(line)

        # Send to Discord
        message = f"🏆 Daily XP Gains for {latest_date}:\n" + "\n".join(medaled_output)
        post_to_discord(message)

        # Commit & push changes to GitHub
        os.system("git config user.name github-actions")
        os.system("git config user.email github-actions@github.com")
        os.system("git add xp_log.json")
        commit_message = f"Daily XP update {latest_date}\n" + "\n".join(medaled_output)
        os.system(f'git commit -m "{commit_message}" || echo "No changes to commit"')
        os.system("git pull --rebase || echo 'Nothing to rebase'")
        os.system("git push || echo 'Push failed (possibly due to no new commit or branch protection)'")
