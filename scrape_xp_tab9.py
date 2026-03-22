import os, json, requests
from pathlib import Path

# --- CONFIG ---
BASE_DIR = Path(__file__).resolve().parent
CHAR_FILE = BASE_DIR / "characters.txt"
TOTALS_PATH = BASE_DIR / "xp_totals.json"

def main():
    if not CHAR_FILE.exists():
        print("❌ ERROR: characters.txt not found!")
        return

    with open(CHAR_FILE) as f:
        chars = [l.strip() for l in f if l.strip()]
    
    print(f"📡 Found {len(chars)} characters. Fetching live totals...")
    new_totals = {}
    
    # We add a User-Agent to identify our bot
    headers = {'User-Agent': 'TibiaXPTrackerBot/1.0'}

    for name in chars:
        # We try both v4 and ensure URL encoding is correct
        safe_name = name.replace(' ', '%20')
        url = f"https://api.tibiadata.com/v4/character/{safe_name}"
        
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
                print(f"❌ {name}: API Error (Status: {r.status_code})")
                continue
                
            data = r.json()
            
            # --- DYNAMIC DATA SEARCH ---
            # TibiaData v4 structure check
            char_obj = data.get("character", {}).get("character", {})
            total_xp = char_obj.get("experience", 0)
            
            # If still 0, print the response keys to debug
            if total_xp == 0:
                print(f"⚠️ {name}: Found 0 XP. Response keys: {list(data.keys())}")
                if "character" in data:
                    print(f"   Internal keys: {list(data['character'].keys())}")
            else:
                print(f"✅ {name}: Found {total_xp:,} XP (Level {char_obj.get('level')})")
                new_totals[name] = total_xp
                
        except Exception as e:
            print(f"❌ {name}: Connection failed ({e})")

    if new_totals:
        with open(TOTALS_PATH, "w") as f:
            json.dump(new_totals, f, indent=2)
        print(f"💾 SUCCESS: {len(new_totals)} characters saved to {TOTALS_PATH.name}")
    else:
        print("🛑 No data found. Nothing saved.")

if __name__ == "__main__":
    main()
