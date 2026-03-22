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

    # VOCATIONS TO SCAN (All + Specifics to find lower-level teammates)
    # 2026 update includes Monk and potentially Beastmaster
    categories = ["all", "monk", "knight", "paladin", "sorcerer", "druid"]
    
    print(f"📡 Scanning {WORLD} Highscores for {len(target_chars)} players...")

    for cat in categories:
        if len(found_names) == len(target_chars): break
        
        # Check first 5 pages for each category (Top 250)
        # For 'all', we'll check 20 pages (Top 1000)
        pages_to_check = 20 if cat == "all" else 5
        
        print(f"🔍 Checking category: {cat.upper()}...")
        for page in range(1, pages_to_check + 1):
            if len(found_names) == len(target_chars): break
            
            url = f"https://api.tibiadata.com/v4/highscores/{WORLD}/experience/{cat}/{page}"
            try:
                r = requests.get(url, timeout=15)
                data = r.json()
                highscore_list = data.get("highscores", {}).get("highscore_list", [])
                
                if not highscore_list: break

                for entry in highscore_list:
                    name = entry.get("name")
                    if name and name.lower() in target_chars and name.lower() not in found_names:
                        # FIX: Key is 'value' in highscores
                        xp = entry.get("value") or entry.get("experience") or 0
                        new_totals[name] = xp
                        found_names.add(name.lower())
                        print(f"✅ FOUND: {name} (Rank {entry.get('rank')} in {cat} | {xp:,} XP)")
                
                time.sleep(0.3) # Avoid rate limits
            except: break

    # SAVE AND CLEAN UP
    if new_totals:
        current_data = {}
        if TOTALS_PATH.exists():
            try:
                with open(TOTALS_PATH, "r") as f: current_data = json.load(f)
            except: pass
        current_data.update(new_totals)
        with open(TOTALS_PATH, "w") as f: json.dump(current_data, f, indent=2)

    # 🧹 AUTO-FIX STREAKS.JSON (Removes duplicates from your screenshot)
    if STREAKS_PATH.exists():
        s = {}
        try:
            with open(STREAKS_PATH, "r") as f: s = json.load(f)
            # Keep only the clean nested categories
            clean_streaks = {
                "daily": s.get("daily", {"last_winner": "", "count": 0}),
                "weekly": s.get("weekly", {"last_winner": "", "count": 0}),
                "monthly": s.get("monthly", {"last_winner": "", "count": 0})
            }
            with open(STREAKS_PATH, "w") as f: json.dump(clean_streaks, f, indent=2)
            print("✨ streaks.json cleaned of duplicates.")
        except: pass

    missing = [c for c in target_chars if c not in found_names]
    if missing: print(f"⚠️ Still missing: {', '.join(missing)}")

if __name__ == "__main__":
    main()
