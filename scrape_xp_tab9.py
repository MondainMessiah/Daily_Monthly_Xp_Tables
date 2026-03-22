import os, json, requests, time
from pathlib import Path

# --- CONFIG ---
BASE_DIR = Path(__file__).resolve().parent
CHAR_FILE = BASE_DIR / "characters.txt"
TOTALS_PATH = BASE_DIR / "xp_totals.json"
WORLD = "Celesta" 

def main():
    if not CHAR_FILE.exists(): return
    with open(CHAR_FILE) as f: 
        # Clean the list: lowercase and stripped
        target_chars = [l.strip().lower() for l in f if l.strip()]
    
    print(f"📡 Scanning {WORLD} Highscores (Top 1000) for {len(target_chars)} players...")
    new_totals = {}
    found_names = set()

    # We need to check pages 1 to 20 (50 players per page = 1000 total)
    for page in range(1, 21):
        if len(found_names) == len(target_chars):
            break # Stop early if we found everyone!

        print(f"🔍 Checking Page {page}...")
        url = f"https://api.tibiadata.com/v4/highscores/{WORLD}/experience/all/{page}"
        
        try:
            r = requests.get(url, timeout=20)
            data = r.json()
            highscore_list = data.get("highscores", {}).get("highscore_list", [])
            
            if not highscore_list:
                print(f"⚠️ Page {page} returned no data. Stopping.")
                break

            for entry in highscore_list:
                name = entry.get("name")
                if name and name.lower() in target_chars:
                    xp = entry.get("experience", 0)
                    new_totals[name] = xp
                    found_names.add(name.lower())
                    print(f"✅ FOUND: {name} (Rank {entry.get('rank')} | {xp:,} XP)")
            
            # Small delay to be nice to the API
            time.sleep(0.5)

        except Exception as e:
            print(f"❌ Error on page {page}: {e}")
            break

    # Save results
    if new_totals:
        # Load existing if any, and update
        current_data = {}
        if TOTALS_PATH.exists():
            try:
                with open(TOTALS_PATH, "r") as f: current_data = json.load(f)
            except: pass
        
        current_data.update(new_totals)
        with open(TOTALS_PATH, "w") as f:
            json.dump(current_data, f, indent=2)
        print(f"💾 Saved {len(new_totals)} characters to totals.")
    
    # Report missing
    missing = [c for c in target_chars if c not in found_names]
    if missing:
        print(f"⚠️ Not found in Top 1000: {', '.join(missing)}")
        print("💡 If they are in the Top 1000, double-check the spelling in characters.txt!")

if __name__ == "__main__":
    main()
