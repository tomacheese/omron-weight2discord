"""1 回限りの同期。前回以降の新しい体重レコードを取得し、CSV に追記して Discord へ通知する。"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from app import csv_store, discord_notify, outbox, state as state_mod
from app.client import DEVICE_CATEGORY_SCALE, OmronConnectV1, parse_scale_measurement
from app.error_reporting import init_error_reporting

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = Path(os.environ.get("OMRON_SYNC_DATA_DIR", "data"))


def load_env_file(path: Path) -> dict[str, str]:
    """最小限の .env パーサー (KEY=VALUE 形式の行のみ。外部依存なし)。"""

    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def get_config() -> dict[str, str]:
    """設定を解決する。実環境変数を優先し、無ければ .env から読む。

    実環境変数を優先するので、プロセスの環境変数を設定するだけの Compose の `env_file:` が
    追加のパース処理なしで動く。独自の .env パーサーは、Docker を使わずローカルで動かすためのもの。
    """

    base_dir = Path(__file__).resolve().parent.parent
    env = load_env_file(base_dir / ".env")
    env.update({k: v for k, v in os.environ.items() if k in ("OMRON_CONNECT_EMAIL", "OMRON_CONNECT_PASSWORD", "DISCORD_WEBHOOK")})
    return env


def run_sync(data_dir: Path | None = None, notify: bool = True) -> list[dict[str, Any]]:
    """同期を 1 パス実行する。新たに追加した行のリストを返す (新規が無ければ空)。"""

    data_dir = data_dir or DEFAULT_DATA_DIR
    csv_path = data_dir / "weight_data.csv"
    state_path = data_dir / "state.json"
    outbox_path = data_dir / "outbox.json"

    env = get_config()
    email = env.get("OMRON_CONNECT_EMAIL")
    password = env.get("OMRON_CONNECT_PASSWORD")
    webhook_url = env.get("DISCORD_WEBHOOK")
    if not email or not password:
        raise RuntimeError("OMRON_CONNECT_EMAIL / OMRON_CONNECT_PASSWORD not configured")

    existing_rows = csv_store.load_existing(csv_path)
    existing_keys = {csv_store.dedup_key(row) for row in existing_rows}

    state = state_mod.load_state(state_path)
    if not state and existing_rows:
        # 既存の CSV がある状態での初回実行。履歴全体を Discord へ再通知せず、
        # 同期済みとして扱う。
        state = state_mod.seed_state_from_csv(existing_rows)
        logger.info("Seeded sync state from existing CSV baseline (%d rows).", len(existing_rows))

    client = OmronConnectV1()
    logger.info("Logging in as %s ...", email)
    client.login(email, password)

    devices = client.get_registered_devices()
    scale_devices = [d for d in devices if str(d.get("deviceCategory")) == DEVICE_CATEGORY_SCALE]
    logger.info("Found %d device profile(s), %d scale profile(s).", len(devices), len(scale_devices))

    new_rows: list[dict[str, Any]] = []
    for device in scale_devices:
        key = state_mod.device_key(device)
        last_synced_ms = int(state.get(key, {}).get("last_synced_ms", 0))
        search_date_from = last_synced_ms + 1 if last_synced_ms else 0

        raw_measurements = client.get_measurements(device, search_date_from=search_date_from)
        logger.info(
            "%s (%s): %d raw record(s) since %s",
            device["deviceModel"],
            device["deviceSerialID"],
            len(raw_measurements),
            "beginning" if search_date_from == 0 else search_date_from,
        )

        device_new_rows: list[dict[str, Any]] = []
        max_ms = last_synced_ms
        for m in raw_measurements:
            row = parse_scale_measurement(m, device)
            if not row:
                continue
            if csv_store.dedup_key(row) in existing_keys:
                continue
            device_new_rows.append(row)
            existing_keys.add(csv_store.dedup_key(row))
            max_ms = max(max_ms, row["_measurement_ms"])

        if device_new_rows:
            new_rows.extend(device_new_rows)
            state[key] = {"last_synced_ms": max_ms}

    new_rows.sort(key=lambda r: r["measured_at_utc"])

    use_outbox = notify and bool(webhook_url)
    if use_outbox and new_rows:
        # CSV 追記より先に保存する。CSV 追記後に落ちると、次回は dedup で除外されて通知が失われるため。
        pending = outbox.enqueue(outbox.load_pending(outbox_path), new_rows)
        outbox.save_pending(outbox_path, pending)
        logger.info("Queued %d record(s) for Discord notification.", len(new_rows))

    if new_rows:
        csv_store.append_rows(csv_path, new_rows)
        logger.info("Appended %d new record(s) to %s", len(new_rows), csv_path)
    else:
        logger.info("No new records.")

    state_mod.save_state(state_path, state)

    if use_outbox:
        pending = sorted(outbox.load_pending(outbox_path), key=lambda r: r["measured_at_utc"])
        if pending:
            try:
                discord_notify.notify_new_records(webhook_url, pending)
            except Exception:
                logger.error("Discord notification failed; %d record(s) remain queued for retry.", len(pending))
                raise
            outbox.save_pending(outbox_path, [])
            logger.info("Sent Discord notification for %d record(s).", len(pending))
    elif notify and new_rows:
        logger.warning("New records found but DISCORD_WEBHOOK is not configured; skipping notification.")

    return new_rows


def main() -> int:
    """ログを設定し、同期を 1 パス実行する。"""

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    init_error_reporting()

    run_sync()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
