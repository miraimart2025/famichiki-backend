# famichiki-backend

函館エリアのファミチキ販売数を時間帯ごとに予測する FastAPI バックエンドです。学習済みの XGBoost モデルに気象情報、祝日判定、給料日フラグを組み合わせ、最大 8 時間分の需要予測を返します。クライアントからのボタンクリックは Google スプレッドシートに記録されます。

## 主な機能
- FastAPI 製 REST API。ブラウザからのアクセスを想定して CORS を許可。
- `model.json` に保存された XGBoost Booster を用いた時間帯別売上予測。
- OpenWeather API を利用した最新の函館の気象データ取得。
- `jpholiday` による日本の祝日判定と 10・25 日の給料日フラグ付与。
- Google サービスアカウント経由でのスプレッドシートへの操作ログ保存。

## 必要環境
- Python 3.10 以上（モデル作成時のバージョンに合わせると安全です）
- OpenWeather API キー
- Google サービスアカウント（`famichiki` という名前のスプレッドシートに編集権限を付与）

## セットアップ
1. 仮想環境を作成して依存関係をインストールします。

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. プロジェクトルートに `.env` ファイルを作り、以下の環境変数を設定します。

   ```ini
   OPENWEATHER_API_KEY=your_openweather_api_key
   GOOGLE_SERVICE_ACCOUNT_JSON={"type":"service_account","project_id":"..."}
   ```

   - `GOOGLE_SERVICE_ACCOUNT_JSON` は 1 行の JSON 文字列にします。`cat credentials.json | jq -c` などで整形して貼り付けてください。
   - サービスアカウントのメールアドレスを対象のスプレッドシートと共有します。

3. 学習済みモデル `model.json` を `main.py` と同じディレクトリに配置します。

## サーバーの起動
開発環境で起動する場合は以下を実行します。

```bash
uvicorn main:app --reload
```

デフォルトでは `http://127.0.0.1:8000` で待ち受けます。

## API エンドポイント

### `POST /log_button_click`
ボタンクリックをスプレッドシートに記録します。

- リクエストボディ例: `{ "button_name": "evening_batch" }`
- レスポンス例: `{ "status": "success", "message": "evening_batch logged at 2024-05-01 18:02:11" }`

### `GET /predict`
現在の日本標準時 (JST) を基準に、先の 8 時間分の予測を返します。

- レスポンス例:

```json
{
  "predictions": [
    { "hour": "14", "predicted_sales": 42 },
    { "hour": "15", "predicted_sales": 38 }
  ]
}
```

### `GET /predict_at`
指定した日時を基点に 8 時間分の予測を行います。

- クエリパラメータ
  - `date`: `YYYY-MM-DD`
  - `hour`: 0〜23 の整数
- レスポンス例:

```json
{
  "predictions": [
    { "datetime": "2024-05-01 10:00", "predicted_sales": 41.5 },
    { "datetime": "2024-05-01 11:00", "predicted_sales": 43.2 }
  ]
}
```

## 開発メモ
- すべての日時は `Asia/Tokyo` タイムゾーンで処理しています。
- OpenWeather から取得する気温は摂氏 (℃) ですが、モデル入力の都合でケルビンに変換しています。
- 祝日判定は `jpholiday` に依存し、毎月 10 日と 25 日を給料日としてフラグを立てています。

Happy forecasting!
