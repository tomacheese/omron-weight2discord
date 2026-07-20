"""One-shot sync: fetch new weight records since last run, append to CSV, notify Discord."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from app import csv_store, discord_notify, state as state_mod
from app.client import DEVICE_CATEGORY_SCALE, OmronConnectV1, parse_scale_measurement

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = Path(os.environ.get("OMRON_SYNC_DATA_DIR", "data"))


def load_env_file(path: Path) -> dict[str, str]:
    """Minimal .env parser (KEY=VALUE lines, no external dependency)."""

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
    """Resolve config from real environment variables first, falling back to .env.

    Real env vars take precedence so Compose's `env_file:` (which just sets
    process env vars) works without any extra parsing on our side; the manual
    .env parser is there for running this locally without Docker.
    """

    base_dir = Path(__file__).resolve().parent.parent
    env = load_env_file(base_dir / ".env")
    env.update({k: v for k, v in os.environ.items() if k in ("OMRON_CONNECT_EMAIL", "OMRON_CONNECT_PASSWORD", "DISCORD_WEBHOOK")})
    return env


def run_sync(data_dir: Path | None = None, notify: bool = True) -> list[dict[str, Any]]:
    """Run one sync pass. Returns the list of newly-added rows (empty if nothing new)."""

    data_dir = data_dir or DEFAULT_DATA_DIR
    csv_path = data_dir / "weight_data.csv"
    state_path = data_dir / "state.json"

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
        # First run against a pre-existing CSV baseline: treat it as already
        # synced instead of re-notifying Discord about the whole history.
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

    if new_rows:
        csv_store.append_rows(csv_path, new_rows)
        logger.info("Appended %d new record(s) to %s", len(new_rows), csv_path)
    else:
        logger.info("No new records.")

    state_mod.save_state(state_path, state)

    if notify and new_rows and webhook_url:
        discord_notify.notify_new_records(webhook_url, new_rows)
        logger.info("Sent Discord notification for %d new record(s).", len(new_rows))
    elif notify and new_rows and not webhook_url:
        logger.warning("New records found but DISCORD_WEBHOOK is not configured; skipping notification.")

    return new_rows


def main() -> int:
    """Configure logging and run a single sync pass."""

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run_sync()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
