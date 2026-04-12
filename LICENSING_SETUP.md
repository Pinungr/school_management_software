# Pinaki License Keys Repository

This repository stores activation keys for Pinaki school management software. 

**⚠️ IMPORTANT: Keep this repository PRIVATE**

## Setup Instructions

### 1. Create a GitHub Repository

Create a new **PRIVATE** repository:
- **Name**: `licenses` (or any name, then update the `GITHUB_LICENSE_REPO` env var)
- **Owner**: Your GitHub account or organization
- **Privacy**: **PRIVATE** (must be private to protect license keys)

### 2. Create GitHub PAT Token

1. Go to GitHub Settings → Developer settings → Personal access tokens → Tokens (classic)
2. Click "Generate new token (classic)"
3. Set permissions: `repo` (full control of private repositories)
4. Copy the token and save it securely
5. Set as environment variable:
   ```bash
   $env:GITHUB_LICENSE_TOKEN = "ghp_xxxxxxxxxxxx..."
   ```

### 3. Initialize the Repository

Clone your new repository and add the initial keys file:

```bash
git clone https://github.com/YOUR_USERNAME/licenses.git
cd licenses
```

Add an initial `keys.json` file:

```json
{
  "version": "1.0",
  "updated_at": "2026-04-12T00:00:00Z",
  "keys": {}
}
```

```bash
git add keys.json
git commit -m "Initial commit: empty keys database"
git push
```

### 4. Generate Activation Keys

Run the key generator to create keys:

```python
from school_admin.licensing import generate_batch_keys

# Generate 10 keys
keys = generate_batch_keys(count=10, output_file="activation_keys.json")
```

### 5. Add Keys to Repository

The `keys.json` file structure:

```json
{
  "version": "1.0",
  "updated_at": "2026-04-12T12:30:45Z",
  "keys": {
    "PINAKI-ABCD-EFGH-IJKL-MNOP": {
      "username": null,
      "activation_date": null,
      "expiry_date": "2027-04-12",
      "machine_id": null,
      "status": "active"
    },
    "PINAKI-QRST-UVWX-YZAB-CDEF": {
      "username": "school_admin_01",
      "activation_date": "2026-04-12",
      "expiry_date": "2027-04-12",
      "machine_id": "machine-hash-abc123",
      "status": "active"
    }
  }
}
```

**Key fields:**
- `username`: User who activated this key (null = unactivated)
- `activation_date`: When key was first used
- `expiry_date`: When license expires
- `machine_id`: Device this key is tied to (null = any device)
- `status`: `"active"` or `"revoked"`

## Managing Keys

### Setting Up Your Application

Set environment variables before running Pinaki:

```powershell
# Windows PowerShell
$env:GITHUB_LICENSE_REPO = "your-username/licenses"
$env:GITHUB_LICENSE_TOKEN = "ghp_xxxxxxxxxxxx..."

# Then run Pinaki
python launcher.py
```

Or create a `.env` file in the project root (add to .gitignore):

```
GITHUB_LICENSE_REPO=your-username/licenses
GITHUB_LICENSE_TOKEN=ghp_xxxxxxxxxxxx...
```

### Creating New Keys

Use the Python script:

```bash
python -m school_admin.licensing.key_generator -c 5 -o new_keys.json
```

Then manually add them to `keys.json` and commit to GitHub.

### Revoking Keys

To revoke a key (disable a license):

```json
"PINAKI-XXXX-XXXX-XXXX-XXXX": {
  "username": "user_to_revoke",
  "activation_date": "2026-04-01",
  "expiry_date": "2027-04-01",
  "machine_id": "machine-id",
  "status": "revoked"  // <- Change this from "active" to "revoked"
}
```

### Renewing a License (After 1 Year Expires)

**Important**: Admin cannot extend licenses. When a license expires:

1. **Generate NEW keys** for renewal:
   ```bash
   python -m school_admin.licensing.key_generator -c 50 -o renewal_2027.json
   ```

2. **Send new keys** to customers (email/secure channel)

3. **Customers enter new key** on next Pinaki launch

4. New license is valid for another year

**Benefits of this approach:**
- ✅ Full admin control over renewals
- ✅ Can track who renewed vs. who didn't
- ✅ Can require payment before issuing renewal key
- ✅ Clear audit trail (each renewal = new key entry)
- ✅ Prevents accidental auto-renewal

**You cannot:**
- ❌ Edit expiry_date directly
- ❌ Extend existing keys
- ❌ Auto-renew licenses

Each year = new key required

## How It Works

1. **User installs Pinaki** → Application starts
2. **License check** → Launcher checks if application has valid cached license
3. **If no license** → Prompts user to enter activation key
4. **Validation** → Key is validated against `keys.json` on GitHub:
   - Checks if key exists
   - Verifies expiry date hasn't passed
   - Checks if key is not already used by different user/machine
5. **On success** → Stores encrypted license in local cache (valid for 30 days)
6. **On failure** → Shows error, allows retry (3 attempts max)

## Security Notes

- ✅ Keys are validated over HTTPS from GitHub
- ✅ Local cache is stored (allows offline activation after first auth)
- ✅ Machine ID prevents key sharing across devices
- ✅ Private repository prevents unauthorized key scanning
- ✅ GitHub PAT token kept in environment variable (not in code)
- ⚠️ Each key can be used on ONE machine only
- ⚠️ Reusable across app starts (once activated on a machine, no internet needed for 30 days)

## Troubleshooting

### "Key not found" error
- Check the key format: `PINAKI-XXXX-XXXX-XXXX-XXXX`
- Verify key exists in GitHub `keys.json`
- Make sure key status is `"active"`

### "Key expired" error
- License is no longer valid
- Admin must generate a NEW key for renewal
- Send new key to customer
- Customer enters new key to reactivate

### "Key already in use" error
- This key is assigned to different username/machine
- Generate a new key or revoke the old one

### Connection error, but cached license works
- This is expected! The app uses the 30-day cache if GitHub is unreachable
- Cache automatically refreshes on next successful connection

## API Reference

### LicenseManager Class

```python
from school_admin.licensing import LicenseManager
from pathlib import Path

# Initialize
manager = LicenseManager(
    app_data_dir=Path("./data"),
    github_repo="your-username/licenses",
    github_token="ghp_xxx...",  # Optional, reads from env if omitted
    cache_days=30  # Cache validity period
)

# Validate a key
try:
    license_info = manager.validate_key("PINAKI-XXXX-XXXX-XXXX-XXXX", "username")
    print(f"Valid until: {license_info['expiry_date']}")
except LicenseInvalidError as e:
    print(f"Invalid: {e}")
except LicenseExpiredError as e:
    print(f"Expired: {e}")
except LicenseNetworkError as e:
    print(f"Network error: {e}")

# Check license status (uses cache only, no network)
if manager.is_licensed():
    days = manager.get_days_remaining()
    print(f"Licensed for {days} more days")
```

## Distribution

When distributing keys to users:

1. Generate keys using the key_generator script
2. Send each key via email or secure channel
3. Provide activation instructions (enter key on first launch)
4. Each key is single-use per machine

Example customer email:

```
Subject: Your Pinaki Activation Key

Hi there!

Your Pinaki activation key is:
PINAKI-ABCD-EFGH-IJKL-MNOP

For setup:
1. Install Pinaki
2. Run the application
3. When prompted, enter your activation key
4. License will be valid for one year

Support: admin@example.com
```

---

**Repository**: Should be PRIVATE and only accessible to authorized administrators
**Commit policy**: Every key change should be committed with clear messages
**Backup**: Regularly backup this repository (contains all license data)
