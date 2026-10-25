"""Controlled maintenance-record tampering scenario for local testing."""

from __future__ import annotations

from typing import Any, MutableMapping


def maintenance_log_manipulation(entry: MutableMapping[str, Any]) -> dict[str, Any]:
    """Alter one record's content while deliberately retaining its old hash."""
    if not isinstance(entry, MutableMapping) or not isinstance(entry.get("data"), dict):
        raise TypeError("entry must be a maintenance-log record with object data.")
    original_hash = entry.get("record_hash")
    entry["data"] = {**entry["data"], "inspection": "tampered"}
    return {
        "name": "maintenance_log_manipulation",
        "entry_id": entry.get("entry_id"),
        "original_hash": original_hash,
        "description": "Maintenance record content altered without updating its integrity hash.",
    }
