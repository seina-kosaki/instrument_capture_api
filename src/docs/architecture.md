# 設計メモ

## 1. 疎結合の方針

```
 frontend/ (React + TypeScript) ── HTTP(JSON/JPEG) ──▶ FastAPI
                  ├─ InstrumentCatalog (SQLite → 本番マスタ)
                  ├─ MetadataStore (SQLite → PostgreSQL)
                  ├─ ImageStore (ローカルFS → S3)
                  └─ CameraService → CameraPort → CamlibCamera → camlib
```

| 結合点 | 契約 | 差し替え・独立性 |
|---|---|---|
| React撮影/解析画面 ⇔ API | OpenAPI（`/docs`）。座標は画像サイズで**正規化(0-1)** | フロントのHTTPクライアントと解析機能はTypeScriptに集約 |
| API ⇔ カメラ | `CameraPort`を`CamlibCamera`が実装 | `CameraService`が接続状態と排他制御を管理。SDK importは接続時まで遅延 |
| 撮影画面 ⇔ カメラ | `/camera/status`, `/camera/open`, `/camera/close`, `/camera/preview` | APIがJPEGプレビューを返し、ブラウザはカメラSDKに依存しない |
| 撮影画面 ⇔ 画像保存 | `POST /declarations/{id}/capture` | API内で撮影と既存画像保存を連続実行。画像の再アップロードは不要 |
| API ⇔ 器具マスタ | `InstrumentCatalog` ポート（`list`/`get`/`reload`） | `sample_details`の`id`と`hierarchy_path`を器具ID・階層として利用 |
| API ⇔ 保存先 | `MetadataStore` / `ImageStore` ポート | サービス層はSQLite・FSを知らない |
| 日次サマリー | セッション終了イベントを購読 | レポート処理を外しても撮影機能は無傷 |

APIバックエンドの層（依存は上→下の一方向）:
`api(ルーター/スキーマ)` → `services` → `ports` ← `adapters` ／ `domain`（純粋。他に依存しない）。
具体実装の選択は `main.py`（コンポジションルート）のみ。`create_app()` に各ポート実装を注入できる（`tests/test_decoupling.py`）。

## 2. データモデル

```
Instrument(uid, name, category_path)  ← `sample_details`のSQLiteが正本。階層はIDに含めない
Session → Declaration(candidate_instruments:[uid,name_snapshot], confirmed, arrangement_no) → Image
                                                                                   └→ Hint(InstanceHint) ×N
```
- **Declaration（宣言）**: 撮影対象となり得る器具IDの集合。個数や撮影モードは宣言せず、画像ごとに実際に写ったHintから判断する。確認(`confirm`)前は撮影不可。
- **arrangement_no**: 「配置し直しました」で増える。連写と置き直しを区別し、集計は枚数でなく**配置数**を主指標にする。
- **Image**: 無加工で保存。`tag_status` = untagged / tagged。取得場所、取得時刻、`camera_id.yaml`の名称、カメラ状態は撮影時点の値を保存する。
- **DeclarationItem**: `instrument_uid`に加えて器具名をスナップショット保存し、器具マスタの名称変更後も撮影時表示を維持する。
- **Hint**: `instrument_uid`, `instance_no`（点を打った順にサーバーが採番）, `center`（必須）, `end_a`/`end_b`（任意）, 各点 `status`(visible/estimated), `occluded`, `visible`（画面外=false）, `hint_source`(manual/auto_center/none), `added_after_capture`, `hint_quality`(full/center_only/none)。
  - 画像に対象器具が写らない場合はHintを作成しなくてよい。点を付けずに器具の存在だけ記録する場合は`hint_source=none`を保存する。

## 3. 整合性チェック（保存時エラー／警告）

| 区分 | コード |
|---|---|
| エラー（保存拒否・422） | `UNDECLARED_INSTRUMENT`, `CENTER_REQUIRED`, `NONE_WITH_POINTS`, `INVISIBLE_WITH_POINTS`, `UNKNOWN_INSTRUMENT`, `POINT_OUT_OF_RANGE` |
| 警告（保存可） | `CENTER_NOT_BETWEEN_ENDS`, `ENDS_COINCIDE`, `CLOSE_POINTS`（別器具の中心が近接＝取り違え疑い）, `DUPLICATE_POINT`, `ADDED_AFTER_CAPTURE` |

`POST /images/{id}/tags/validate` は保存せずに同じチェックのみ実行（UIのライブ検証用）。

## 4. API一覧

| メソッド/パス | 内容 |
|---|---|
| `GET /instruments?q=` | 器具検索（全角半角ゆれ吸収） |
| `POST /sessions` / `POST /sessions/{id}/close` | セッション開始/終了（終了時に日次レポート出力） |
| `DELETE /sessions/{id}` | 終了済みセッションのDB・画像バンドルを削除 |
| `POST /sessions/{id}/declarations` | 撮影候補の器具UID集合を宣言（個数指定なし、`copy_from`で候補集合をコピー） |
| `POST /declarations/{id}/confirm` / `rearrange` | 配置確認 / 置き直し（配置番号+1） |
| `GET /camera/status` / `POST /camera/open` / `POST /camera/close` | camlibカメラ状態・接続管理 |
| `GET /camera/preview` | 最新プレビューフレーム（JPEG） |
| `POST /declarations/{id}/capture` | camlib撮影・画像保存（宣言確認とセッション状態を撮影前に検証） |
| `POST /declarations/{id}/images` | 画像アップロード（multipart: file, meta。外部画像取り込み用） |
| `GET /images?tag_status=&session_id=&date=` / `GET /images/{id}` / `GET /images/{id}/file` | 画像一覧・メタ・実体 |
| `DELETE /images/{id}` | SQL行・タグ・同一セッションのraw/debug画像を削除 |
| `GET|PUT /images/{id}/tags` | タグ取得 / 全置換保存 |
| `POST /images/{id}/tags/validate` | ドライラン検証 |
| `POST /instruments/reload` | 器具マスタSQLiteを再読込（API再起動不要） |
| `GET /stats/daily?date=` / `GET /stats/coverage` | 当日集計 / 全体カバレッジ（達成率・次に撮るべき器具） |
| `GET /export/hints?date=` | 解析用: 1タグ=1行のフラットな表（クライアントがCSV化） |
| `GET|POST /reports/daily` | 日次サマリーHTML表示 / ファイル出力（JSON+HTML） |

エラー形式: `{"code","message","details"}`（404 not_found / 409 conflict / 400 invalid_input / 422 tag_validation_failed）。

## 5. 集計の考え方
- 常に元データから都度計算（集計値は保存しない）。
- 器具ごと: 実際にタグ付けされた画像数・インスタンス数・遮蔽数・Hint数から判定した単体/複数の**配置数**・セッション数・達成率。
  達成率 = (min(単体配置, 目標) + min(複数配置, 目標)) / (目標合計)。
- 日次サマリーは「セッション終了」「`POST /reports/daily`」「API停止時」の3経路で出力（異常終了対策）。

## 6. セッションバンドル保存

```text
<IC_DATA_DIR>/YYYY-MM-DD/<session_id>/
├─ metadata.sqlite3       # このセッションの撮影・タグメタデータ
├─ raw/<image_id>.<ext>   # 撮影原本
├─ depth/<image_id>.*     # 任意の深度画像
└─ debug/<image_id>.jpg   # タグを重ねた再生成可能な画像
```

- 日付はセッション開始日で固定し、日付をまたいでも同一バンドルに格納する。
- `Image.meta`はスキーマバージョン付きJSONで可変のカメラ設定を保持し、検索対象のcamera_name/status/location等は列にも保存する。
- 撮影・タグのメタデータはセッションDBだけを正本とする。バンドル削除で撮影メタデータ・画像・debug画像をまとめて除去する。
- `IC_DATA_DIR`の既定はSPD直下の`shared_data/`。旧データを移行する場合は`IC_LEGACY_DATA_DIR`で移行元を明示し、既定ではコピーしない。
- SAM3承認状態とセッションsplitは各セッションDBに保存する。
- RGB・depth・debugのファイルは日付/セッションフォルダーに残し、DBにはデータルート相対パスを保存する。

## 7. 未実装・次の検討事項
- **認証/認可・監査ログ**（現状なし。医療環境での運用前に必須。CORSも限定すること）
- 実マスタ（チーム作成の登録処理の出力）への `InstrumentCatalog` アダプタ追加。`status=deprecated` は宣言不可として対応済み
- React画面のユーザビリティ確認、TypeScript API型のOpenAPI生成への移行
- 連写時の「直前タグのコピー」（`copied_from_image_id`、目視確認必須）
- 点→SAM等によるmask/bbox自動生成と `Annotation`（source, review_status）
- 学習データセット出力（階層バージョン指定での展開、セッション単位のtrain/val/test分割）
- 患者情報・手術室の映り込み防止ルールの運用設計
- 大規模化時の集計キャッシュ、SQLiteからの移行
