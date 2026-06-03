# プロンプトのカスタマイズ

appreview-insight のLLMプロンプトは Jinja2 テンプレート形式で記述されており、カスタマイズ可能です。

## テンプレートファイルの場所

| ファイル | 用途 |
|---------|------|
| `src/appreview/prompts/classify.md` | レビュー分類プロンプト |
| `src/appreview/prompts/suggest.md` | クラスタリング・改善提案プロンプト |

## カスタマイズ方法

1. テンプレートファイルをプロジェクトディレクトリにコピーします：

```bash
cp src/appreview/prompts/classify.md ./my-classify.md
cp src/appreview/prompts/suggest.md ./my-suggest.md
```

2. テンプレートを編集します（詳細は下記の変数一覧を参照）。

3. `appreview.yaml` でカスタムテンプレートパスを指定する機能は現時点（v0.1）では未実装です。現在は `src/appreview/prompts/` のファイルを直接編集してください。

## Jinja2変数一覧

### classify.md

| 変数 | 型 | 説明 |
|-----|-----|------|
| `{{ categories }}` | `list[str]` | 分類カテゴリ名のリスト |
| `{{ reviews }}` | `list[dict]` | レビューオブジェクトのリスト |
| `{{ reviews[i].id }}` | `str` | レビューID |
| `{{ reviews[i].rating }}` | `int` | 星評価（1-5） |
| `{{ reviews[i].title }}` | `str` | レビュータイトル（App Storeのみ） |
| `{{ reviews[i].body }}` | `str` | レビュー本文（PII済） |

### suggest.md

| 変数 | 型 | 説明 |
|-----|-----|------|
| `{{ category }}` | `str` | 分析対象のカテゴリ名 |
| `{{ reviews }}` | `list[dict]` | ネガティブレビューのリスト |
| `{{ reviews[i].id }}` | `str` | レビューID |
| `{{ reviews[i].rating }}` | `int` | 星評価 |
| `{{ reviews[i].body }}` | `str` | レビュー本文 |
| `{{ reviews[i].version }}` | `str` | アプリバージョン |

## カスタムカテゴリの追加

`appreview.yaml` の `analysis.categories` を編集します：

```yaml
analysis:
  categories:
    - performance
    - ui_ux
    - feature_request
    - bug_crash
    - billing
    - auth
    - notification
    - onboarding      # ← 追加
    - localization    # ← 追加
    - other           # ← 必須（削除不可）
```

カテゴリを追加したら、`classify.md` のプロンプトにそのカテゴリの説明を追記すると分類精度が向上します。

## 日本語対応のプロンプト例

英語と日本語のレビューが混在する場合、プロンプトに明示的な指示を加えると効果的です：

```markdown
Analyze the reviews in their original language.
For the output JSON, use the exact category names provided (in English).
Your suggestions should be written in the same language as the review body.
```
