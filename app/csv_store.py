"""体重レコードの CSV 永続化と、防御的な重複排除のためのキー。"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from app.client import CSV_FIELDS


def dedup_key(row: dict[str, Any]) -> tuple[str, str, str]:
    """行の重複排除キーを作る。

    全フィールドを str にキャストする。csv.DictReader は既存行を必ず文字列で返す一方、
    新たにパースした行は API 由来の int / str のままなので、生の値のまま比べると
    両者は一致しない。同じデバイス / ユーザーが同一時刻に 2 回測ることはない。
    """

    return (str(row["measured_at_utc"]), str(row["device_serial"]), str(row["user_number_in_device"]))


def load_existing(csv_path: Path) -> list[dict[str, Any]]:
    """既存の CSV 行をすべて dict で読み込む。ファイルが無ければ空リスト。"""

    if not csv_path.exists():
        return []
    with csv_path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def append_rows(csv_path: Path, rows: list[dict[str, Any]]) -> None:
    """行を CSV に追記する。ファイルが無ければヘッダー付きで新規作成する。"""

    if not rows:
        return

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        if is_new:
            writer.writeheader()
        writer.writerows(rows)
