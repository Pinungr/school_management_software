"""
License Manager - Handles key validation, activation, and caching
Manages licensing checks at application startup and runtime
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, TypedDict
import uuid
import socket
import re

logger = logging.getLogger(__name__)


class LicenseInfo(TypedDict, total=False):
    """License information structure"""
    key: str
    username: str
    activation_date: str
    expiry_date: str
    machine_id: str
    status: str
    cached_at: str


class LicenseError(Exception):
    """Base license error"""
    pass


class LicenseExpiredError(LicenseError):
    """License has expired"""
    pass


class LicenseInvalidError(LicenseError):
    """License key is invalid or not found"""
    pass


class LicenseMachineError(LicenseError):
    """License is tied to a different machine"""
    pass


class LicenseNetworkError(LicenseError):
    """Network error during license verification"""
    pass


def get_machine_id() -> str:
    """
    Generate a unique machine identifier
    Uses hostname + first MAC address for consistency
    """
    try:
        # Get hostname
        hostname = socket.gethostname()
        
        # Try to get MAC address - more unique than just hostname
        mac = None
        if os.name == 'nt':  # Windows
            try:
                import uuid as uuid_module
                mac = ':'.join(re.findall('..', '%012x' % uuid_module.getnode()))
            except Exception:
                pass
        
        # Combine for uniqueness
        machine_str = f"{hostname}:{mac or 'unknown'}"
        
        # Hash to a consistent length
        return hashlib.sha256(machine_str.encode()).hexdigest()[:16]
    except Exception as e:
        logger.warning(f"Could not generate machine ID: {e}")
        return "unknown"


class LicenseManager:
    """Manages license key validation and caching"""
    
    def __init__(
        self,
        app_data_dir: Path,
        github_repo: str = "pinaki-school/licenses",
        github_token: Optional[str] = None,
        cache_days: int = 30
    ):
        """
        Initialize License Manager
        
        Args:
            app_data_dir: Directory for local cache storage
            github_repo: GitHub repo in format 'owner/repo'
            github_token: GitHub PAT token (from env var GITHUB_LICENSE_TOKEN if not provided)
            cache_days: Days to cache license validation (default: 30)
        """
        self.app_data_dir = Path(app_data_dir)
        self.app_data_dir.mkdir(parents=True, exist_ok=True)
        
        self.github_repo = github_repo
        self.github_token = github_token or os.getenv("GITHUB_LICENSE_TOKEN")
        self.cache_days = cache_days
        
        self.cache_file = self.app_data_dir / "license_cache.json"
        self.github_keys_url = (
            f"https://raw.githubusercontent.com/{github_repo}/main/keys.json"
        )
        
        self.machine_id = get_machine_id()
    
    def _get_github_keys(self) -> dict:
        """
        Fetch keys from GitHub repository
        
        Returns:
            Dictionary with keys data
            
        Raises:
            LicenseNetworkError: If unable to fetch or parse
        """
        try:
            headers = {
                'Accept': 'application/vnd.github.v3.raw',
            }
            if self.github_token:
                headers['Authorization'] = f'token {self.github_token}'
            
            req = urllib.request.Request(self.github_keys_url, headers=headers)
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode('utf-8'))
                return data
        except (urllib.error.URLError, urllib.error.HTTPError, socket.timeout) as e:
            logger.error(f"Failed to fetch keys from GitHub: {e}")
            raise LicenseNetworkError(f"Could not connect to GitHub: {str(e)}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid GitHub keys format: {e}")
            raise LicenseNetworkError(f"Invalid license data format: {str(e)}")
    
    def _load_cache(self) -> Optional[LicenseInfo]:
        """Load cached license info"""
        if not self.cache_file.exists():
            return None
        
        try:
            with open(self.cache_file, 'r') as f:
                cache_data = json.load(f)
            
            # Check if cache is still valid
            cached_at = datetime.fromisoformat(cache_data.get('cached_at'))
            if (datetime.now() - cached_at).days <= self.cache_days:
                logger.debug("Using cached license info")
                return cache_data
            
            logger.debug("Cache expired, will validate with GitHub")
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Could not load cache: {e}")
        
        return None
    
    def _save_cache(self, license_info: LicenseInfo) -> None:
        """Save license info to cache"""
        license_info['cached_at'] = datetime.now().isoformat()
        try:
            with open(self.cache_file, 'w') as f:
                json.dump(license_info, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save license cache: {e}")
    
    def validate_key(
        self,
        key: str,
        username: str = "Unknown"
    ) -> LicenseInfo:
        """
        Validate an activation key
        
        Args:
            key: Activation key to validate
            username: Username for this activation
            
        Returns:
            LicenseInfo dictionary with license details
            
        Raises:
            LicenseInvalidError: Key is invalid or already used by another user
            LicenseExpiredError: Key has expired
            LicenseMachineError: Key is tied to a different machine
            LicenseNetworkError: Network error during validation
        """
        key = key.strip().upper()
        
        # First, try cached validation
        cached = self._load_cache()
        if cached and cached.get('key') == key:
            logger.info("License validated against cache")
            
            # Check expiry
            expiry = datetime.fromisoformat(cached['expiry_date'])
            if datetime.now() > expiry:
                raise LicenseExpiredError(
                    f"License expired on {expiry.strftime('%Y-%m-%d')}"
                )
            
            # Check machine match
            if cached.get('machine_id') != self.machine_id:
                cached_machine = cached.get('machine_id', 'unknown')
                raise LicenseMachineError(
                    f"License is tied to a different machine "
                    f"({cached_machine}). Current: {self.machine_id}"
                )
            
            return cached
        
        # Fetch latest from GitHub
        logger.info(f"Validating license key with GitHub...")
        try:
            github_data = self._get_github_keys()
        except LicenseNetworkError as e:
            # If we have a cache, use it as fallback
            if cached and cached.get('key') == key:
                logger.warning(f"Network error, using cached license: {e}")
                return cached
            raise
        
        # Look up key in GitHub data
        keys_db = github_data.get('keys', {})
        if key not in keys_db:
            raise LicenseInvalidError(f"Activation key '{key}' not found")
        
        key_info = keys_db[key]
        
        # Check status
        if key_info.get('status') != 'active':
            raise LicenseInvalidError(
                f"Activation key is {key_info.get('status', 'invalid')}"
            )
        
        # Check if key is already in use by different user/machine
        assigned_user = key_info.get('username')
        assigned_machine = key_info.get('machine_id')
        
        if assigned_user and assigned_user != username:
            raise LicenseInvalidError(
                f"Activation key is already in use by '{assigned_user}'"
            )
        
        if assigned_machine and assigned_machine != self.machine_id:
            raise LicendeMachineError(
                f"Activation key is tied to a different machine"
            )
        
        # Calculate expiry date
        # If this key was already activated before, use the original activation date
        # Otherwise, this is first activation - set expiry to 1 year from now
        if key_info.get('activation_date'):
            # Already activated - use same dates
            activation_date = key_info.get('activation_date')
            expiry_date_str = key_info.get('expiry_date')
            logger.info(f"Key previously activated on {activation_date}")
        else:
            # First activation - set to 1 year from now
            activation_date = datetime.now().isoformat()
            activation_date_obj = datetime.now()
            expiry_date_obj = activation_date_obj + timedelta(days=365)
            expiry_date_str = expiry_date_obj.strftime('%Y-%m-%d')
            logger.info(f"Key first activation - expires {expiry_date_str}")
        
        # Valid! Create license info
        # Expiry is 1 year from ACTIVATION DATE (not from key generation)
        license_info: LicenseInfo = {
            'key': key,
            'username': username,
            'activation_date': activation_date,
            'expiry_date': expiry_date_str,
            'machine_id': self.machine_id,
            'status': 'active',
        }
        
        # Cache for offline use
        self._save_cache(license_info)
        
        logger.info(f"License validated successfully for '{username}'")
        return license_info
    
    def get_license_status(self) -> Optional[LicenseInfo]:
        """Get current license status from cache (no network calls)"""
        return self._load_cache()
    
    def is_licensed(self) -> bool:
        """Check if application is currently licensed (using cache only)"""
        try:
            cached = self._load_cache()
            if not cached:
                return False
            
            expiry = datetime.fromisoformat(cached['expiry_date'])
            return datetime.now() <= expiry
        except Exception:
            return False
    
    def get_days_remaining(self) -> Optional[int]:
        """Get days remaining on current license"""
        try:
            cached = self._load_cache()
            if not cached:
                return None
            
            expiry = datetime.fromisoformat(cached['expiry_date'])
            remaining = (expiry - datetime.now()).days
            return max(0, remaining)
        except Exception:
            return None
