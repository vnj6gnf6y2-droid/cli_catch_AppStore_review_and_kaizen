# App Store Connect APIキーの取得方法

App Store Connect APIを使用するには、API認証キーが必要です。このドキュメントでは、キーの発行手順を説明します。

## 手順

### 1. App Store Connect にアクセス

[App Store Connect](https://appstoreconnect.apple.com) にApple IDでサインインします。

### 2. 「ユーザーとアクセス」を開く

画面上部のナビゲーションから「ユーザーとアクセス (Users and Access)」をクリックします。

### 3. 「インテグレーション」タブを選択

画面上部のタブから「インテグレーション (Integrations)」を選択します。

### 4. 「App Store Connect API」を選択

左側のサイドバーから「App Store Connect API」をクリックします。

### 5. 新しいキーを作成

「+」ボタンをクリックして新しいAPIキーを作成します。

- **名前**: 任意の識別名（例：「appreview-insight」）
- **アクセス**: 「Developer」以上を選択してください。「Admin」でも動作しますが、最小権限の原則から「Developer」を推奨します。

### 6. キー情報をメモ

キーが作成されると以下の情報が表示されます。必ずメモしてください：

- **Key ID** (例: `XXXXXXXXXX`): `.env` の `APP_STORE_KEY_ID` に設定します
- **Issuer ID** (例: `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`): `.env` の `APP_STORE_ISSUER_ID` に設定します

### 7. 秘密鍵ファイル (.p8) をダウンロード

「APIキーをダウンロード (Download API Key)」ボタンをクリックして `.p8` ファイルをダウンロードします。

> **⚠️ 重要な注意点:**
> - `.p8` ファイルは**一度しかダウンロードできません**。ダウンロード後は安全な場所に保管してください。
> - ダウンロードしてしまった後でページを離れると、再ダウンロードはできません。紛失した場合は新しいキーを発行してください。

### 8. .p8 ファイルを配置

ダウンロードした `.p8` ファイルを `./secrets/` ディレクトリに配置します：

```bash
mkdir -p secrets
mv ~/Downloads/AuthKey_XXXXXXXXXX.p8 secrets/
```

`.env` に以下を設定します：

```env
APP_STORE_PRIVATE_KEY_PATH=./secrets/AuthKey_XXXXXXXXXX.p8
```

## チームで利用する場合

複数人で同じAPIキーを共有するのではなく、「App Store Connect API」画面で各開発者が自分のキーを発行することを推奨します。組織レベルの自動化（CI/CDなど）では、「チームキー」を使用してください。

## 動作確認

設定後、以下のコマンドで接続を確認できます：

```bash
appreview doctor
```
