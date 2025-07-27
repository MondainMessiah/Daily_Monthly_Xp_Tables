import os
import json
import asyncio
from datetime import datetime
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

CHAR_FILE = "characters.txt"
JSON_PATH = "xp_log.json"
BEST_DAILY_XP_PATH = "best_daily_xp.json"

def timestamp():
    return datetime.utcnow().strftime("[%Y-%m-%d %H:%M:%S]")

async def scrape_xp_tab9(char_name, page):
    url = f"https://guildstats.eu/character?nick={char_name.replace(' ', '+')}&tab=9"
    print(f"{timestamp()} Scraping {char_name} from {url}")
    await page.goto(url)
    try:
        await page.wait_for_selector("#tabs1", timeout=10000)
    except Exception:
        print(f"{timestamp()} No tabs1 div found for {char_name} on tab 9 (timeout).")
        return {}
    content = await page.content()
    soup = BeautifulSoup(content, "html.parser")
    tabs1_div = soup.find("div", id="tabs1")
    if not tabs1_div:
        print(f"{timestamp()} No tabs1 div found for {char_name} on tab 9 (element not found).")
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
    print(f"{timestamp()} Successfully scraped {len(xp_data)} XP entries for {char_name}.")
    return xp_data

def load_json(path, fallback):
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"{timestamp()} Failed to load {path}: {e}")
    print(f"{timestamp()} Initializing {path} with fallback data.")
    return fallback

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"{timestamp()} Saved data to {path}.") # Added print for save_json

def xp_str_to_int(xp_str):
    try:
        return int(xp_str.replace(",", "").replace("+", "").strip())
    except Exception:
        print(f"{timestamp()} Warning: Could not convert '{xp_str}' to int. Returning 0.")
        return 0

def get_ordinal(n):
    if 10 <= n % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1:'st',2:'nd',3:'rd'}.get(n%10, 'th')
    return f"{n}{suffix}"

def post_to_discord_embed(title, description, fields=None, color=0xf1c40f, footer=""):
    print(f"{timestamp()} Attempting to post to Discord. Title: '{title}'")
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print(f"{timestamp()} ERROR: DISCORD_WEBHOOK_URL not set in environment variables.")
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
    
    # Debug: Print the full payload being sent
    print(f"{timestamp()} Discord Webhook Payload being sent: {json.dumps(payload, indent=2)}")

    try:
        import requests # Import requests here for clarity in logging potential import errors
        resp = requests.post(webhook_url, json=payload, timeout=5)
        if resp.status_code in (200, 204):
            print(f"{timestamp()} Posted to Discord successfully! Status: {resp.status_code}")
        else:
            print(f"{timestamp()} ERROR: Discord post failed! Status: {resp.status_code}, Response: {resp.text}")
    except ImportError:
        print(f"{timestamp()} ERROR: 'requests' library not found. Please ensure it's in your requirements.txt.")
    except Exception as e:
        print(f"{timestamp()} ERROR: Exception posting to Discord: {e}")

async def main():
    print(f"{timestamp()} Starting main script execution.")
    # Load characters list
    if os.path.exists(CHAR_FILE):
        try:
            with open(CHAR_FILE) as f:
                characters = [line.strip() for line in f if line.strip()]
            print(f"{timestamp()} Loaded {len(characters)} characters from {CHAR_FILE}.")
            if not characters:
                print(f"{timestamp()} Warning: {CHAR_FILE} is empty. No characters to scrape.")
        except Exception as e:
            print(f"{timestamp()} ERROR: Failed to load {CHAR_FILE}: {e}")
            characters = []
    else:
        print(f"{timestamp()} ERROR: {CHAR_FILE} not found. Please create it with character names.")
        characters = []

    all_xp = {}
    if characters: # Only proceed with scraping if there are characters
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            for name in characters:
                xp_data = await scrape_xp_tab9(name, page)
                all_xp[name] = xp_data
            await browser.close()
        print(f"{timestamp()} Finished scraping all characters.")
    else:
        print(f"{timestamp()} Skipping Playwright scraping as no characters were found.")

    save_json(JSON_PATH, all_xp)

    latest_dates = [max(xp.keys()) for xp in all_xp.values() if xp]
    print(f"{timestamp()} Detected latest dates: {latest_dates}")

    if not latest_dates:
        print(f"{timestamp()} No valid XP data found across all characters. Will not post main leaderboard.")
        # Removed the direct post here as per typical use cases, it might be better
        # to only post "no gains" if the scraping was successful but found no gains *for today*.
        # The next block handles this more robustly.
        daily_ranking = [] # Ensure daily_ranking is empty for the next checks
    else:
        latest_date = max(latest_dates)
        daily_ranking = []
        print(f"{timestamp()} Determined latest date to be: {latest_date}")

        for name, xp_data in all_xp.items():
            xp_raw = xp_data.get(latest_date)
            if not xp_raw:
                print(f"{timestamp()} No XP data for {latest_date} for {name}.")
                continue
            if "+" not in xp_raw: # Ensure it's a gain, not current XP or loss (though guildstats only shows gains)
                print(f"{timestamp()} Skipping {name}: '{xp_raw}' does not indicate XP gain.")
                continue
            
            xp_val = xp_str_to_int(xp_raw)
            if xp_val > 0:
                daily_ranking.append((name, xp_val, "⬆️", xp_raw))
            else:
                print(f"{timestamp()} Skipping {name}: XP gain was 0 or negative after parsing.")

    daily_ranking.sort(key=lambda x: x[1], reverse=True)
    print(f"{timestamp()} Daily ranking prepared: {daily_ranking}")

    if not daily_ranking:
        print(f"{timestamp()} No characters with XP gains found for {latest_date}. Posting 'No XP gains' message.")
        post_to_discord_embed("Tibia Daily XP Leaderboard", f"No XP gains on {latest_date}.", color=0x636e72)
    else:
        print(f"{timestamp()} Characters with XP gains found. Preparing main leaderboard post.")
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
            f"👑 **Top Gainer:** **{daily_ranking[0][0]}** 👑\n🗓️ **Date:** {latest_date}",
            fields=fields,
            color=0xf1c40f
        )

    # ---- Updated best_daily_xp.json logic ----
    print(f"{timestamp()} Loading previous best daily XP data.")
    best_daily = load_json(BEST_DAILY_XP_PATH, {})
    updated = False

    for name, xp_val, _, _ in daily_ranking: # Loop through actual daily gains
        prev_best = best_daily.get(name, {})
        prev_val = prev_best.get("xp", 0)
        print(f"{timestamp()} Checking personal best for {name}: Current gain={xp_val:,}, Previous best={prev_val:,}")
        if xp_val > prev_val:
            print(f"{timestamp()} New best for {name}: {xp_val:,} XP on {latest_date} (prev: {prev_val:,})")
            best_daily[name] = {"xp": xp_val, "date": latest_date}
            updated = True

            # ✅ Post new personal best to Discord
            print(f"{timestamp()} Posting new personal best for {name} to Discord.")
            post_to_discord_embed(
                title="🏅 New Personal Best!",
                description=f"**{name}** just achieved a new XP record: **+{xp_val:,} XP** on {latest_date}! 🚀",
                color=0x2ecc71,
                footer="Tibia XP Tracker"
            )
        else:
            print(f"{timestamp()} No new best for {name} ({xp_val:,} XP <= {prev_val:,})")

    if updated:
        print(f"{timestamp()} Changes detected for best_daily_xp.json. Saving...")
        save_json(BEST_DAILY_XP_PATH, best_daily)
    else:
        print(f"{timestamp()} No changes to best_daily_xp.json detected. Skipping save.")

    print(f"{timestamp()} Script execution completed.")

if __name__ == "__main__":
    asyncio.run(main())