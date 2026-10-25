"""Integrity verification for simulated firmware packages and maintenance logs."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Mapping, Sequence


class IntegrityChecker:
    """Verify firmware HMAC signatures and a tamper-evident log hash chain."""

    def __init__(self, firmware_key: bytes | None = None) -> None:
        if firmware_key is not None and len(firmware_key) < 32:
            raise ValueError("firmware_key must contain at least 32 bytes.")
        self._firmware_key = firmware_key

    @property
    def firmware_verification_configured(self) -> bool:
        return self._firmware_key is not None

    def sign_firmware_package(self, package: bytes) -> str:
        if self._firmware_key is None:
            raise RuntimeError("Firmware signing key is not configured.")
        if not isinstance(package, bytes) or not package:
            raise ValueError("Firmware package must be non-empty bytes.")
        return hmac.new(self._firmware_key, package, hashlib.sha256).hexdigest()

    def verify_firmware_signature(self, package: bytes, signature: str | None) -> bool:
        if self._firmware_key is None or not isinstance(signature, str):
            return False
        if not isinstance(package, bytes) or not package or not signature:
            return False
        expected = self.sign_firmware_package(package)
        return hmac.compare_digest(expected, signature)

    @staticmethod
    def create_log_entry(
        entry_id: str,
        recorded_at: str,
        data: Mapping[str, Any],
        previous_hash: str,
    ) -> dict[str, Any]:
        entry = {
            "entry_id": entry_id,
            "recorded_at": recorded_at,
            "data": dict(data),
            "previous_hash": previous_hash,
        }
        entry["record_hash"] = IntegrityChecker._log_hash(entry)
        return entry

    @staticmethod
    def verify_log_chain(entries: Sequence[Mapping[str, Any]]) -> bool:
        previous_hash = "0" * 64
        for entry in entries:
            if not isinstance(entry, Mapping):
                return False
            if entry.get("previous_hash") != previous_hash:
                return False
            recorded_hash = entry.get("record_hash")
            if not isinstance(recorded_hash, str) or not hmac.compare_digest(
                IntegrityChecker._log_hash(entry), recorded_hash
            ):
                return False
            previous_hash = recorded_hash
        return True

    @staticmethod
    def _log_hash(entry: Mapping[str, Any]) -> str:
        payload = {
            "entry_id": entry.get("entry_id"),
            "recorded_at": entry.get("recorded_at"),
            "data": entry.get("data"),
            "previous_hash": entry.get("previous_hash"),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
