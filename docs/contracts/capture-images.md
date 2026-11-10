# 撮影画像API契約

撮影画面のReact / TypeScriptクライアントとPython / FastAPI間で、撮影画像・タグ・画像単位削除に使用するAPI契約を示す。保存先は `IC_DATA_DIR` 以下の日付・セッション単位のバンドルで、画像メタデータの正本は `metadata.sqlite3`。

## 対象API

### `POST /declarations/{declaration_id}/capture`

宣言IDをパスで受け取り、リクエストボディなしで撮影する。成功時は `201` と `ImageOut` を返す。応答項目は `image_id`、`declaration_id`、`session_id`、`arrangement_no`、`width`、`height`、`content_type`、`sha256`、`captured_at`、`meta`、`tag_status`、`tag_revision`、`tagged_at`、`tagged_by`、`camera_name`、`camera_status`、`location`、`relative_path`、`file_url`、`depth_path`（未取得時は `null`）。RGBは撮影画像の本体、深度画像は取得できた場合のみ保存される。

### `GET /images/{image_id}/file`

画像IDに対応するRGBファイルを返す。コンテンツタイプは画像レコードの `content_type` に従う。ローカル保存パスをクライアントへ渡す契約ではない。

### `GET /images/{image_id}/tags`

画像IDを指定してタグ配列を取得する。各タグには `instrument_uid`、`instance_no`、`visible`、`hint_source`、`hint_quality`、`center`、`end_a`、`end_b`、`occluded`、`added_after_capture` を含む。各点は `x`、`y`（0〜1の正規化値）と `status` を持ち、未設定点は `null`。

### `PUT /images/{image_id}/tags`

以下を含むJSONを受け取る。

- `hints`: タグ配列（必須）。各要素は `instrument_uid`（必須）と、任意の `hint_source` / `visible` / `center` / `end_a` / `end_b` / `occluded` / `added_after_capture` を持つ。点は0〜1の `x` / `y` と `status` を持つ。`center` / `end_a` / `end_b` は未設定時 `null`。
- `tagged_by`: 任意の文字列。既定値は空文字列。

成功時は `TagsOut`（`image_id`、保存後のタグ配列、`errors`、`warnings`）を返す。タグ要素は `instrument_uid`、`instance_no`、`visible`、`hint_source`、`hint_quality`、`center`、`end_a`、`end_b`、`occluded`、`added_after_capture` を含む。保存後は `images.tag_status` が `tagged` となる。無効入力時は既存のAPIエラー契約に従う。

### `DELETE /images/{image_id}`

画像ID単位で削除する。リクエストボディなし。成功時は `204 No Content`、画像が存在しない場合は `404`。

成功時に削除する対象:

1. `images.path` が指すRGB実ファイル。
2. `images.depth_path` が非NULLの場合、その深度実ファイル。
3. 対象画像IDの `debug/{image_id}.jpg`（存在する場合）。
4. 所有するセッションの `metadata.sqlite3` にある `images` 行、`hints` 行、および `annotation_revisions` の対象 `session_id` / `image_id` 行。

画像IDに紐づくデータを削除し、SQL上に対象行を残さない。画像ファイルの実パスはDBに記録された相対パスを基準とし、拡張子をクライアント側で推測しない。セッション、宣言、他の画像、セッション単位の `session_splits` は削除対象ではない。ファイルやDBの削除に失敗した場合、成功の204を返してはならない。部分失敗時の補償・再試行方式は未確定。

## 対象外

- 撮影履歴は現行画面が当該セッション内で保持する撮影応答の一覧であり、この契約は履歴一覧APIを追加しない。
- セッション一括削除、レポート更新、`annotation_revisions` が参照する可能性のある外部マニフェスト・注釈ファイルの所有権は本契約で定めない。
