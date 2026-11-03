# AGENTS.md

## 言語規約

- 成果物 (コミットの説明、PR / Issue の題名・本文・レビューコメント、コードコメント / docstring、ドキュメント、仕様書・計画書) は日本語で書く。
- 例外: Discord 通知などエンドユーザー向けの文言、日本語のデータパターン・フィクスチャ、引用、技術的な識別子、フォーク PR 承認コメントの文言とその `body-includes` の一致キー (`.github/workflows/docker.yml`)。
- エラーメッセージは英語。
- 日本語と英数字の間には半角スペースを入れる。

## 概要

OMRON connect のクラウド (日本アカウント / Kii ベースの「API v1」) から体重・体組成の測定履歴を差分同期し、CSV に追記して、新規レコードを Discord へ通知する Python ツール。詳細は `README.md` を参照。

## 開発コマンド

- 依存関係のインストール: `pip install -r requirements.txt`
- 1 回だけ同期: `python3 -m app.sync`
- ループ実行 (コンテナの CMD と同じ): `python3 -m app.scheduler`
- テスト: `python3 -m unittest discover -s tests -t .`
- Docker: `docker compose up -d --build`

## アーキテクチャ

- `app/client.py`: OMRON connect v1 クライアントと測定値のパース
- `app/sync.py`: 同期 1 パス (`run_sync`) と設定の解決
- `app/scheduler.py`: 起動直後と `SYNC_INTERVAL_SECONDS` ごとに `run_sync` を実行する常駐エントリポイント
- `app/state.py` / `app/csv_store.py` / `app/outbox.py`: `data/` 配下の `state.json` / `weight_data.csv` / `outbox.json` の永続化
- `app/discord_notify.py`: Discord webhook への embed 通知
- `app/error_reporting.py`: GlitchTip (Sentry 互換) の初期化

## 守るべき不変条件

- 実環境変数は `.env` の値より優先する (Compose の `env_file:` と整合させるため)。
- 通知対象のレコードは、CSV への追記より先に `outbox.json` へ保存する。CSV 追記後に落ちると、次回は重複排除で除外されて通知が失われるため。outbox は Discord への送信が成功したときだけ空にする。
- 状態 (`state.json`) は `last_synced_ms` を保持し、`searchDateFrom = last_synced_ms + 1` で差分のみ要求する。CSV の重複排除は防御的な二重チェックとして残す。
- `state.json` が無く CSV が存在する場合は、CSV から状態をシードして履歴の再通知を防ぐ。
- `measureData` は 200 件単位でページングされる。`nextPaginationKey` が返らなくなるまでループすること。
- `OMRON_CONNECT_EMAIL` / `OMRON_CONNECT_PASSWORD` / `DISCORD_WEBHOOK` / `SENTRY_DSN` などの秘密情報をコミットしない。パスワード、Webhook URL、DSN はログにも出力しない(ログイン用メールアドレスは現状 `app/sync.py` で出力されている。新たに出力を増やさないこと)。`.env` と `data/` は Git 管理外。
