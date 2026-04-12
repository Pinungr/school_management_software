# Pinaki Licensing System - Quick Start Guide

## Overview

Your Pinaki application now has a complete licensing system that:
- ✅ Generates unique activation keys
- ✅ Validates keys against a GitHub repository
- ✅ Caches licenses locally for offline use (30 days)
- ✅ Ties licenses to individual machines
- ✅ Requires new keys for annual renewals (admin controlled)
- ✅ Handles network errors gracefully

## 5-Step Setup

### Step 1: Create GitHub Private Repository

1. Go to [GitHub](https://github.com/new)
2. Create new repository:
   - **Name**: `licenses`
   - **Privacy**: **PRIVATE** (critical!)
   - **Add**: Add a README.md

### Step 2: Create GitHub Personal Access Token (PAT)

1. Go to GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
2. Click **"Generate new token"**
   - Name: `Pinaki License Manager`
   - Scopes: Select `repo` (read/write all repos)
   - Expiry: 1 year or No expiration
3. **Copy the token immediately** (you won't see it again)

### Step 3: Initialize Keys File in GitHub Repo

1. Clone your new repo:
   ```bash
   git clone https://github.com/YOUR_USERNAME/licenses.git
   cd licenses
   ```

2. Create `keys.json` (use the example below):
   ```json
   {
     "version": "1.0",
     "updated_at": "2026-04-12T00:00:00Z",
     "keys": {}
   }
   ```

3. Push to GitHub:
   ```bash
   git add keys.json
   git commit -m "Initialize license keys database"
   git push
   ```

### Step 4: Generate First Batch of Keys

```bash
# Generate 10 keys
python -m school_admin.licensing.key_generator -c 10 -o activation_keys.json
```

### Step 5: Run Pinaki with License Check

Set environment variables, then run:

```powershell
# Windows PowerShell
$env:GITHUB_LICENSE_REPO = "your-username/licenses"
$env:GITHUB_LICENSE_TOKEN = "ghp_xxxxxxxxxxxxxxxxxxxx"

python launcher.py
```

**On first run**: You'll be prompted to enter an activation key from the generated batch.

---

## Usage

### For End Users (Installing Pinaki)

1. **First Launch**: Application asks for activation key
2. **Enter Key**: Copy key and paste it in the prompt
3. **Success**: License activated for 1 year, cached locally
4. **Works Offline**: Doesn't need internet after first activation (cached for 30 days)

### For Administrators (Managing Keys)

#### Generate Keys for Distribution

```bash
python -m school_admin.licensing.key_generator -c 50 -o batch_2026_april.json
```

Then manually add them to GitHub `keys.json`:

```json
"PINAKI-NEWK-EY01-2345-6789": {
  "username": null,
  "activation_date": null,
  "expiry_date": "2027-04-12",
  "machine_id": null,
  "status": "active"
}
```

#### Check All Keys

```bash
python -m school_admin.licensing.admin_tool list --repo your-username/licenses --token ghp_xxx
```

#### Revoke a License (Disable User)

```bash
python -m school_admin.licensing.admin_tool revoke PINAKI-XXXX-XXXX-XXXX-XXXX \
  --repo your-username/licenses --token ghp_xxx
```

---

## Renewal Process

**When a license expires (after 1 year):**

1. Admin checks expiry dates in GitHub
2. Admin **generates NEW keys** for customers renewing
3. Admin sends new keys to customers
4. Customers enter the new key in Pinaki (same activation process)
5. New license valid for another year

**Why this model:**
- ✅ Full admin control
- ✅ Clear audit trail (each renewal is a new key)
- ✅ Can track who renewed
- ✅ Prevent automatic extensions
- ✅ Can require payment for renewal

**To renew a license:**
```bash
# 1. Generate new keys for renewal
python -m school_admin.licensing.key_generator -c 10 -o renewal_batch_2027.json

# 2. Add them to GitHub (same process as initial setup)

# 3. Send new keys to customers
# 4. Customers enter new key to reactivate
```

---

## File Structure

```
school_admin/licensing/
├── __init__.py                 # Module exports
├── key_generator.py            # Generate new keys
├── license_manager.py          # Core validation logic
├── admin_tool.py              # Manage keys from CLI
└── dialogs.py                 # UI dialogs for activation
```

## Architecture

```
┌─────────────────┐
│  Pinaki App     │
│  (launcher.py)  │
└────────┬────────┘
         │ check_license()
         ↓
┌─────────────────┐
│ LicenseManager  │
└────────┬────────┘
         │
    ┌────┴─────────┐
    ↓              ↓
 Local Cache    GitHub
(30 days)    (keys.json)
   ~/.pinaki/    (Private Repo)
 license_    
 cache.json
```

## Key Generation Format

Keys are in format: `PINAKI-XXXX-XXXX-XXXX-XXXX`

- **Easy to read**: Uses uppercase letters and numbers
- **Base32**: Avoids confusing characters (0, O, 1, I, L, l)
- **Unique**: 16 random characters = 36^16 combinations
- **Secure**: Generated using `secrets` module (cryptographically secure)

## Machine Binding

Each key is tied to a single machine using:
- `hostname`
- `MAC address`
- SHA256 hashed to 16 characters

**Result**: Strong identity without collecting personal data

## Offline Support

After first activation, the app works offline for **30 days**:

1. License cached in local file: `~/.pinaki/license_cache.json`
2. Cache encrypted and tied to machine
3. Auto-refreshes when internet available
4. After 30 days, needs internet to re-verify

## Security Best Practices

✅ **DO:**
- Keep GitHub repo **PRIVATE**
- Store PAT token in environment variables only
- Rotate PAT tokens periodically
- Commit all key changes to GitHub (audit trail)
- Regular backups of keys.json

❌ **DON'T:**
- Commit PAT token to code repository
- Share PAT tokens via email
- Make license repo public
- Hardcode keys in application
- Use old/weak GitHub tokens

---

## Error Handling

| Error | Cause | Solution |
|-------|-------|----------|
| "Key not found" | Invalid key | User enters wrong key (check format) |
| "Key already in use by..." | Key registered to different user | Generate new key or unregister old user |
| "License expired" | Expiry date passed | Renew key in GitHub |
| "Key tied to different machine" | Key was activated elsewhere | Use new key or unregister old machine |
| "Could not connect to GitHub" | No internet | Works with cached license |

---

## Example Workflow

### January 2026: Setup

1. Create GitHub `licenses` repo
2. Generate 100 activation keys
3. Distribute to schools via email

### April 2026: Monitor

```bash
# Check license status
python -m school_admin.licensing.admin_tool list --repo your/licenses --token ghp_xxx
# Output shows: 87 active, 13 not yet used
```

### March 2027: Renewals

```bash
# Extend licenses that are about to expire
python -m school_admin.licensing.admin_tool renew PINAKI-XXXX-... --days 365
```

### Invalid User: Revoke

```bash
# Disable a school's license
python -m school_admin.licensing.admin_tool revoke PINAKI-XXXX-...
```

---

## Requirements

Make sure these are in `requirements.txt`:

```
requests  # For GitHub API (optional, uses standard urllib)
```

No additional dependencies needed! Uses only Python stdlib.

---

## Testing

Test the licensing system without GitHub:

```bash
# Generate test keys
python -m school_admin.licensing.key_generator -c 5

# Test with SCHOOLFLOW_SMOKE_TEST bypass
export SCHOOLFLOW_SMOKE_TEST=1
python launcher.py
# License check skipped in smoke test mode
```

---

## Next Steps

1. ✅ Set up GitHub private repository
2. ✅ Create PAT token and save it
3. ✅ Initialize keys.json in repo
4. ✅ Generate first batch of keys
5. ✅ Test with `python launcher.py`
6. ✅ Distribute keys to users/customers
7. ✅ Monitor usage with admin tool
8. ✅ Renew licenses on demand

**Questions?** See [LICENSING_SETUP.md](LICENSING_SETUP.md) for detailed documentation.
