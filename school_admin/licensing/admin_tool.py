"""
License Admin Tool - Manage activation keys (add, revoke, view)
RENEWAL MODEL: When a license expires (after 1 year), generate a NEW key and send to user.
Users enter the new key to reactivate. Admin cannot extend existing keys.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import urllib.request


def load_keys_from_github(
    repo: str,
    github_token: Optional[str] = None,
    raw_url: Optional[str] = None
) -> dict:
    """Fetch keys.json from GitHub"""
    url = raw_url or f"https://raw.githubusercontent.com/{repo}/main/keys.json"
    
    try:
        headers = {'Accept': 'application/vnd.github.v3.raw'}
        if github_token:
            prefix = "Bearer" if github_token.startswith("github_pat_") else "token"
            headers['Authorization'] = f'{prefix} {github_token}'
        
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"✗ Failed to load keys from GitHub: {e}")
        sys.exit(1)


def save_keys_local(keys: dict, output_file: str = "keys.json") -> None:
    """Save keys to local file"""
    with open(output_file, 'w') as f:
        json.dump(keys, f, indent=2)
    print(f"✓ Saved to {output_file}")
    print("\nNext steps:")
    print("  1. Review changes: git diff keys.json")
    print("  2. Commit: git add keys.json && git commit -m 'Updated licenses'")
    print("  3. Push: git push")


def add_new_keys(
    keys: dict,
    new_keys: list,
    expiry_days: int = 365
) -> None:
    """Add new keys to database"""
    expiry_date = (datetime.now() + timedelta(days=expiry_days)).strftime('%Y-%m-%d')
    
    for key in new_keys:
        if key in keys['keys']:
            print(f"⚠ Key already exists: {key}")
            continue
        
        keys['keys'][key] = {
            "username": None,
            "activation_date": None,
            "expiry_date": expiry_date,
            "machine_id": None,
            "status": "active"
        }
        print(f"✓ Added: {key}")
    
    keys['updated_at'] = datetime.now().isoformat()


def revoke_key(keys: dict, key: str) -> bool:
    """Revoke a license key"""
    if key not in keys['keys']:
        print(f"✗ Key not found: {key}")
        return False
    
    keys['keys'][key]['status'] = 'revoked'
    keys['updated_at'] = datetime.now().isoformat()
    print(f"✓ Revoked: {key}")
    return True



def list_keys(keys: dict, status_filter: Optional[str] = None) -> None:
    """List all keys with their status"""
    print("\nActivation Keys:")
    print("=" * 80)
    
    count = 0
    for key, info in keys['keys'].items():
        if status_filter and info['status'] != status_filter:
            continue
        
        status_icon = "✓" if info['status'] == 'active' else "✗"
        username = info.get('username') or "[unused]"
        expiry = info.get('expiry_date', 'unknown')
        
        print(f"{status_icon} {key:30} | User: {username:20} | Expires: {expiry}")
        count += 1
    
    print("=" * 80)
    print(f"Total: {count} keys")


def show_key_details(keys: dict, key: str) -> None:
    """Show detailed info about a key"""
    if key not in keys['keys']:
        print(f"✗ Key not found: {key}")
        return
    
    info = keys['keys'][key]
    print(f"\n{key}")
    print(f"  Status: {info.get('status', 'unknown')}")
    print(f"  Username: {info.get('username') or '(not activated)'}")
    print(f"  Activation Date: {info.get('activation_date') or '(not activated)'}")
    print(f"  Expiry Date: {info.get('expiry_date', 'unknown')}")
    print(f"  Machine ID: {info.get('machine_id') or '(any machine)'}")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Manage Pinaki license keys")
    parser.add_argument("--repo", help="GitHub repo (owner/repo)")
    parser.add_argument("--token", help="GitHub PAT token")
    parser.add_argument("--local", help="Load from local keys.json instead of GitHub")
    parser.add_argument("--output", default="keys.json", help="Output file for changes")
    
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # List command
    list_cmd = subparsers.add_parser("list", help="List all keys")
    list_cmd.add_argument("--status", choices=["active", "revoked"], help="Filter by status")
    
    # Add command
    add_cmd = subparsers.add_parser("add", help="Add new keys (for new users or renewals)")
    add_cmd.add_argument("keys", nargs="+", help="Key(s) to add")
    add_cmd.add_argument("--days", type=int, default=365, help="Validity in days (default: 365)")
    
    # Revoke command
    revoke_cmd = subparsers.add_parser("revoke", help="Revoke a key")
    revoke_cmd.add_argument("key", help="Key to revoke")
    

    
    # Details command
    details_cmd = subparsers.add_parser("details", help="Show key details")
    details_cmd.add_argument("key", help="Key to inspect")
    
    args = parser.parse_args()
    
    # Load keys
    if args.local:
        print(f"Loading from {args.local}...")
        with open(args.local) as f:
            keys = json.load(f)
    else:
        if not args.repo:
            print("✗ Must specify --repo or --local")
            sys.exit(1)
        print(f"Fetching from {args.repo}...")
        keys = load_keys_from_github(args.repo, args.token)
    
    # Execute command
    if args.command == "list":
        list_keys(keys, args.status)
    
    elif args.command == "add":
        add_new_keys(keys, args.keys, args.days)
        save_keys_local(keys, args.output)
    
    elif args.command == "revoke":
        revoke_key(keys, args.key)
        save_keys_local(keys, args.output)
    
    elif args.command == "details":
        show_key_details(keys, args.key)
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
