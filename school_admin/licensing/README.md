# Pinaki Licensing Module

Complete licensing system for Pinaki school management software with:
- **Key Generation**: Create unique activation keys
- **Validation**: Verify keys against GitHub repository
- **Caching**: 30-day offline support
- **Machine Binding**: One key per device
- **Management**: Admin tools to manage licenses

## Quick Start

### For Users

1. **First Run**: 
   ```
   $ python launcher.py
   → "Enter activation key (Attempt 1/3)"
   → Type: PINAKI-XXXX-XXXX-XXXX-XXXX
   ```

2. **Success**: Licensed for 1 year, cached locally

3. **Offline**: Works without internet (cached validation for 30 days)

### For Admins

#### Generate Keys
```bash
python -m school_admin.licensing.key_generator -c 100 -o new_keys.json
```

#### Manage Keys
```bash
# List all keys
python -m school_admin.licensing.admin_tool list --repo owner/licenses

# Add new keys to GitHub
python -m school_admin.licensing.admin_tool add KEY1 KEY2 KEY3 --repo owner/licenses

# Revoke a license
python -m school_admin.licensing.admin_tool revoke PINAKI-XXXX-XXXX-XXXX-XXXX

# Renew/extend license
python -m school_admin.licensing.admin_tool renew PINAKI-XXXX-XXXX-XXXX-XXXX --days 365
```

## Modules

### `key_generator.py`
Generates unique activation keys for distribution.

```python
from school_admin.licensing import generate_batch_keys

# Generate 10 keys
keys = generate_batch_keys(count=10, output_file="my_keys.json")
```

### `license_manager.py`
Core licensing logic - validates keys against GitHub and manages local cache.

```python
from school_admin.licensing import LicenseManager, LicenseInvalidError

manager = LicenseManager(
    app_data_dir="/path/to/cache",
    github_repo="owner/licenses",
    github_token="ghp_xxxxx"  # Optional, reads from env
)

try:
    license_info = manager.validate_key("PINAKI-XXXX-...", "username")
    print(f"Licensed until: {license_info['expiry_date']}")
except LicenseInvalidError as e:
    print(f"Invalid key: {e}")
```

### `dialogs.py`
User interface for activation prompts and status messages.

```python
from school_admin.licensing.dialogs import show_license_dialog, show_license_success_dialog

key = show_license_dialog("Enter your key")
if key:
    show_license_success_dialog("user", "2027-04-12")
```

### `admin_tool.py`
Command-line interface for license administration.

```bash
python -m school_admin.licensing.admin_tool --help
```

## GitHub Repository Setup

Create a **PRIVATE** GitHub repository to store license keys:

```json
{
  "version": "1.0",
  "updated_at": "2026-04-12T00:00:00Z",
  "keys": {
    "PINAKI-XXXX-XXXX-XXXX-XXXX": {
      "username": "school_name",
      "activation_date": "2026-04-12",
      "expiry_date": "2027-04-12",
      "machine_id": "device-hash-abc123",
      "status": "active"
    }
  }
}
```

## Environment Variables

```bash
# GitHub repository (format: owner/repo)
export GITHUB_LICENSE_REPO="your-username/licenses"

# GitHub Personal Access Token (keep secure!)
export GITHUB_LICENSE_TOKEN="ghp_xxxxxxxxxxxxxxxxxxxx"

# Skip license check in testing
export SCHOOLFLOW_SMOKE_TEST=1
```

## Exception Handling

```python
from school_admin.licensing import (
    LicenseInvalidError,      # Key not found/already used
    LicenseExpiredError,      # License expired
    LicenseMachineError,      # Different machine
    LicenseNetworkError,      # GitHub connection failed
)
```

## API Reference

### LicenseManager

#### `__init__(app_data_dir, github_repo, github_token, cache_days)`
Initialize license manager.

#### `validate_key(key, username)` → LicenseInfo
Validate an activation key against GitHub. Returns license info or raises exception.

#### `is_licensed()` → bool
Check if current machine has valid cached license (no network call).

#### `get_license_status()` → LicenseInfo | None
Get cached license info without validation.

#### `get_days_remaining()` → int | None
Days until current license expires.

#### `get_machine_id()` → str
Get unique identifier for this machine.

## Cache Format

Local cache stored in `{APP_DATA_DIR}/license_cache.json`:

```json
{
  "key": "PINAKI-XXXX-XXXX-XXXX-XXXX",
  "username": "user_name",
  "activation_date": "2026-04-12T10:30:45",
  "expiry_date": "2027-04-12",
  "machine_id": "a1b2c3d4e5f6g7h8",
  "status": "active",
  "cached_at": "2026-04-12T10:35:20"
}
```

**Cache validity**: 30 days (configurable), then re-validates with GitHub.

## Key Format

Keys use Base32 encoding for readability:
- Format: `PINAKI-XXXX-XXXX-XXXX-XXXX`
- Alphabet: A-Z, 2-7 (avoids confusing 0/O, 1/I/L)
- Length: 16 random characters
- Uniqueness: 36^16 ≈ 4.7 × 10^24 combinations

## Machine Identification

Machine ID generated from:
1. Hostname
2. MAC address (primary network interface)
3. SHA256 hashed to 16 characters

Result: Unique, consistent identifier without personal data collection.

## Offline Support

1. First activation: Key validated with GitHub, cached locally
2. Next 30 days: Works offline using cache
3. After 30 days: Requires internet to re-validate cache
4. Network error: Falls back to cache if available

## Workflow

```
┌─────────────────────┐
│  User runs Pinaki   │
└──────────┬──────────┘
           │
           ↓
┌──────────────────────────┐
│  Check cached license    │
│  (local file)            │
└──────────┬─────────────────
           │
      ┌────┴─────────┐
      │              │
   Valid?        No
      │              │
    YES           ┌──┴──────────────────┐
      │           │                     │
      ↓           ↓                     ↓
   ✓ Start   Prompt for key    Validation Failed
      app    (3 attempts)       → Exit app
                │
           ┌────┴─────────┐
           │              │
        Valid?        No
           │              │
         YES           Retry
           │           (max 3)
           ↓              │
        ✓ Start      └─────→ Exit app
        Cache &
        Start app
```

## Testing

```python
# Mock validation (no GitHub needed)
from unittest.mock import patch

def test_license():
    with patch('school_admin.licensing.LicenseManager._get_github_keys'):
        manager = LicenseManager(...)
        # Test without network calls
```

## Troubleshooting

### "Connection refused" / GitHub error
- Check `GITHUB_LICENSE_REPO` format: `owner/repo`
- Verify `GITHUB_LICENSE_TOKEN` is valid
- Ensure repo is accessible and contains `keys.json`

### "Key not found"
- Verify key format: `PINAKI-XXXX-XXXX-XXXX-XXXX`
- Check key exists in GitHub `keys.json`
- Verify key status is `"active"` (not `"revoked"`)

### "Key already in use"
- Key is assigned to different username/machine
- Revoke the old key or unregister the user
- Generate a new key for this installation

### "License expired"
- Check expiry_date in GitHub keys.json
- Renew the license
- Admin: `python -m school_admin.licensing.admin_tool renew KEY`

## Security Considerations

✅ **Implemented:**
- GitHub token kept in environment variable
- License tied to machine (prevents sharing)
- Cache is local to machine
- Validation over HTTPS
- PAT tokens use least-privilege scope

⚠️ **Considerations:**
- GitHub repo must be PRIVATE
- Don't commit PAT to code repository
- Rotate tokens periodically
- Monitor for unusual key usage patterns

## Limitations

- One key per machine (not transferable)
- Requires GitHub account to manage licenses
- Internet required for initial setup and renewals
- Cache expires after 30 days of no internet

## Future Enhancements

- [ ] Web dashboard for key management
- [ ] Email notifications for expiring licenses
- [ ] Bulk license generation interface
- [ ] License analytics/usage tracking
- [ ] Self-service renewal portal
- [ ] Multiple keys per machine

---

See **LICENSING_SETUP.md** and **LICENSING_QUICKSTART.md** for complete setup instructions.
