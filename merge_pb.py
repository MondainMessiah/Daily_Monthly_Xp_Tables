import json
import os

OLD_FILE = "best_daily_xp.json"
NEW_FILE = "personal_bests.json"

# Load old daily bests if they exist
if os.path.exists(OLD_FILE):
    with open(OLD_FILE, "r") as f:
        old_data = json.load(f)
else:
    old_data = {}
    print("Old file not found. Nothing to merge!")

# Create the new structure
new_structure = {
    "daily": old_data,   # Moves your old records here
    "weekly": {},        # Starts fresh for weekly
    "monthly": {}        # Starts fresh for monthly
}

# Save as the new filename
with open(NEW_FILE, "w") as f:
    json.dump(new_structure, f, indent=2)

print(f"Successfully merged {len(old_data)} records into {NEW_FILE}!")
