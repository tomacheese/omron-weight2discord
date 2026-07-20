"""Per-device sync state (last synced measurement timestamp), persisted as JSON.

Keyed by "{deviceSerialID}:{userNumberInDevice}" -> {"last_synced_ms": int}.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def device_key(device: dict[str, Any]) -> str:
    """Build the state map key identifying one device/user profile."""

    return f"{device['deviceSerialID']}:{device['userNumberInDevice']}"


def load_state(state_path: Path) -> dict[str, Any]:
    """Load the persisted per-device sync state, or an empty dict if absent."""

    if not state_path.exists():
        return {}
    return json.loads(state_path.read_text(encoding="utf-8"))


def save_state(state_path: Path, state: dict[str, Any]) -> None:
    """Atomically persist the per-device sync state as JSON."""

    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = state_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(state_path)


def seed_state_from_csv(existing_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive initial per-device last_synced_ms from a pre-existing CSV.

    Lets a CSV baseline captured before this sync tool existed be treated as
    already-synced, so the first run under the new tool doesn't re-notify
    Discord about the entire history.
    """

    state: dict[str, Any] = {}
    for row in existing_rows:
        key = f"{row['device_serial']}:{row['user_number_in_device']}"
        # measured_at_utc is ISO-8601, e.g. "2019-11-18T08:02:46+00:00"
        ms = int(datetime.fromisoformat(row["measured_at_utc"]).timestamp() * 1000)
        entry = state.setdefault(key, {"last_synced_ms": 0})
        entry["last_synced_ms"] = max(entry["last_synced_ms"], ms)

    return state
