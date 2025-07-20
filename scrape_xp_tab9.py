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
        print(f"{timestamp()} No tabs1 div found for {char_name} on tab 9.")
        return {}
    content = await page.content()
    soup = BeautifulSoup(content, "html.parser")
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
        import requests
        resp = requests.post(webhook_url, json=payload, timeout=5)
        if resp.status_code in (200, 204):
            print(f"{timestamp()} Posted to Discord.")
        else:
            print(f"{timestamp()} Discord post failed: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"{timestamp()} Exception posting to Discord: {e}")

async def main():
    # Load characters list
    if os.path.exists(CHAR_FILE):
        try:
            with open(CHAR_FILE) as f:
                characters = [line.strip() for line in f if line.strip()]
        except Exception as e:
            print(f"{timestamp()} Failed to load {CHAR_FILE}: {e}")
            characters = []
    else:
        characters = []

    all_xp = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        for name in characters:
            xp_data = await scrape_xp_tab9(name, page)
            all_xp[name] = xp_data
        await browser.close()

    save_json(JSON_PATH, all_xp)

    latest_dates = [max(xp.keys()) for xp in all_xp.values() if xp]
    if not latest_dates:
        print(f"{timestamp()} No valid XP data.")
        return

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
        return

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

if __name__ == "__main__":
    asyncio.run(main())
