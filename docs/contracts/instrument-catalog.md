# 器具マスタ・API契約

## 提供側と利用側

- **SQLiteデータ提供側:** SPDの器具マスタ。既定ファイルは `C:\work\SPD\master\dataset.sqlite`。
- **SQLite/API利用側:** `instrument_capture_api` のFastAPIバックエンド。`IC_CATALOG_DB` が設定されている場合はそのファイルを使用する。
- **API利用側:** 初期器具検索画面などのHTTPクライアント。
- FastAPIはマスタSQLiteを `mode=ro` で開く。マスタデータはAPI起動時にメモリへ読み込まれ、`POST /instruments/reload` 成功後に更新される。画像ファイルの存在は一覧・詳細・画像要求ごとに確認する。
- 実DBの列定義は `C:\work\SPD\master\dataset.sqlite` のSQLite `PRAGMA table_info` で確認した。以下は確認時点の定義であり、未確認の制約・業務上の意味は補っていない。

## SQLiteスキーマ

「必須」はSQLite列定義の `NOT NULL` を示す。主キーは `PK` 欄に示す。SQLite型は実DBに記録された型名である。

### `samples`

| 列 | SQLite型 | 必須 | PK | 備考 |
|---|---|---:|---:|---|
| `id` | TEXT | いいえ | 1 | 主キー |
| `name` | TEXT | はい | — | |
| `model_number` | TEXT | いいえ | — | |
| `place` | TEXT | いいえ | — | |
| `date` | TEXT | いいえ | — | |
| `occluded` | TEXT | はい | — | |
| `overlapping` | TEXT | はい | — | |
| `camera` | TEXT | いいえ | — | |
| `camera_mount` | TEXT | いいえ | — | |
| `height` | REAL | いいえ | — | |
| `size` | REAL | いいえ | — | |
| `sync_group_id` | TEXT | いいえ | — | |
| `status` | TEXT | いいえ | — | |
| `hierarchy_path` | TEXT | はい | — | |
| `hierarchy` | TEXT | はい | — | |
| `data_path` | TEXT | はい | — | JSON文字列。画像APIは `color` を参照する |
| `annotations` | TEXT | はい | — | |
| `created_at` | TEXT | はい | — | |
| `updated_at` | TEXT | はい | — | |
| `name_ja` | TEXT | はい | — | DB定義の既定値は空文字列 |

### `version_samples`

| 列 | SQLite型 | 必須 | PK | 備考 |
|---|---|---:|---:|---|
| `version` | TEXT | はい | 1 | |
| `id` | TEXT | はい | 2 | |
| `snapshot` | TEXT | はい | — | |

`version` と `id` の複合主キー。

### `versions`

| 列 | SQLite型 | 必須 | PK | 備考 |
|---|---|---:|---:|---|
| `version` | TEXT | いいえ | 1 | 主キー |
| `created_at` | TEXT | はい | — | |
| `note` | TEXT | いいえ | — | |
| `sample_count` | INTEGER | はい | — | |
| `snapshot_sha256` | TEXT | はい | — | |

APIは `samples` のみを読み込み、`version_samples` と `versions` は読み書きしない。カタログ読み込みで必須とする列は `samples.id`, `name`, `name_ja`, `model_number`, `hierarchy_path`, `data_path`。`status` は現在の器具APIの互換性を保つため、API側では全レコードを `active` として扱う。

確認時点の `samples` は12行で、`id` の重複はなかった。`data_path` はJSON文字列、`color` は単一の相対PNGパスとして確認し、DB親フォルダー基準で解決した画像ファイルは12件中5件存在した。画像の存在数は更新され得るため契約値として固定しない。

## HTTP API

### `GET /instruments?q={検索語}&limit={件数}`

既存の検索条件を維持する。応答は器具配列であり、各要素は少なくとも次を含む。

| フィールド | 型 | 説明 |
|---|---|---|
| `instrument_uid` | string | `samples.id` |
| `name` | string | `samples.name` |
| `name_ja` | string | `samples.name_ja` |
| `model_number` | string \| null | `samples.model_number` |
| `sample_image_url` | string \| null | 画像が実在する場合は `/instruments/{uid}/sample-image` |
| `category_path` | string | `samples.hierarchy_path` |
| `category_levels` | string[] | `category_path` の階層要素 |
| `status` | string | 現行互換の `active` |

### `GET /instruments/{uid}`

指定した器具を1件返す。応答フィールドは一覧APIと同じ。器具がなければ404。

### `GET /instruments/{uid}/sample-image`

`samples.data_path` のJSONにある文字列 `color` をSQLiteファイルの親フォルダーからの相対パスとして解決し、画像ファイルを配信する。親フォルダー外へ解決するパス（絶対パス、`..` による脱出、外部を指すシンボリックリンクを含む）は配信しない。参照がない、不正、親フォルダー外、またはファイルが存在しない場合は404。ローカルファイルパスはAPI JSONに含めない。

`sample_image_url` は応答生成時点のファイル存在に基づく。ファイルが応答生成後に削除された場合、画像APIは404を返し得る。

### `POST /instruments/reload`

SQLiteの再読み込み完了後、以降の一覧・詳細APIに新しい器具データを反映する。画像ファイルの有無は各リクエスト時に確認する。

### `GET /stats/coverage` / `GET /stats/daily?date={日付}`

どちらの応答も `instruments` 配列の各行に以下の器具マスタ情報を含む。既存の集計項目・計算結果は変更しない。

| フィールド | 型 | 説明 |
|---|---|---|
| `name_ja` | string | `samples.name_ja` |
| `model_number` | string \| null | `samples.model_number` |
| `sample_image_url` | string \| null | サンプル画像が利用可能な場合は `/instruments/{uid}/sample-image`。参照がない、または画像を利用できない場合は `null` |

`name_ja` と `model_number` は同じ器具カタログから取得する。`/stats/coverage` は全器具の行を返し、`/stats/daily` は従来どおり当日の集計対象器具の行を返す。
