"""Discord webhook notification for newly-synced weight records, as embeds."""

from __future__ import annotations

from typing import Any

import requests

MAX_SHOWN_RECORDS = 3
COLOR = 0x3AA0FF

# (row key, display label, unit)
METRIC_SPECS: list[tuple[str, str, str]] = [
    ("bmi", "BMI", ""),
    ("body_fat_percentage", "体脂肪率", "%"),
    ("skeletal_muscle_percentage", "骨格筋率", "%"),
    ("visceral_fat_level", "内臓脂肪レベル", ""),
    ("resting_metabolism_kcal", "基礎代謝", " kcal"),
    ("metabolic_age", "体内年齢", ""),
]


def _metric_fields(row: dict[str, Any]) -> list[dict[str, Any]]:
    """One inline Discord field per available body-composition metric (weight is the title, not a field)."""

    fields = []
    for key, label, unit in METRIC_SPECS:
        value = row.get(key)
        if value in (None, ""):
            continue
        fields.append({"name": label, "value": f"{value}{unit}", "inline": True})
    return fields


def _build_embed(row: dict[str, Any]) -> dict[str, Any]:
    """One embed for a single weight record.

    Weight is the headline number, so it's the title; everything else is a
    field. Time is conveyed via Discord's own `timestamp` field (rendered in
    each viewer's local time), not written out as text.
    """

    return {
        "title": f"{row['weight_kg']} kg",
        "color": COLOR,
        "fields": _metric_fields(row),
        "timestamp": row["measured_at_utc"],
        "footer": {"text": row["device_model"]},
    }


def build_payload(new_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the full webhook payload: one embed per record, most recent first.

    Only the MAX_SHOWN_RECORDS most recent records get their own embed; if
    more were synced, a plain-text note on the omitted count is added.
    """

    shown = new_rows[-MAX_SHOWN_RECORDS:]
    payload: dict[str, Any] = {"embeds": [_build_embed(row) for row in reversed(shown)]}

    omitted = len(new_rows) - len(shown)
    if omitted > 0:
        payload["content"] = f"他 {omitted} 件も同期済み"

    return payload


def send_payload(webhook_url: str, payload: dict[str, Any]) -> None:
    """Post a webhook payload (embeds, optionally content) to Discord."""

    r = requests.post(webhook_url, json=payload, timeout=10)
    r.raise_for_status()


def notify_new_records(webhook_url: str, new_rows: list[dict[str, Any]]) -> None:
    """Send a Discord notification for newly-synced records; no-op if there are none."""

    if not new_rows:
        return
    send_payload(webhook_url, build_payload(new_rows))
