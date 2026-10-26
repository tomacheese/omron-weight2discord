# omron-weight-sync

OMRON connect のクラウドバックエンド (日本アカウント / Kii ベースの「API v1」) から体重・体組成の測定履歴を差分同期し、ローカルの CSV に追記したうえで、新たに見つかったレコードを Discord へ通知するツールです。

## セットアップと実行

### Docker で実行する (推奨)

```bash
docker compose up -d --build
```

`app.scheduler` が起動し、まず即座に 1 回同期を実行したあと、`SYNC_INTERVAL_SECONDS` (デフォルト `1800` = 30 分。`Dockerfile` の `ENV` で定義) ごとに同期を繰り返します。`./data` を `/app/data` にバインドマウントしているため、CSV と同期状態はコンテナの再起動をまたいで保持されます。

事前に `.env.example` をコピーして `.env` を作成し、必要な値を設定してください。

```bash
cp .env.example .env
```

### Docker を使わずにローカルで実行する

```bash
pip install -r requirements.txt
python3 -m app.sync        # 1 回だけ同期する
python3 -m app.scheduler   # コンテナの CMD と同じくループ実行する
```

## 設定 (環境変数)

`.env` に以下の環境変数を設定します。Compose の `env_file:` はこれらをプロセスの環境変数として渡すだけなので、実環境変数が `.env` の値より優先されます。

| 変数名 | 必須 | 説明 |
|---|---|---|
| `OMRON_CONNECT_EMAIL` | 必須 | OMRON connect のログインに使用するメールアドレス |
| `OMRON_CONNECT_PASSWORD` | 必須 | OMRON connect のログインに使用するパスワード |
| `DISCORD_WEBHOOK` | 任意 | 新規レコードの通知先 Discord Webhook URL。未設定の場合は通知をスキップします |
| `SENTRY_DSN` | 任意 | エラー送信先の GlitchTip (Sentry 互換) DSN。未設定の場合はエラー送信をスキップします |

## 差分同期の仕組み

デバイス / ユーザーごとに `last_synced_ms` を `data/state.json` に保持します。各同期パスでは `searchDateFrom` を `last_synced_ms + 1` に設定し、OMRON API に対して新しい測定データのみを直接要求します (「全件取得してローカルで差分を取る」方式ではありません)。追記の前には、既存の CSV 行に対する重複排除チェックを防御的に適用します。

`data/weight_data.csv` に既にデータがあるものの `state.json` がまだ存在しない場合 (例: 以前の手動エクスポートをこのツールが置き換えた最初の実行時) は、CSV 内のデバイスごとの最大タイムスタンプから状態をシードします。これにより、既存の履歴が Discord へ再送されることを防ぎます。

## Discord 通知

新規レコードが見つかったときのみ送信します (新しいデータがない場合はメッセージを送りません)。各レコードは 1 つの embed になります。

- **タイトル**: `{weight} kg` (見出しとなる数値)
- **フィールド**: 利用可能な体組成メトリクスごとに 1 つの inline フィールド (BMI、体脂肪率、骨格筋率、内臓脂肪レベル、基礎代謝、体内年齢)
- **タイムスタンプ**: 測定時刻を Discord 自身の `timestamp` フィールドで表示 (各閲覧者のローカル時刻で描画)
- **フッター**: デバイスのモデル名

embed になるのは直近 3 件のレコードのみで、新しい順に並びます。1 回の同期で 3 件を超えるレコードが同期された場合は、追加で保存された件数をプレーンテキストの注記 (`他 N 件も同期済み`) で報告します。

### 送信失敗時の再送

通知対象のレコードは、CSV への追記より先に `data/outbox.json` (未配送レコード) へ保存します。Discord への送信が成功したときだけ outbox を空にするため、webhook の 5xx やタイムアウトで送信に失敗しても、`state.json` (データ同期位置) とは独立して次回以降の同期パスで未配送分がまとめて再送されます。OMRON 側に新しいデータがないパスでも再送します。

Discord に届いたが応答前にタイムアウトした場合は、次回に同じレコードが再送され、通知が重複することがあります (at-least-once)。

## API の詳細 (リバースエンジニアリング)

1. **ログイン**: `POST {server}/oauth2/token` に `{username, password}` と、アカウントのリージョンに対応する OMRON connect アプリを識別する `X-Kii-AppID` / `X-Kii-AppKey` ヘッダーを付与して送信します。ベアラー `access_token` が返されます。
2. **デバイス検出**: `POST {server}/apps/{appId}/server-code/versions/current/synchronizeDeviceConfData` を `lastSyncDate` / `nextPaginationKey` でページングし、登録済みの体重計 / 血圧計プロファイルを列挙します (ここでは `deviceCategory == "1"`、すなわち体重計に絞り込みます)。
3. **測定データ取得**: `POST {server}/apps/{appId}/server-code/versions/current/measureData` をデバイス / ユーザーごとに呼び出します。**このエンドポイント自体が 200 件単位でページングされます**。不透明な `paginationKey` (形式は `"<page>/<pageSize>"`、例: `"1/200"`) が `nextPaginationKey` として返され、これを次の要求に渡します。この挙動は非公開で、ベースにした先行実装 (bugficks/omramin) では実装されていません。省略すると結果が黙って最初の 200 件で頭打ちになるため、このクライアントは `nextPaginationKey` が返らなくなるまでループします。
4. 各測定の `bodyIndexList` は、数値の「ValueType」コード (例: `"257"` = 体重) をキーとして `{value, subtype, scale, measurementId}` のタプルでフィールドを表現します。値は `value * 10**scale` としてデコードし、`subtype` に基づいて単位変換 (g/lb/st → kg) を行います。

日本 (`JP`) アカウント (および `HK`/`KR`/`TW`) は、この「API v1」バックエンド `https://data-jp.omronconnect.com/api` によって提供されます。認証には、そのリージョン向けの公式モバイルアプリに埋め込まれた共有クライアントの `X-Kii-AppID` / `X-Kii-AppKey` ペアを使用します (ユーザーごとの秘密情報ではありません)。

## 参考にしたリポジトリ

- [bugficks/omramin](https://github.com/bugficks/omramin) — v1 API のフロー (`omronconnect.py`) とリージョン / appID テーブルの主な情報源
- [wachl/omron-connect-mcp](https://github.com/wachl/omron-connect-mcp) — v1/v2 認証フローのクロスリファレンス
- [happydev-ca/omron-connect-api](https://github.com/happydev-ca/omron-connect-api) — v2 (Cognito ベース) フローのリファレンス。この JP アカウントには適用されません

## 現在の挙動と制限

- 同期対象は体重・体組成 (`deviceCategory == SCALE`) のデータのみで、血圧計のデータは無視します。
- 各同期パスは毎回ログインし直します。トークンのリフレッシュや長時間セッションの維持は行いません。
- 1 回のパス内での一時的な HTTP エラーはバックオフ付きのリトライを行いません。スケジューラループが失敗をログに記録し、次のインターバルで再試行します。
- webhook が 4xx などの恒久的なエラーを返し続ける場合も、毎パス再送を試み、`data/outbox.json` に未配送レコードが残り続けます。webhook の設定を直すと次回パスで再送されます。
- 未配送の通知 (`data/outbox.json`) が導入される前に失われた通知は復旧しません。`outbox.json` が壊れている場合は同期が失敗するため、手動で修復または削除してください (未送信分は失われます)。

## ライセンス

[MIT License](./LICENSE) の下で公開しています。
