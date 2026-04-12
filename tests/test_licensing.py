from __future__ import annotations

import base64
import json
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError

import pytest

from school_admin.licensing.license_manager import (
    LicenseManager,
    LicenseMachineError,
    LicenseNetworkError,
)


class FakeResponse:
    def __init__(self, payload: str):
        self.payload = payload.encode("utf-8")

    def read(self) -> bytes:
        return self.payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def github_contents_payload(data: dict, sha: str = "sha-123") -> str:
    encoded = base64.b64encode(json.dumps(data).encode("utf-8")).decode("ascii")
    return json.dumps(
        {
            "sha": sha,
            "content": encoded,
            "encoding": "base64",
        }
    )


def test_validate_key_records_first_activation(monkeypatch, tmp_path: Path):
    github_data = {
        "version": "1.0",
        "updated_at": "2026-04-12T00:00:00",
        "keys": {
            "PINAKI-TEST-KEY1-ABCD-EFGH": {
                "username": None,
                "activation_date": None,
                "expiry_date": None,
                "machine_id": None,
                "status": "active",
            }
        },
    }
    writes: list[dict] = []

    def fake_urlopen(request, timeout=0):
        if request.method == "PUT":
            writes.append(json.loads(request.data.decode("utf-8")))
            return FakeResponse('{"content": {"sha": "sha-456"}}')
        return FakeResponse(github_contents_payload(github_data))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    manager = LicenseManager(
        app_data_dir=tmp_path,
        github_repo="owner/licenses",
        github_token="github_pat_test_token",
    )
    monkeypatch.setattr(manager, "machine_id", "machine-123")

    license_info = manager.validate_key("pinaki-test-key1-abcd-efgh", username="School One")

    assert license_info["username"] == "School One"
    assert license_info["machine_id"] == "machine-123"
    assert license_info["status"] == "active"
    assert license_info["expiry_date"]
    assert len(writes) == 1

    saved = base64.b64decode(writes[0]["content"]).decode("utf-8")
    saved_data = json.loads(saved)
    saved_key = saved_data["keys"]["PINAKI-TEST-KEY1-ABCD-EFGH"]
    assert saved_key["username"] == "School One"
    assert saved_key["machine_id"] == "machine-123"
    assert saved_key["activation_date"]
    assert saved_key["expiry_date"]
    assert (tmp_path / "license_cache.json").exists()


def test_validate_key_rejects_different_machine(monkeypatch, tmp_path: Path):
    github_data = {
        "version": "1.0",
        "updated_at": "2026-04-12T00:00:00",
        "keys": {
            "PINAKI-TEST-KEY2-ABCD-EFGH": {
                "username": "School One",
                "activation_date": "2026-04-12T08:00:00",
                "expiry_date": "2027-04-12",
                "machine_id": "machine-abc",
                "status": "active",
            }
        },
    }

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout=0: FakeResponse(github_contents_payload(github_data)),
    )

    manager = LicenseManager(
        app_data_dir=tmp_path,
        github_repo="owner/licenses",
        github_token="github_pat_test_token",
    )
    monkeypatch.setattr(manager, "machine_id", "machine-other")

    with pytest.raises(LicenseMachineError):
        manager.validate_key("PINAKI-TEST-KEY2-ABCD-EFGH", username="School One")


def test_validate_key_surfaces_github_auth_error(monkeypatch, tmp_path: Path):
    def fake_urlopen(request, timeout=0):
        raise HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            hdrs=None,
            fp=BytesIO(b"{}"),
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    manager = LicenseManager(
        app_data_dir=tmp_path,
        github_repo="owner/licenses",
        github_token="github_pat_test_token",
    )

    with pytest.raises(LicenseNetworkError, match="rejected the license token"):
        manager.validate_key("PINAKI-TEST-KEY3-ABCD-EFGH", username="School One")
