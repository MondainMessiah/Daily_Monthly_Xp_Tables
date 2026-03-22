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
    
    print(f"📡 Found {len(chars)} characters. Fetching live totals from TibiaData...")
    new_totals = {}

    for name in chars:
        url = f"https://api.tibiadata.com/v4/character/{name.replace(' ', '%20')}"
        try:
            r = requests.get(url, timeout=10)
            data = r.json()
            # The exact path to experience in v4 API
            total_xp = data.get("character", {}).get("character", {}).get("experience", 0)
            
            if total_xp > 0:
                print(f"✅ {name}: Found {total_xp:,} XP")
                new_totals[name] = total_xp
            else:
                print(f"❓ {name}: API returned 0 XP (Check spelling in characters.txt!)")
        except Exception as e:
            print(f"❌ {name}: Failed to connect ({e})")

    if new_totals:
        with open(TOTALS_PATH, "w") as f:
            json.dump(new_totals, f, indent=2)
        print(f"💾 LOCAL SAVE SUCCESS: Found {len(new_totals)} characters.")
        print("⚠️ If xp_totals.json is still empty on GitHub after this, check your WORKFLOW PERMISSIONS!")
    else:
        print("🛑 No data was found. Nothing to save.")

if __name__ == "__main__":
    main()
