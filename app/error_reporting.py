"""2 つのエントリポイントで共有する GlitchTip (Sentry 互換) のエラー送信設定。"""

from __future__ import annotations

import os

import sentry_sdk


def init_error_reporting() -> None:
    """SENTRY_DSN が設定されていれば Sentry SDK を初期化する。未設定なら何もしない。

    DISCORD_WEBHOOK と同様、未設定ならまるごとスキップする任意設定。
    常駐する同期バッチでありリクエストを捌くアプリではないため、
    traces_sample_rate=0 でパフォーマンストレースを無効にしている。
    """

    dsn = os.environ.get("SENTRY_DSN")
    if dsn:
        sentry_sdk.init(dsn=dsn, traces_sample_rate=0)
