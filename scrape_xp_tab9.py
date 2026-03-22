import os, json, requests
from pathlib import Path

# --- CONFIG ---
BASE_DIR = Path(__file__).resolve().parent
CHAR_FILE = BASE_DIR / "characters.txt"
TOTALS_PATH = BASE_DIR / "xp_totals.json"
WORLD = "Celesta" # Change this to your world

def main():
    if not CHAR_FILE.exists(): return
    with open(CHAR_FILE) as f: chars = [l.strip().lower() for l in f if l.strip()]
    
    # In 2026, we MUST pull from Highscores to see Total XP
    print(f"📡 Fetching {WORLD} Highscores (Top 1000)...")
    url = f"https://api.tibiadata.com/v4/highscores/{WORLD}/experience/all/1"
    
    try:
        r = requests.get(url, timeout=20)
        data = r.json()
        highscore_list = data.get("highscores", {}).get("highscore_list", [])
        
        new_totals = {}
        found_count = 0

        # Map the highscores to our characters
        for entry in highscore_list:
            name = entry.get("name")
            if name and name.lower() in chars:
                xp = entry.get("experience", 0)
                new_totals[name] = xp
                print(f"✅ {name}: Found {xp:,} XP (Rank {entry.get('rank')})")
                found_count += 1

        if new_totals:
            with open(TOTALS_PATH, "w") as f:
                json.dump(new_totals, f, indent=2)
            print(f"💾 Saved {found_count} characters to totals.")
        
        # Check for anyone missing (Not in Top 1000)
        missing = [c for c in chars if c not in [n.lower() for n in new_totals.keys()]]
        for m in missing:
            print(f"⚠️ {m}: Not found in Top 1000 Highscores (Cannot track XP).")

    except Exception as e:
        print(f"❌ Connection Error: {e}")

if __name__ == "__main__":
    main()
