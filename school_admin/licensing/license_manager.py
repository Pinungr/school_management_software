"""
License Manager - Handles key validation, activation, and caching
Manages licensing checks at application startup and runtime
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import socket
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, TypedDict

logger = logging.getLogger(__name__)


class LicenseInfo(TypedDict, total=False):
    """License information structure."""

    key: str
    username: str
    activation_date: str
    expiry_date: str
    machine_id: str
    status: str
    cached_at: str


class GitHubKeysDocument(TypedDict):
    """GitHub-hosted keys.json with metadata needed for updates."""

    data: dict
    sha: Optional[str]


class LicenseError(Exception):
    """Base license error."""


class LicenseExpiredError(LicenseError):
    """License has expired."""


class LicenseInvalidError(LicenseError):
    """License key is invalid or not found."""


class LicenseMachineError(LicenseError):
    """License is tied to a different machine."""


class LicenseNetworkError(LicenseError):
    """Network error during license verification."""


def get_machine_id() -> str:
    """
    Generate a unique machine identifier.
    Uses hostname + first MAC address for consistency.
    """
    try:
        hostname = socket.gethostname()

        mac = None
        if os.name == "nt":
            try:
                import uuid as uuid_module

                mac = ":".join(re.findall("..", "%012x" % uuid_module.getnode()))
            except Exception:
                pass

        machine_str = f"{hostname}:{mac or 'unknown'}"
        return hashlib.sha256(machine_str.encode()).hexdigest()[:16]
    except Exception as exc:
        logger.warning(f"Could not generate machine ID: {exc}")
        return "unknown"


class LicenseManager:
    """Manages license key validation and caching."""

    def __init__(
        self,
        app_data_dir: Path,
        github_repo: str = "pinaki-school/licenses",
        github_token: Optional[str] = None,
        cache_days: int = 30,
    ):
        """
        Initialize License Manager.

        Args:
            app_data_dir: Directory for local cache storage
            github_repo: GitHub repo in format 'owner/repo'
            github_token: GitHub PAT token
            cache_days: Days to cache license validation
        """
        self.app_data_dir = Path(app_data_dir)
        self.app_data_dir.mkdir(parents=True, exist_ok=True)

        self.github_repo = github_repo
        self.github_token = github_token or os.getenv("GITHUB_LICENSE_TOKEN")
        self.cache_days = cache_days

        repo_parts = github_repo.split("/", 1)
        if len(repo_parts) != 2 or not repo_parts[0] or not repo_parts[1]:
            raise ValueError("GitHub repo must be in 'owner/repo' format")
        self.github_owner = repo_parts[0]
        self.github_repo_name = repo_parts[1]

        self.cache_file = self.app_data_dir / "license_cache.json"
        self.github_keys_api_url = (
            f"https://api.github.com/repos/"
            f"{self.github_owner}/{self.github_repo_name}/contents/keys.json"
        )
        self.machine_id = get_machine_id()

    def _build_github_headers(self, accept: str) -> dict[str, str]:
        """Build GitHub API headers."""
        headers = {
            "Accept": accept,
            "User-Agent": "Pinaki-License/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.github_token:
            prefix = "Bearer" if self.github_token.startswith("github_pat_") else "token"
            headers["Authorization"] = f"{prefix} {self.github_token}"
        return headers

    def _raise_github_error(self, error: Exception, action: str) -> None:
        """Convert GitHub/network failures into user-facing licensing errors."""
        if isinstance(error, urllib.error.HTTPError):
            if error.code in {401, 403}:
                raise LicenseNetworkError(
                    "GitHub rejected the license token. Check GITHUB_LICENSE_TOKEN "
                    f"and ensure it has access to '{self.github_repo}'."
                ) from error
            if error.code == 404:
                raise LicenseNetworkError(
                    f"Could not find 'keys.json' in GitHub repo '{self.github_repo}'. "
                    "Check the repo name, branch, and file path."
                ) from error
            if error.code == 409:
                raise LicenseNetworkError(
                    "GitHub reported a license database conflict. Please try the "
                    "activation again."
                ) from error
            raise LicenseNetworkError(
                f"GitHub returned HTTP {error.code} while trying to {action}."
            ) from error

        raise LicenseNetworkError(f"Could not {action}: {error}") from error

    def _get_github_keys_document(self) -> GitHubKeysDocument:
        """
        Fetch keys from GitHub repository.

        Returns:
            GitHubKeysDocument with parsed data and content sha.
        """
        try:
            req = urllib.request.Request(
                self.github_keys_api_url,
                headers=self._build_github_headers("application/vnd.github+json"),
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))

            if not isinstance(payload, dict) or "content" not in payload:
                raise LicenseNetworkError("GitHub returned an unexpected license payload.")

            encoded_content = str(payload.get("content", "")).replace("\n", "")
            decoded_content = base64.b64decode(encoded_content).decode("utf-8")
            data = json.loads(decoded_content)
            if "keys" not in data:
                raise LicenseNetworkError("GitHub license data does not contain a 'keys' section.")

            return {
                "data": data,
                "sha": payload.get("sha"),
            }
        except json.JSONDecodeError as exc:
            logger.error(f"Invalid GitHub keys format: {exc}")
            raise LicenseNetworkError(f"Invalid license data format: {exc}") from exc
        except (urllib.error.URLError, urllib.error.HTTPError, socket.timeout, ValueError) as exc:
            logger.error(f"Failed to fetch keys from GitHub: {exc}")
            self._raise_github_error(exc, "read license data from GitHub")

    def _save_github_keys(self, github_data: dict, sha: Optional[str], message: str) -> None:
        """Persist updated keys.json back to GitHub."""
        if not self.github_token:
            raise LicenseNetworkError(
                "GitHub token is required to record license activation."
            )

        payload = {
            "message": message,
            "content": base64.b64encode(
                (json.dumps(github_data, indent=2) + "\n").encode("utf-8")
            ).decode("ascii"),
            "branch": "main",
        }
        if sha:
            payload["sha"] = sha

        request_data = json.dumps(payload).encode("utf-8")
        headers = self._build_github_headers("application/vnd.github+json")
        headers["Content-Type"] = "application/json"

        try:
            req = urllib.request.Request(
                self.github_keys_api_url,
                data=request_data,
                headers=headers,
                method="PUT",
            )
            with urllib.request.urlopen(req, timeout=10):
                logger.info("Updated license activation in GitHub")
        except (urllib.error.URLError, urllib.error.HTTPError, socket.timeout) as exc:
            logger.error(f"Failed to update keys on GitHub: {exc}")
            self._raise_github_error(exc, "write license data to GitHub")

    def _load_cache(self) -> Optional[LicenseInfo]:
        """Load cached license info."""
        if not self.cache_file.exists():
            return None

        try:
            with open(self.cache_file, "r", encoding="utf-8") as handle:
                cache_data = json.load(handle)

            cached_at = datetime.fromisoformat(cache_data.get("cached_at"))
            if (datetime.now() - cached_at).days <= self.cache_days:
                logger.debug("Using cached license info")
                return cache_data

            logger.debug("Cache expired, will validate with GitHub")
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning(f"Could not load cache: {exc}")

        return None

    def _save_cache(self, license_info: LicenseInfo) -> None:
        """Save license info to cache."""
        license_info["cached_at"] = datetime.now().isoformat()
        try:
            with open(self.cache_file, "w", encoding="utf-8") as handle:
                json.dump(license_info, handle, indent=2)
        except Exception as exc:
            logger.warning(f"Could not save license cache: {exc}")

    def validate_key(self, key: str, username: str = "Unknown") -> LicenseInfo:
        """
        Validate an activation key.

        Raises:
            LicenseInvalidError: Key is invalid or already used by another user
            LicenseExpiredError: License has expired
            LicenseMachineError: Key is tied to a different machine
            LicenseNetworkError: Network or GitHub failure
        """
        key = key.strip().upper()
        username = username.strip() or "Unknown"

        cached = self._load_cache()
        if cached and cached.get("key") == key:
            logger.info("License validated against cache")

            expiry = datetime.fromisoformat(cached["expiry_date"])
            if datetime.now() > expiry:
                raise LicenseExpiredError(
                    f"License expired on {expiry.strftime('%Y-%m-%d')}"
                )

            if cached.get("machine_id") != self.machine_id:
                cached_machine = cached.get("machine_id", "unknown")
                raise LicenseMachineError(
                    "License is tied to a different machine "
                    f"({cached_machine}). Current: {self.machine_id}"
                )

            return cached

        logger.info("Validating license key with GitHub...")
        try:
            github_document = self._get_github_keys_document()
        except LicenseNetworkError as exc:
            if cached and cached.get("key") == key:
                logger.warning(f"Network error, using cached license: {exc}")
                return cached
            raise

        github_data = github_document["data"]
        github_sha = github_document["sha"]

        keys_db = github_data.setdefault("keys", {})
        if key not in keys_db:
            raise LicenseInvalidError(f"Activation key '{key}' not found")

        key_info = keys_db[key]
        if key_info.get("status") != "active":
            raise LicenseInvalidError(
                f"Activation key is {key_info.get('status', 'invalid')}"
            )

        assigned_user = key_info.get("username")
        assigned_machine = key_info.get("machine_id")

        if assigned_user and assigned_user != username:
            raise LicenseInvalidError(
                f"Activation key is already in use by '{assigned_user}'"
            )
        if assigned_machine and assigned_machine != self.machine_id:
            raise LicenseMachineError("Activation key is tied to a different machine")

        now = datetime.now()
        activation_date = key_info.get("activation_date")
        expiry_date_str = key_info.get("expiry_date")
        needs_remote_update = False

        if not activation_date:
            activation_date = now.isoformat()
            key_info["activation_date"] = activation_date
            needs_remote_update = True
        if not expiry_date_str:
            activation_date_obj = datetime.fromisoformat(activation_date)
            expiry_date_str = (activation_date_obj + timedelta(days=365)).strftime(
                "%Y-%m-%d"
            )
            key_info["expiry_date"] = expiry_date_str
            needs_remote_update = True
        if not assigned_user:
            key_info["username"] = username
            needs_remote_update = True
        if not assigned_machine:
            key_info["machine_id"] = self.machine_id
            needs_remote_update = True

        if needs_remote_update:
            github_data["updated_at"] = now.isoformat()
            self._save_github_keys(
                github_data,
                github_sha,
                f"Activate license {key} for {key_info.get('username')}",
            )

        expiry = datetime.fromisoformat(expiry_date_str)
        if datetime.now() > expiry:
            raise LicenseExpiredError(
                f"License expired on {expiry.strftime('%Y-%m-%d')}"
            )

        license_info: LicenseInfo = {
            "key": key,
            "username": key_info.get("username", username),
            "activation_date": activation_date,
            "expiry_date": expiry_date_str,
            "machine_id": self.machine_id,
            "status": "active",
        }

        self._save_cache(license_info)
        logger.info(f"License validated successfully for '{license_info['username']}'")
        return license_info

    def get_license_status(self) -> Optional[LicenseInfo]:
        """Get current license status from cache without network calls."""
        return self._load_cache()

    def is_licensed(self) -> bool:
        """Check if application is currently licensed using cache only."""
        try:
            cached = self._load_cache()
            if not cached:
                return False

            expiry = datetime.fromisoformat(cached["expiry_date"])
            return datetime.now() <= expiry
        except Exception:
            return False

    def get_days_remaining(self) -> Optional[int]:
        """Get days remaining on current license."""
        try:
            cached = self._load_cache()
            if not cached:
                return None

            expiry = datetime.fromisoformat(cached["expiry_date"])
            remaining = (expiry - datetime.now()).days
            return max(0, remaining)
        except Exception:
            return None
