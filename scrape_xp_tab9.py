import os, json, requests, time
from pathlib import Path

# --- CONFIG ---
BASE_DIR = Path(__file__).resolve().parent
CHAR_FILE = BASE_DIR / "characters.txt"
TOTALS_PATH = BASE_DIR / "xp_totals.json"
STREAKS_PATH = BASE_DIR / "streaks.json"
WORLD = "Celesta"

def main():
    if not CHAR_FILE.exists(): return
    with open(CHAR_FILE) as f:
        target_chars = [l.strip().lower() for l in f if l.strip()]
    
    new_totals = {}
    found_names = set()

    # We check ALL first, then MONK specifically for our missing teammates
    categories = ["all", "monk", "knight", "paladin", "sorcerer", "druid"]
    
    print(f"📡 Scanning {WORLD} for {len(target_chars)} players...")

    for cat in categories:
        if len(found_names) == len(target_chars): break
        
        # We check 20 pages (Top 1000) for every vocation to be 100% sure
        print(f"🔍 [SEARCH] Category: {cat.upper()}")
        for page in range(1, 21):
            if len(found_names) == len(target_chars): break
            
            url = f"https://api.tibiadata.com/v4/highscores/{WORLD}/experience/{cat}/{page}"
            try:
                r = requests.get(url, timeout=15)
                data = r.json()
                
                # Check for API error messages
                if "information" in data and "error" in data["information"]:
                    print(f"   ⚠️ API Error for {cat}: {data['information']['error']}")
                    break

                highscore_list = data.get("highscores", {}).get("highscore_list", [])
                if not highscore_list: 
                    # If Page 1 is empty, maybe the vocation name is wrong
                    if page == 1: print(f"   ⚠️ No data found on Page 1 for {cat}.")
                    break

                found_on_page = 0
                for entry in highscore_list:
                    name = entry.get("name")
                    if name and name.lower() in target_chars and name.lower() not in found_names:
                        # KEY FIX: Using 'value' for XP in highscores
                        xp = entry.get("value") or entry.get("experience") or 0
                        new_totals[name] = xp
                        found_names.add(name.lower())
                        print(f"   ✅ FOUND: {name} (Rank {entry.get('rank')} in {cat} | {xp:,} XP)")
                        found_on_page += 1
                
                # If we're deep in the pages and found nobody, don't spam the logs
                if found_on_page == 0 and page % 5 == 0:
                    print(f"   ... checked up to Page {page} ...")

                time.sleep(0.3) 
            except Exception as e:
                print(f"   ❌ Network Error on Page {page}: {e}")
                break

    # 💾 SAVE TOTALS
    if new_totals:
        current_data = {}
        if TOTALS_PATH.exists():
            try:
                with open(TOTALS_PATH, "r") as f: current_data = json.load(f)
            except: pass
        current_data.update(new_totals)
        with open(TOTALS_PATH, "w") as f: json.dump(current_data, f, indent=2)
        print(f"💾 Total XP file updated.")

    # 🧹 STREAKS CLEANER (Removes the double-repeating lines from your JSON)
    if STREAKS_PATH.exists():
        try:
            with open(STREAKS_PATH, "r") as f: s = json.load(f)
            clean_streaks = {
                "daily": s.get("daily", {"last_winner": "", "count": 0}),
                "weekly": s.get("weekly", {"last_winner": "", "count": 0}),
                "monthly": s.get("monthly", {"last_winner": "", "count": 0})
            }
            with open(STREAKS_PATH, "w") as f: json.dump(clean_streaks, f, indent=2)
            print("✨ streaks.json duplicates removed.")
        except: pass

    missing = [c for c in target_chars if c not in found_names]
    if missing: 
        print(f"⚠️ Still missing: {', '.join(missing)}")
        print("💡 TIP: Check characters.txt for extra spaces or typos!")

if __name__ == "__main__":
    main()
