"""新たに同期した体重レコードを embed として Discord webhook で通知する。"""

from __future__ import annotations

from typing import Any

import requests

MAX_SHOWN_RECORDS = 3
COLOR = 0x3AA0FF

# (行のキー, 表示ラベル, 単位)
METRIC_SPECS: list[tuple[str, str, str]] = [
    ("bmi", "BMI", ""),
    ("body_fat_percentage", "体脂肪率", "%"),
    ("skeletal_muscle_percentage", "骨格筋率", "%"),
    ("visceral_fat_level", "内臓脂肪レベル", ""),
    ("resting_metabolism_kcal", "基礎代謝", " kcal"),
    ("metabolic_age", "体内年齢", ""),
]


def _metric_fields(row: dict[str, Any]) -> list[dict[str, Any]]:
    """利用可能な体組成メトリクスごとに 1 つの inline フィールドを作る (体重はタイトルに使うのでフィールドにしない)。"""

    fields = []
    for key, label, unit in METRIC_SPECS:
        value = row.get(key)
        if value in (None, ""):
            continue
        fields.append({"name": label, "value": f"{value}{unit}", "inline": True})
    return fields


def _build_embed(row: dict[str, Any]) -> dict[str, Any]:
    """体重レコード 1 件分の embed を作る。

    体重が見出しとなる数値なのでタイトルにし、それ以外はフィールドにする。
    時刻は文字列で書かず、Discord 自身の `timestamp` フィールドで伝える
    (閲覧者ごとのローカル時刻で描画される)。
    """

    return {
        "title": f"{row['weight_kg']} kg",
        "color": COLOR,
        "fields": _metric_fields(row),
        "timestamp": row["measured_at_utc"],
        "footer": {"text": row["device_model"]},
    }


def build_payload(new_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """webhook のペイロード全体を作る (レコード 1 件につき 1 embed)。

    `new_rows` は `sync.run_sync` が保証するとおり昇順 (古い順) にソート済みであることを
    前提とし、この関数ではソートしない。
    """

    shown = new_rows[-MAX_SHOWN_RECORDS:]
    payload: dict[str, Any] = {"embeds": [_build_embed(row) for row in shown]}

    omitted = len(new_rows) - len(shown)
    if omitted > 0:
        payload["content"] = f"他 {omitted} 件も同期済み"

    return payload


def send_payload(webhook_url: str, payload: dict[str, Any]) -> None:
    """webhook ペイロード (embeds と任意の content) を Discord へ POST する。"""

    r = requests.post(webhook_url, json=payload, timeout=10)
    r.raise_for_status()


def notify_new_records(webhook_url: str, new_rows: list[dict[str, Any]]) -> None:
    """新たに同期したレコードを Discord へ通知する。レコードが無ければ何もしない。"""

    if not new_rows:
        return
    send_payload(webhook_url, build_payload(new_rows))
