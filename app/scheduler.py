"""Entrypoint: run the sync once immediately, then every INTERVAL_SECONDS forever.

Designed to be the container's main process (Compose `restart:
unless-stopped`). Exceptions during a single sync pass are logged and
swallowed so a transient OMRON/Discord outage doesn't kill the loop.
"""

from __future__ import annotations

import logging
import os
import time

from app.error_reporting import init_error_reporting
from app.sync import run_sync

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = int(os.environ.get("SYNC_INTERVAL_SECONDS", "1800"))


def main() -> int:
    """Run the sync immediately, then repeat every INTERVAL_SECONDS forever."""

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    init_error_reporting()

    logger.info("Starting scheduler loop (interval=%ds).", INTERVAL_SECONDS)

    while True:
        try:
            run_sync()
        except Exception:
            logger.exception("Sync pass failed; will retry next interval.")

        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
