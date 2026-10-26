"""Discord へ未配送のレコードを `data/outbox.json` に永続化する。

データ同期位置 (`state.json`) とは独立して、送信成功後にのみ取り除く。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app import csv_store, state


def load_pending(path: Path) -> list[dict[str, Any]]:
    """未配送レコードを読み込む。ファイルが無ければ空リスト。"""

    return state.load_state(path).get("pending", [])


def save_pending(path: Path, rows: list[dict[str, Any]]) -> None:
    """未配送レコードを原子的に保存する。"""

    state.save_state(path, {"pending": rows})


def enqueue(pending: list[dict[str, Any]], new_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`pending` に無いレコードだけを末尾に足した新しいリストを返す (引数は変更しない)。"""

    seen = {csv_store.dedup_key(row) for row in pending}
    added = [row for row in new_rows if csv_store.dedup_key(row) not in seen]
    return pending + added
