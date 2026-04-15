import json
import os
import sys
from pathlib import Path
from datetime import datetime

# Add the project root to sys.path to import local modules
sys.path.append(str(Path(__file__).parent.parent))

def load_env():
    env_file = Path(".env")
    if env_file.exists():
        with open(env_file, "r") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    parts = line.strip().split("=", 1)
                    if len(parts) == 2:
                        os.environ[parts[0]] = parts[1]

def main():
    load_env()
    keys_file = Path("keys.json")
    if not keys_file.exists():
        print("Error: keys.json not found locally.")
        return

    with open(keys_file, "r", encoding="utf-8") as f:
        local_data = json.load(f)

    github_repo = os.getenv("GITHUB_LICENSE_REPO")
    github_token = os.getenv("GITHUB_LICENSE_TOKEN")
    
    if not github_repo or not github_token:
        print("Error: GITHUB_LICENSE_REPO or GITHUB_LICENSE_TOKEN not found in .env")
        return

    print(f"Syncing local keys to GitHub: {github_repo}...")
    try:
        from school_admin.licensing.license_manager import LicenseManager
        # Use dummy app data dir
        lm = LicenseManager(Path("."), github_repo, github_token)
        
        # Fetch current GitHub doc
        doc = lm._get_github_keys_document()
        remote_data = doc["data"]
        remote_sha = doc["sha"]
        
        # Merge keys
        remote_keys = remote_data.setdefault("keys", {})
        local_keys = local_data.get("keys", {})
        
        count_before = len(remote_keys)
        remote_keys.update(local_keys)
        count_after = len(remote_keys)
        
        remote_data["updated_at"] = datetime.now().isoformat()
        
        if count_after > count_before:
            print(f"Adding {count_after - count_before} new keys to GitHub (Total: {count_after})")
            lm._save_github_keys(
                remote_data, 
                remote_sha, 
                f"Sync {count_after - count_before} new keys from local keys.json"
            )
            print("Success: Successfully synced to GitHub.")
        else:
            print("GitHub is already up to date with all local keys.")
            
    except Exception as e:
        print(f"Failed to sync to GitHub: {e}")

if __name__ == "__main__":
    main()
