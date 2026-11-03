"""デバイスごとの同期状態 (最後に同期した測定のタイムスタンプ) を JSON で永続化する。

"{deviceSerialID}:{userNumberInDevice}" をキーとし、値は {"last_synced_ms": int}。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def device_key(device: dict[str, Any]) -> str:
    """1 つのデバイス / ユーザープロファイルを識別する状態マップのキーを作る。"""

    return f"{device['deviceSerialID']}:{device['userNumberInDevice']}"


def load_state(state_path: Path) -> dict[str, Any]:
    """永続化済みのデバイスごとの同期状態を読み込む。ファイルが無ければ空 dict。"""

    if not state_path.exists():
        return {}
    return json.loads(state_path.read_text(encoding="utf-8"))


def save_state(state_path: Path, state: dict[str, Any]) -> None:
    """デバイスごとの同期状態を JSON として原子的に保存する。"""

    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = state_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(state_path)


def seed_state_from_csv(existing_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """既存の CSV から、デバイスごとの last_synced_ms の初期値を求める。

    このツールの導入前に取得済みの CSV を同期済みとして扱い、
    初回実行で履歴全体を Discord へ再通知しないようにする。
    """

    state: dict[str, Any] = {}
    for row in existing_rows:
        key = f"{row['device_serial']}:{row['user_number_in_device']}"
        # measured_at_utc は ISO-8601 形式。例: "2019-11-18T08:02:46+00:00"
        ms = int(datetime.fromisoformat(row["measured_at_utc"]).timestamp() * 1000)
        entry = state.setdefault(key, {"last_synced_ms": 0})
        entry["last_synced_ms"] = max(entry["last_synced_ms"], ms)

    return state
