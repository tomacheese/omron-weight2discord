"""エントリポイント。まず即座に 1 回同期し、以降は INTERVAL_SECONDS ごとに無限に繰り返す。

コンテナのメインプロセス (Compose の `restart: unless-stopped`) として動かす想定。
1 回の同期パスで発生した例外はログに記録して握りつぶし、OMRON / Discord の
一時的な障害でループが止まらないようにしている。
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
    """即座に同期し、以降 INTERVAL_SECONDS ごとに無限に繰り返す。"""

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
