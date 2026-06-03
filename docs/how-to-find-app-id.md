# App ID / Package Name の確認方法

## iOS App Store の App ID（数値）

App Store Connect でのApp IDは数値形式（例: `1234567890`）です。

**確認方法：**

1. [App Store Connect](https://appstoreconnect.apple.com) にサインインします
2. 「マイApp (My Apps)」をクリックして対象のアプリを選択します
3. 「アプリ情報 (App Information)」タブを開きます
4. 「一般情報 (General Information)」セクションの「Apple ID」という項目に数値が表示されます

あるいは、App StoreのアプリページURLから確認することもできます。URLの形式は以下の通りです：

```
https://apps.apple.com/jp/app/アプリ名/id**1234567890**
```

`id` の後の数字がApp IDです。

`appreview.yaml` に設定する際は文字列として記述します：

```yaml
apps:
  - name: "My iOS App"
    source: app_store
    app_id: "1234567890"  # ← ここに数値をそのまま記述
```

## Android Google Play の Package Name

Package Nameはリバースドメイン形式の文字列です（例: `com.example.myapp`）。

**確認方法1 — Play Console から：**

1. [Google Play Console](https://play.google.com/console) を開きます
2. 左側の「アプリ一覧」から対象のアプリをクリックします
3. 画面上部のURLを確認すると、以下の形式になっています：
   ```
   https://play.google.com/console/u/0/developers/xxxx/app/**com.example.myapp**/app-dashboard
   ```
   URLの `/app/` と `/app-dashboard` の間の文字列がPackage Nameです。

**確認方法2 — Google Playストアから：**

Google PlayのアプリページURLを確認します：

```
https://play.google.com/store/apps/details?id=**com.example.myapp**
```

`id=` の後の文字列がPackage Nameです。

**確認方法3 — APKファイルから：**

```bash
aapt dump badging your-app.apk | grep package:
```

`appreview.yaml` に設定する際：

```yaml
apps:
  - name: "My Android App"
    source: google_play
    package_name: "com.example.myapp"  # ← ここにPackage Nameを記述
```
