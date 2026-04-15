import json
import secrets
import string
import os
import sys
from datetime import datetime
from pathlib import Path

# Add the project root to sys.path to import local modules
sys.path.append(str(Path(__file__).parent.parent))

try:
    from school_admin.licensing.license_manager import LicenseManager
except ImportError:
    # If standard import fails, try relative or just define the helper
    print("Could not import LicenseManager, using manual GitHub update")

def load_env():
    env_file = Path(".env")
    if env_file.exists():
        with open(env_file, "r") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    key, value = line.strip().split("=", 1)
                    os.environ[key] = value

def generate_activation_key() -> str:
    alphabet = string.ascii_uppercase + "234567"
    random_chars = ''.join(secrets.choice(alphabet) for _ in range(16))
    return f"PINAKI-{random_chars[0:4]}-{random_chars[4:8]}-{random_chars[8:12]}-{random_chars[12:16]}"

def main():
    load_env()
    keys_file = Path("keys.json")
    if not keys_file.exists():
        print("Error: keys.json not found in current directory")
        return

    with open(keys_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    existing_keys = data.get("keys", {})
    new_keys_count = 500
    added = 0
    
    print(f"Generating {new_keys_count} keys...")
    
    new_batch = {}
    while added < new_keys_count:
        key = generate_activation_key()
        if key not in existing_keys:
            existing_keys[key] = {
                "username": None,
                "activation_date": None,
                "expiry_date": None,
                "machine_id": None,
                "status": "active"
            }
            new_batch[key] = existing_keys[key]
            added += 1

    data["keys"] = existing_keys
    data["updated_at"] = datetime.now().isoformat()
    
    with open(keys_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    
    print(f"Successfully added {added} new keys to keys.json locally.")

    # Optional: Sync to GitHub if token is available
    github_repo = os.getenv("GITHUB_LICENSE_REPO")
    github_token = os.getenv("GITHUB_LICENSE_TOKEN")
    
    if github_repo and github_token:
        print(f"Syncing to GitHub repo: {github_repo}...")
        try:
            from school_admin.licensing.license_manager import LicenseManager
            # Use dummy app data dir
            lm = LicenseManager(Path("."), github_repo, github_token)
            
            # Use internal methods to update GitHub
            doc = lm._get_github_keys_document()
            doc["data"]["keys"].update(existing_keys)
            doc["data"]["updated_at"] = data["updated_at"]
            
            lm._save_github_keys(
                doc["data"], 
                doc["sha"], 
                f"Batch generate {new_keys_count} new keys"
            )
            print("✓ Successfully synced to GitHub.")
        except Exception as e:
            print(f"Failed to sync to GitHub: {e}")
            print("Please push keys.json manually.")
    else:
        print("GitHub config not found in environment. Please push keys.json manually.")

if __name__ == "__main__":
    main()
