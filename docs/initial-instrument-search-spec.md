# 初期器具検索画面・初期仕様

## 目的

器具撮影システムの初期器具検索画面で、選択対象を識別しやすくする。対象は器具マスタの表示と検索結果に限る。

## 対象範囲

- **対象画面:** セッション内の初期器具検索・宣言画面のみ。
- **変更対象:** Python/FastAPI の器具カタログ/API、および React/TypeScript の同画面。
- **画面表示:** 階層パス中心の表示をやめ、器具の `name`、`name_ja`、`model_number` を表示する。既存の器具ID表示は維持する。階層パスを表示する他画面（選択確認、撮影時の器具選択など）は変更しない。
- **サンプル画像:** 各器具の `data_path.color` を単一のサンプル画像参照として扱い、参照がない場合は `null` とする。検索画面では画像がない状態を明示的に扱う。
- **対象外:** 他画面の表示変更、撮影・タグ付け動作、器具マスタのデータ更新。

## システム要否・技術

| 項目 | 決定 |
|---|---|
| AI開発 | いいえ。学習・評価・推論の要件なし |
| フロントエンド | Yes — React / TypeScript |
| バックエンド/API | Yes — Python / FastAPI |
| マスタDB | SQLite。既定パスは `C:\work\SPD\master\dataset.sqlite` |
| パス上書き | `IC_CATALOG_DB` は引き続き有効とし、指定時は既定パスに優先する |

## API概要

初期検索画面で使用する既存APIを拡張する。

| エンドポイント | 用途・入力 | 応答概要 |
|---|---|---|
| `GET /instruments?q={検索語}&limit={件数}` | 器具一覧の検索。`q` と `limit` は現行の任意パラメーターを維持する | 器具配列。各要素に既存の `instrument_uid` 等に加え、`name`、`name_ja`、`model_number` とサンプル画像の nullable な参照を含める |
| `GET /instruments/{uid}` | 器具1件の取得 | 一覧と同じ器具項目・サンプル画像参照を返す |
| `GET /instruments/{uid}/sample-image` | マスタ画像の取得 | `data_path.color` が指す画像を返す。画像がない、または参照先が存在しない場合は404 |

器具応答には `name_ja`、`model_number`、`sample_image_url` を含める。`model_number` は文字列または `null`、`sample_image_url` は `/instruments/{uid}/sample-image` または `null` とする。画像参照の元データは SQLite の `data_path.color` であり、複数画像リストではなく単一値として扱う。相対画像パスはDBファイルの親フォルダーを基準に解決し、そのフォルダー外は参照できない。画像ファイルが存在しない場合は `sample_image_url: null` とする。画像APIの404およびブラウザーでの取得失敗は画面で画像なしとして扱う。ローカルファイルパスをブラウザーへ渡さない。既存の `/images/{image_id}/file` は撮影画像用とし、マスタ画像には流用しない。

検索条件は既存動作を維持する。既存の `/instruments/reload` の動作は本変更の対象外。

## UI状態・動作

- 初期器具検索画面で既存の検索・選択操作を維持し、結果に `name`、`name_ja`、`model_number` とサンプル画像を表示する。階層パス中心の情報は表示しない。
- `name`、`name_ja`、`model_number` が未設定の場合は「未登録」と表示し、器具IDは引き続き表示する。画像は一覧内のサムネイルとして表示する。
- 検索中、結果あり、該当なし、取得エラーの各状態を扱う。
- `data_path.color` が `null`、または画像を取得・表示できない場合も検索結果自体は表示し、画像なし状態を画面上で示す。
- 選択確認画面・撮影画面を含むその他の既存表示は変更しない。

## 外部契約・次工程

**外部契約変更が必要。** 器具API応答項目の拡張と SQLite マスタの読み取り契約変更がある。実際のDBスキーマを確認し、提供側・利用側、SQLiteのテーブル／カラム／型／必須性、およびデータが読み取り可能となる時点を含む契約書を `docs/contracts/` に新規作成または更新する。

## 受け入れ条件

1. 既定の SQLite パスが `C:\work\SPD\master\dataset.sqlite` であり、`IC_CATALOG_DB` が設定されている場合はその指定を使う。
2. 初期器具検索画面の器具行で `name`、`name_ja`、`model_number` を確認でき、階層パス中心の表示が置き換わっている。
3. APIから器具ごとに単一のサンプル画像参照を受け取れ、画像がない器具は `null` として表現される。画像参照時はAPIが配信し、DB親フォルダー外へのパスは参照できない。
4. サンプル画像がない／表示できない場合でも器具の検索・選択が可能で、画面上で画像なし状態を識別できる。
5. 既存の選択確認画面、撮影時の器具選択など、対象外画面の表示に変更がない。
6. API詳細と外部契約を `docs/contracts/` に反映する。

## 実DBで確認した項目

指定DBの `samples` テーブルに `id`（TEXT、主キー）、`name`（TEXT、NOT NULL）、`name_ja`（TEXT、NOT NULL）、`model_number`（TEXT、NULL許容）、`hierarchy_path`（TEXT、NOT NULL）、`data_path`（TEXT、NOT NULL）がある。`data_path` はJSON文字列で、その `color` は単一の相対PNGパスである。画像ファイルはDB親フォルダーを基準に探索する。契約書には今回の実DBで確認した範囲の列を記載する。
