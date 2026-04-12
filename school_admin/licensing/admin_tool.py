"""
License Admin Tool - Manage activation keys (add, revoke, view)
RENEWAL MODEL: When a license expires (after 1 year), generate a NEW key and
send to the user. Users enter the new key to reactivate.
"""

from __future__ import annotations

import base64
import json
import sys
import urllib.request
from datetime import datetime, timedelta
from typing import Optional


def load_keys_from_github(
    repo: str,
    github_token: Optional[str] = None,
    raw_url: Optional[str] = None,
) -> dict:
    """Fetch keys.json from GitHub."""
    if raw_url:
        url = raw_url
    else:
        owner, name = repo.split("/", 1)
        url = f"https://api.github.com/repos/{owner}/{name}/contents/keys.json"

    try:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "Pinaki-License-Admin",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if github_token:
            prefix = "Bearer" if github_token.startswith("github_pat_") else "token"
            headers["Authorization"] = f"{prefix} {github_token}"

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))

        if raw_url:
            return payload

        content = base64.b64decode(payload["content"].replace("\n", "")).decode("utf-8")
        return json.loads(content)
    except Exception as exc:
        print(f"[X] Failed to load keys from GitHub: {exc}")
        sys.exit(1)


def save_keys_local(keys: dict, output_file: str = "keys.json") -> None:
    """Save keys to local file."""
    with open(output_file, "w", encoding="utf-8") as handle:
        json.dump(keys, handle, indent=2)
    print(f"[OK] Saved to {output_file}")
    print("\nNext steps:")
    print("  1. Review changes: git diff keys.json")
    print("  2. Commit: git add keys.json && git commit -m 'Updated licenses'")
    print("  3. Push: git push")


def add_new_keys(keys: dict, new_keys: list, expiry_days: int = 365) -> None:
    """Add new keys to database."""
    expiry_date = (datetime.now() + timedelta(days=expiry_days)).strftime("%Y-%m-%d")

    for key in new_keys:
        if key in keys["keys"]:
            print(f"[!] Key already exists: {key}")
            continue

        keys["keys"][key] = {
            "username": None,
            "activation_date": None,
            "expiry_date": expiry_date,
            "machine_id": None,
            "status": "active",
        }
        print(f"[OK] Added: {key}")

    keys["updated_at"] = datetime.now().isoformat()


def revoke_key(keys: dict, key: str) -> bool:
    """Revoke a license key."""
    if key not in keys["keys"]:
        print(f"[X] Key not found: {key}")
        return False

    keys["keys"][key]["status"] = "revoked"
    keys["updated_at"] = datetime.now().isoformat()
    print(f"[OK] Revoked: {key}")
    return True


def list_keys(keys: dict, status_filter: Optional[str] = None) -> None:
    """List all keys with their status."""
    print("\nActivation Keys:")
    print("=" * 80)

    count = 0
    for key, info in keys["keys"].items():
        if status_filter and info["status"] != status_filter:
            continue

        status_icon = "[OK]" if info["status"] == "active" else "[X]"
        username = info.get("username") or "[unused]"
        expiry = info.get("expiry_date", "unknown")

        print(f"{status_icon} {key:30} | User: {username:20} | Expires: {expiry}")
        count += 1

    print("=" * 80)
    print(f"Total: {count} keys")


def show_key_details(keys: dict, key: str) -> None:
    """Show detailed info about a key."""
    if key not in keys["keys"]:
        print(f"[X] Key not found: {key}")
        return

    info = keys["keys"][key]
    print(f"\n{key}")
    print(f"  Status: {info.get('status', 'unknown')}")
    print(f"  Username: {info.get('username') or '(not activated)'}")
    print(f"  Activation Date: {info.get('activation_date') or '(not activated)'}")
    print(f"  Expiry Date: {info.get('expiry_date', 'unknown')}")
    print(f"  Machine ID: {info.get('machine_id') or '(any machine)'}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Manage Pinaki license keys")
    parser.add_argument("--repo", help="GitHub repo (owner/repo)")
    parser.add_argument("--token", help="GitHub PAT token")
    parser.add_argument("--local", help="Load from local keys.json instead of GitHub")
    parser.add_argument("--output", default="keys.json", help="Output file for changes")

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    list_cmd = subparsers.add_parser("list", help="List all keys")
    list_cmd.add_argument("--status", choices=["active", "revoked"], help="Filter by status")

    add_cmd = subparsers.add_parser("add", help="Add new keys (for new users or renewals)")
    add_cmd.add_argument("keys", nargs="+", help="Key(s) to add")
    add_cmd.add_argument("--days", type=int, default=365, help="Validity in days (default: 365)")

    revoke_cmd = subparsers.add_parser("revoke", help="Revoke a key")
    revoke_cmd.add_argument("key", help="Key to revoke")

    details_cmd = subparsers.add_parser("details", help="Show key details")
    details_cmd.add_argument("key", help="Key to inspect")

    args = parser.parse_args()

    if args.local:
        print(f"Loading from {args.local}...")
        with open(args.local, encoding="utf-8") as handle:
            keys = json.load(handle)
    else:
        if not args.repo:
            print("[X] Must specify --repo or --local")
            sys.exit(1)
        print(f"Fetching from {args.repo}...")
        keys = load_keys_from_github(args.repo, args.token)

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
