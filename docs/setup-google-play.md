# Google Play Developer APIの設定方法

Google Play Developer APIを使用するには、Google Cloud Service Accountの設定と、Play ConsoleへのService Account招待が必要です。

## 手順

### 1. Google Cloud Console でプロジェクトを用意

[Google Cloud Console](https://console.cloud.google.com) を開き、適切なプロジェクトを選択または作成します。

### 2. Google Play Android Developer API を有効化

「APIとサービス > ライブラリ」から「Google Play Android Developer API」を検索して有効化します。

### 3. Service Account を作成

「IAMと管理 > サービスアカウント」を開き、「サービスアカウントを作成」をクリックします。

- **サービスアカウント名**: 任意（例: `appreview-insight`）
- **説明**: 任意（例: `AppReview Insight review fetcher`）
- ロールの付与は不要です（次のステップでPlay Consoleから権限付与します）

### 4. JSON キーファイルを発行

作成したService Accountの詳細を開き、「キー」タブで「鍵を追加 > 新しい鍵を作成」をクリックします。形式は「JSON」を選択します。

ダウンロードしたJSONファイルを `./secrets/` ディレクトリに配置します：

```bash
mkdir -p secrets
mv ~/Downloads/service-account-xxxx.json secrets/service-account.json
```

`.env` に設定します：

```env
GOOGLE_PLAY_SERVICE_ACCOUNT_JSON=./secrets/service-account.json
```

### 5. Play Console に Service Account を招待 ← **最も忘れやすい手順**

> ⚠️ **この手順を忘れると `403 Forbidden` エラーが発生します。**

[Google Play Console](https://play.google.com/console) を開き、画面左側の「ユーザーと権限 (Users and permissions)」をクリックします。

「新しいユーザーを招待」をクリックして、手順3で作成したService Accountのメールアドレス（例: `appreview-insight@your-project.iam.gserviceaccount.com`）を入力します。

**権限の設定:**
「アプリへのアクセス権」タブで、対象アプリを選択して以下の権限を付与します：
- 「アプリ情報の表示と一括レポートのダウンロード (View app information and download bulk reports)」
- 「返信の表示と返信 (Reply to reviews)」

「招待を送信」をクリックして完了です。

### 6. 動作確認

```bash
appreview doctor
```

## 重要な制約事項

Google Play Developer APIの `/reviews` エンドポイントは**過去7日分のレビューしか返しません**。データの欠損を防ぐため、`appreview run` を**毎日実行することを強く推奨します**。

```bash
# cronの例（毎日朝9時）
0 9 * * * cd /path/to/project && appreview run --quiet
```
