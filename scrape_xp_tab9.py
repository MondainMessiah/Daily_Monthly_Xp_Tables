import os, json, requests, time, re
from pathlib import Path

# --- CONFIG ---
BASE_DIR = Path(__file__).resolve().parent
CHAR_FILE = BASE_DIR / "characters.txt"
TOTALS_PATH = BASE_DIR / "xp_totals.json"
STREAKS_PATH = BASE_DIR / "streaks.json"
WORLD = "Celesta"

# 2026 Vocation IDs for Tibia.com (Monk is 5, Knights 2, etc.)
VOC_MAP = {"druid": 1, "knight": 2, "paladin": 3, "sorcerer": 4, "monk": 5}

def scrape_tibia_highscore(world, voc_id, page):
    """Fallback: Scrapes the official website when the API filter is restricted."""
    url = f"https://www.tibia.com/community/?subtopic=highscores&world={world}&category=6&vocation={voc_id}&currentpage={page}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200: return []
        # Pattern to find: name, level, and XP (Experience has commas)
        pattern = r'name=(.*?)">(.*?)</a></td><td>.*?</td><td>.*?</td><td>([\d,]+)</td>'
        matches = re.findall(pattern, r.text)
        return [{"name": m[1].replace('&#x27;', "'").replace('&nbsp;', ' '), "xp": int(m[2].replace(',', ''))} for m in matches]
    except: return []

def main():
    if not CHAR_FILE.exists(): return
    with open(CHAR_FILE) as f: target_chars = [l.strip().lower() for l in f if l.strip()]
    
    new_totals, found_names = {}, set()
    print(f"📡 Scanning {WORLD} for {len(target_chars)} players...")

    # 1. API SCAN (Global All - Top 1000)
    for page in range(1, 21):
        if len(found_names) == len(target_chars): break
        url = f"https://api.tibiadata.com/v4/highscores/{WORLD}/experience/all/{page}"
        try:
            r = requests.get(url, timeout=10); data = r.json()
            items = data.get("highscores", {}).get("highscore_list", [])
            if not items: break
            for entry in items:
                name = entry.get("name")
                if name and name.lower() in target_chars:
                    xp = entry.get("value") or entry.get("experience") or 0
                    new_totals[name] = xp; found_names.add(name.lower())
                    print(f"   ✅ API FOUND: {name} ({xp:,} XP)")
        except: break

    # 2. OFFICIAL WEBSITE FALLBACK (For the missing Monks!)
    missing = [c for c in target_chars if c not in found_names]
    if missing:
        print(f"🔍 FALLBACK: Scraping Tibia.com for {len(missing)} missing players...")
        for voc_name, voc_id in VOC_MAP.items():
            if all(m in found_names for m in missing): break
            print(f"   Searching {voc_name.upper()} category (Page 1)...")
            results = scrape_tibia_highscore(WORLD, voc_id, 1) # Check Page 1 (Rank 1-50)
            for res in results:
                if res['name'].lower() in missing:
                    new_totals[res['name']] = res['xp']; found_names.add(res['name'].lower())
                    print(f"   ✅ SCRAPE FOUND: {res['name']} ({res['xp']:,} XP)")

    # 💾 SAVE & CLEAN
    if new_totals:
        curr = {}
        if TOTALS_PATH.exists():
            try:
                with open(TOTALS_PATH, "r") as f: curr = json.load(f)
            except: pass
        curr.update(new_totals); save_json(TOTALS_PATH, curr)
    
    # Clean streaks.json from your earlier double-entry issue
    if STREAKS_PATH.exists():
        try:
            with open(STREAKS_PATH, "r") as f: s = json.load(f)
            clean = {k: s.get(k, {"last_winner": "", "count": 0}) for k in ["daily", "weekly", "monthly"]}
            save_json(STREAKS_PATH, clean); print("✨ streaks.json cleaned.")
        except: pass

def save_json(path, data):
    with open(path, "w") as f: json.dump(data, f, indent=2)

if __name__ == "__main__":
    main()
