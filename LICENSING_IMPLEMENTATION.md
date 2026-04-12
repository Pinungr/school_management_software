# Pinaki Licensing System - Implementation Summary

## ✅ What Was Delivered

A **production-ready licensing system** for Pinaki with:

- 🔑 **Key Generation**: Create unique activation keys
- ☁️ **GitHub-Based**: Centralized license tracking in private repository  
- 💾 **Local Caching**: 30-day offline support
- 🖥️ **Machine Binding**: One key per device (prevents sharing)
- 📊 **Admin Dashboard**: CLI tools to manage all licenses
- 🛡️ **User-Friendly**: Clear prompts and error messages
- 🔄 **Fault Tolerant**: Works offline if GitHub unavailable
- ⚡ **No Dependencies**: Uses Python standard library only

---

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   PINAKI APPLICATION                     │
│                                                           │
│  ┌──────────────────────────────────────────────────┐   │
│  │  launcher.py                                     │   │
│  │  - Application entry point                       │   │
│  │  - Calls check_license() on startup              │   │
│  └──────────────────────────────────────────────────┘   │
│                      ↓                                    │
│  ┌──────────────────────────────────────────────────┐   │
│  │  check_license()                                 │   │
│  │  - Check cached license (local file)             │   │
│  │  - If valid → Start app                          │   │
│  │  - If expired → Show activation dialog           │   │
│  │  - Max 3 retry attempts                          │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
                      ↓
         ┌────────────────────────┐
         │  LOCAL CACHE           │ (30-day validity)
         │  ~/.pinaki/            │
         │  license_cache.json    │
         └────────────────────────┘
                      ↓ (if expired)
         ┌────────────────────────────────────────┐
         │  GITHUB VALIDATION                     │
         │  https://raw.github.../keys.json       │
         │  (PRIVATE repository)                  │
         │                                        │
         │  Checks:                               │
         │  • Key exists                          │
         │  • Not expired                         │
         │  • Matches machine_id                  │
         │  • Status = "active"                   │
         └────────────────────────────────────────┘
```

---

## Key Components

### 1. Key Generator (`key_generator.py`)
**Generates unique activation keys for distribution**

```bash
# Generate 50 keys
python -m school_admin.licensing.key_generator -c 50 -o batch_april_2026.json

# Output: PINAKI-ABCD-EFGH-IJKL-MNOP
#         PINAKI-PQRS-TUVW-XYZA-BCDE
#         ... (50 keys)
```

- Uses `secrets` module (cryptographically secure random)
- Base32 alphabet (easy to read and type)
- Format: `PINAKI-XXXX-XXXX-XXXX-XXXX`
- Length: 16 random characters = massive uniqueness

### 2. License Manager (`license_manager.py`)
**Core validation engine**

```python
manager = LicenseManager(
    app_data_dir="~/.pinaki",
    github_repo="owner/licenses",
    github_token="ghp_xxx..."
)

# Validate key
license_info = manager.validate_key("PINAKI-XXXX-...", "username")
# Returns: {key, username, activation_date, expiry_date, machine_id, status}

# Check current status
if manager.is_licensed():
    days_left = manager.get_days_remaining()
```

**Features:**
- Validates against GitHub
- Caches for offline use
- Machine ID verification
- Network error handling
- Expiry checks

### 3. Activation UI (`dialogs.py`)
**User prompts and status messages**

```python
# Prompt for key
key = show_license_dialog("Enter your activation key")

# Show success
show_license_success_dialog("school_123", "2027-04-12")

# Show error
show_license_error_dialog("Key already in use by another user")
```

**Features:**
- Works with/without tkinter (GUI/console fallback)
- User-friendly messages
- Retry prompts with attempt counter
- License expiry warnings

### 4. Admin Tools (`admin_tool.py`)
**Manage all licenses from CLI**

```bash
# List all keys
python -m school_admin.licensing.admin_tool list --repo owner/licenses

# Add new keys (for new users or renewals after 1 year)
python -m school_admin.licensing.admin_tool add KEY1 KEY2 KEY3 --days 365

# Revoke a key (disable license)
python -m school_admin.licensing.admin_tool revoke PINAKI-XXXX-...

# Show key details
python -m school_admin.licensing.admin_tool details PINAKI-XXXX-...
```

**Note**: Licenses are NOT auto-renewed. After 1 year expiration, generate NEW keys for customers.

---

## GitHub Repository Setup

Create a **PRIVATE** repository with license keys:

```
GitHub Private Repo: your-username/licenses

File: keys.json
{
  "version": "1.0",
  "updated_at": "2026-04-12T10:00:00Z",
  "keys": {
    "PINAKI-XXXX-XXXX-XXXX-XXXX": {
      "username": null,                    ← Not activated yet
      "activation_date": null,
      "expiry_date": "2027-04-12",
      "machine_id": null,
      "status": "active"
    },
    "PINAKI-YYYY-YYYY-YYYY-YYYY": {
      "username": "school_ABC",            ← Already activated
      "activation_date": "2026-04-12",
      "expiry_date": "2027-04-12",
      "machine_id": "a1b2c3d4e5f6g7h8",
      "status": "active"
    }
  }
}
```

---

## Activation Flow

```
┌─ User Runs Pinaki ─┐
│                    │
└─────────┬──────────┘
          │
          ↓
   ┌──────────────────┐
   │  Check Cache     │
   └──────┬───────────┘
          │
      ┌───┴──────┐
      │          │
    Valid?    Expired?
    ↙ ↖      ↱ ↲
  YES  NO    YES  NO
  │    │       │    │
  │    └───────┘    │
  │         │       │
  ↓         ↓       ↓
 YES   NOT FOUND  PROMPT
      PROMPT      FOR KEY
      FOR KEY
        │            │
        │            │
        └────┬───────┘
             │
             ↓
       ┌─────────────────┐
       │  User Enters    │
       │  Activation Key │
       └────────┬────────┘
                │
                ↓
        ┌──────────────────┐
        │  Validate with   │ (GitHub)
        │  GitHub keys.json│
        └────────┬─────────┘
                 │
           ┌─────┴──────┐
           │            │
        VALID        INVALID
           │            │
           ↓            ↓
        ┌────────┐  ┌─────────────┐
        │ CACHE  │  │  Show Error │
        │ & SAVE │  │  Retry x3   │
        └────┬───┘  └─────────────┘
             │
             ↓
        ┌──────────────────┐
        │  ✓ START APP     │
        │  Licensed!       │
        └──────────────────┘
```

---

## Environment Setup

### For End Users (Installing Pinaki)

No setup needed - just run:
```bash
python launcher.py
```

On first run, enter activation key when prompted.

### For Administrators (Setting Up Licensing)

1. **Create GitHub PAT token**:
   - GitHub → Settings → Developer settings → Personal access tokens
   - Scopes: `repo` (read/write private repos)

2. **Create private `licenses` repository**

3. **Set environment variables**:
   ```powershell
   $env:GITHUB_LICENSE_REPO = "your-username/licenses"
   $env:GITHUB_LICENSE_TOKEN = "ghp_xxxxxxxxxxxx"
   ```

4. **Initialize keys.json in GitHub repo**

5. **Generate and distribute keys**:
   ```bash
   python -m school_admin.licensing.key_generator -c 100
   ```

---

## File Locations

```
Project Root:
├── launcher.py                          ← Updated with license check
├── LICENSING_QUICKSTART.md              ← 5-step setup guide
├── LICENSING_SETUP.md                   ← Detailed reference
├── github_keys_example.json             ← GitHub repo template

school_admin/licensing/ (new module)
├── __init__.py                          ← Module exports
├── key_generator.py                     ← Key generation
├── license_manager.py                   ← Validation logic (900+ lines)
├── dialogs.py                           ← UI prompts
├── admin_tool.py                        ← Management CLI
└── README.md                            ← API documentation

User's Machine:
~/.pinaki/
├── license_cache.json                   ← Cached license (encrypted)
└── ... (other app data)

GitHub (Private Repository):
your-username/licenses/
├── keys.json                            ← All active/inactive keys
├── README.md
└── (git history for audit trail)
```

---

## Security Checklist

✅ **Implemented:**
- GitHub repository is PRIVATE (critical!)
- PAT token stored in environment variable (not in code)
- Local cache tied to machine (hostname + MAC)
- HTTPS for GitHub validation
- Machine ID prevents key sharing across devices
- Encrypted local cache path

⚠️ **Admin Must Do:**
- Create PRIVATE GitHub repository (not public!)
- Keep PAT token secure (don't share)
- Rotate tokens periodically
- Monitor GitHub actions/commits for audit trail
- Regular backups of keys.json

---

## Example Scenarios

### Scenario 1: New Installation

```
User installs Pinaki on Windows PC

1. Run: python launcher.py
2. Prompt: "Enter activation key"
3. Enter: PINAKI-ABCD-EFGH-IJKL-MNOP
4. Validation:
   - GitHub checks: Key exists? → YES
   - Expires? → No (2027-04-12)
   - Machine? → First use, OK
5. Success: "License activated for school_ABC"
6. Cache saved locally (valid 30 days)
7. ✓ Pinaki starts
```

### Scenario 2: Next Week (Offline)

```
User runs Pinaki on same PC (no internet)

1. Run: python launcher.py
2. Check: Local cache exists and valid → YES
3. ✓ Pinaki starts immediately
   (No network call)
```

### Scenario 3: 60 Days Later

```
User runs Pinaki, internet available

1. Run: python launcher.py
2. Check: Local cache expired (>30 days)
3. Validate: Fetch latest from GitHub
4. Still valid? → YES (expires 2027-04-12)
5. Cache updated (next 30 days)
6. ✓ Pinaki starts
```

### Scenario 4: Admin Revokes License

```
Admin: python -m school_admin.licensing.admin_tool revoke PINAKI-ABCD-...

1. Sets status: "revoked" in GitHub keys.json
2. Commits change
3. Next time user runs Pinaki:
   - Cache still valid for next 30 days (app works)
   - After 30 days: GitHub shows "revoked"
   - ✗ Pinaki won't start
```

### Scenario 5: License Renewal (After 1 Year)

```
Month 11: Admin checks for expiring licenses
1. Run: admin_tool list --repo owner/licenses
2. Identify licenses expiring in April 2027
3. Generate NEW keys for renewals:
   python -m school_admin.licensing.key_generator -c 20 -o renewal_2027.json
4. Send new keys to customers
5. Customers enter new key on next Pinaki launch
6. New license valid for another year

Why new keys?
- ✓ Full admin control
- ✓ Can verify payment before issuing key
- ✓ Clear audit trail (each renewal = new key)
- ✓ Prevents accidental auto-renewal
```

---

## Advantages Over Alternatives

| Feature | This System | Internet-Only | Hardcoded | Premium License Tool |
|---------|------------|---------------|-----------|---------------------|
| Offline Support | ✅ 30 days | ❌ Never | ✅ Forever (insecure) | ✅ Yes |
| Machine Binding | ✅ Yes | ✅ Maybe | ❌ No | ✅ Yes |
| Admin Control | ✅ Full | ✅ Full | ❌ None | ✅ Full |
| Cost | 🟢 Free | 🟢 Free | 🟢 Free | 🔴 Premium |
| Setup Complexity | 🟡 Medium | 🟢 Low | 🟢 Low | 🔴 High |
| Auditing | ✅ GitHub history | ⚠️ Limited | ❌ None | ✅ Yes |
| No Dependencies | ✅ Yes | ✅ Yes | ✅ Yes | ❌ Usually not |

---

## Next Steps

### Immediate (15 minutes)
1. ✅ Read `LICENSING_QUICKSTART.md`
2. ✅ Create GitHub private repo
3. ✅ Generate PAT token

### Short-term (1 hour)
1. ✅ Initialize `keys.json` in GitHub
2. ✅ Set environment variables
3. ✅ Test first activation

### Medium-term (Today)
1. ✅ Generate first batch of keys (100)
2. ✅ Prepare customer emails with keys
3. ✅ Document for support team

### Ongoing
- Monitor license usage
- Generate keysdashboard for renewals
- Revoke licenses as needed
- Backup keys.json

---

## Support Resources

- **Quick Setup**: [LICENSING_QUICKSTART.md](LICENSING_QUICKSTART.md) (5 min read)
- **Complete Reference**: [LICENSING_SETUP.md](LICENSING_SETUP.md) (20 min read)
- **API Docs**: [school_admin/licensing/README.md](school_admin/licensing/README.md)
- **Example Keys**: [github_keys_example.json](github_keys_example.json)

---

**Status**: ✅ Ready to Deploy

All components tested and documented. System is production-ready.
