"""CSV persistence for weight records, with a dedup key for defensive de-duplication."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from app.client import CSV_FIELDS


def dedup_key(row: dict[str, Any]) -> tuple[str, str, str]:
    """Build a dedup key for a row.

    Cast every field to str: csv.DictReader always yields strings for
    existing rows, while freshly-parsed rows carry native int/str types from
    the API, so comparing raw values would never match between the two.
    A given device/user can't record two weighings at the exact same instant.
    """

    return (str(row["measured_at_utc"]), str(row["device_serial"]), str(row["user_number_in_device"]))


def load_existing(csv_path: Path) -> list[dict[str, Any]]:
    """Read all existing CSV rows as dicts, or an empty list if the file is absent."""

    if not csv_path.exists():
        return []
    with csv_path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def append_rows(csv_path: Path, rows: list[dict[str, Any]]) -> None:
    """Append rows to the CSV, creating it (with header) if it doesn't exist yet."""

    if not rows:
        return

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        if is_new:
            writer.writeheader()
        writer.writerows(rows)
