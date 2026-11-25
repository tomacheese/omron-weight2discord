"""2 つのエントリポイントで共有する GlitchTip (Sentry 互換) のエラー送信設定。"""

from __future__ import annotations

import sentry_sdk


def init_error_reporting(dsn: str | None) -> None:
    """dsn が空でなければ Sentry SDK を初期化する。None または空文字なら何もしない。

    DISCORD_WEBHOOK と同様、未設定ならまるごとスキップする任意設定。
    常駐する同期バッチでありリクエストを捌くアプリではないため、
    traces_sample_rate=0 でパフォーマンストレースを無効にしている。
    スタックフレームのローカル変数には認証情報や測定履歴が含まれるため、
    include_local_variables=False で送信しない。
    """

    if dsn:
        sentry_sdk.init(dsn=dsn, traces_sample_rate=0, include_local_variables=False)
