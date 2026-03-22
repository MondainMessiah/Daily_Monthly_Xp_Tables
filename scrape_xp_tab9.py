import os, json, requests, time, re
from pathlib import Path

# --- CONFIG ---
BASE_DIR = Path(__file__).resolve().parent
CHAR_FILE = BASE_DIR / "characters.txt"
TOTALS_PATH = BASE_DIR / "xp_totals.json"
STREAKS_PATH = BASE_DIR / "streaks.json"
WORLD = "Celesta"

def scrape_tibia_highscore(world, voc_id, page):
    """Scrapes the official Tibia.com highscores with high resilience."""
    url = f"https://www.tibia.com/community/?subtopic=highscores&world={world}&category=6&vocation={voc_id}&currentpage={page}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0'}
    try:
        r = requests.get(url, headers=headers, timeout=20)
        if r.status_code != 200: return []
        
        # This regex is broader to catch names and XP even if the HTML structure shifts
        # It looks for the Name link and then jumps to the XP column (3 cells away)
        pattern = r'name=(.*?)">(.*?)</a></td>.*?</td>.*?</td><td>([\d,]+)</td>'
        matches = re.findall(pattern, r.text)
        
        results = []
        for m in matches:
            # Clean up HTML entities like apostrophes in names
            clean_name = m[1].replace('&#x27;', "'").replace('&nbsp;', ' ').strip()
            xp_val = int(m[2].replace(',', ''))
            results.append({"name": clean_name, "xp": xp_val})
        return results
    except Exception as e:
        print(f"      ⚠️ Scrape error on ID {voc_id}: {e}")
        return []

def main():
    if not CHAR_FILE.exists(): return
    with open(CHAR_FILE) as f:
        target_chars = [l.strip().lower() for l in f if l.strip()]
    
    new_totals, found_names = {}, set()
    print(f"📡 Scanning {WORLD} for {len(target_chars)} players...")

    # --- STEP 1: API GLOBAL SCAN (Top 1000 All) ---
    print("🔍 [STEP 1] Checking Global API (Top 1000)...")
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
                    new_totals[name] = xp
                    found_names.add(name.lower())
                    print(f"   ✅ API FOUND: {name} ({xp:,} XP)")
        except: break

    # --- STEP 2: BRUTE FORCE VOCATION SCRAPE (For the missing Monks) ---
    missing = [c for c in target_chars if c not in found_names]
    if missing:
        print(f"🔍 [STEP 2] Brute-forcing Vocation IDs for {len(missing)} missing players...")
        # We check IDs 1-12 to cover all possible new 2026 vocations
        for voc_id in range(1, 13):
            if all(m in found_names for m in missing): break
            
            print(f"   Checking Vocation ID: {voc_id} (Page 1)...")
            results = scrape_tibia_highscore(WORLD, voc_id, 1)
            
            # Debug: print the first name found to see if we are in the right place
            if results:
                print(f"      (Sample name on ID {voc_id}: {results[0]['name']})")
                
            for res in results:
                if res['name'].lower() in missing:
                    new_totals[res['name']] = res['xp']
                    found_names.add(res['name'].lower())
                    print(f"   ✅ SCRAPE FOUND: {res['name']} ({res['xp']:,} XP)")
            
            time.sleep(1) # Be gentle with the website

    # --- SAVE & RECOVERY ---
    if new_totals:
        curr = {}
        if TOTALS_PATH.exists():
            try:
                with open(TOTALS_PATH, "r") as f: curr = json.load(f)
            except: pass
        curr.update(new_totals)
        with open(TOTALS_PATH, "w") as f: json.dump(curr, f, indent=2)
        print(f"💾 Totals updated with {len(found_names)} players.")
    
    # Final cleanup of the streaks.json to remove those repeating lines
    if STREAKS_PATH.exists():
        try:
            with open(STREAKS_PATH, "r") as f: s = json.load(f)
            clean = {k: s.get(k, {"last_winner": "", "count": 0}) for k in ["daily", "weekly", "monthly"]}
            with open(STREAKS_PATH, "w") as f: json.dump(clean, f, indent=2)
        except: pass

    final_missing = [c for c in target_chars if c not in found_names]
    if final_missing:
        print(f"❌ Still missing after deep scan: {', '.join(final_missing)}")

if __name__ == "__main__":
    main()
