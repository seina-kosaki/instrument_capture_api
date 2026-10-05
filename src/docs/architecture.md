# 設計メモ

## 1. 疎結合の方針

```
 撮影アプリ ──┐                          ┌─ InstrumentCatalog  (CSV → 本番マスタへ差替)
 (apps/capture)│  HTTP(JSON/multipart)    ├─ MetadataStore      (SQLite → PostgreSQL)
              ├──────────▶  API  ───────┤
 タグ付けUI ──┘            (services)     └─ ImageStore         (ローカルFS → S3)
 (apps/tagger)  ▲
      └─ 撮影アプリとは iframe + postMessage（または単独起動）
```

| 結合点 | 契約 | 差し替え・独立性 |
|---|---|---|
| クライアント ⇔ API | OpenAPI（`/docs`）。座標は画像サイズで**正規化(0-1)** | 各アプリは自前の `api.js` を持つ（共有コードなし）。別実装のUI/アプリに置換可 |
| 撮影アプリ ⇔ タグ付けUI | URL（`?api&image&embed=1`）＋ `postMessage({source:'instrument-tagger', type:'saved'|'cancel', image_id})` | どちらも単独で動作。タグ付けUIは別端末・別時間でも使える |
| 撮影アプリ ⇔ カメラ | `CameraSource`（`start`/`capture`/`stop`）。実装: Webcam / Mock / File | 産業用カメラ等は同インターフェースの実装を足すだけ |
| API ⇔ 器具マスタ | `InstrumentCatalog` ポート（`list`/`get`） | CSVの未知列は無視。本番マスタCSV（status, end_a定義など）が来ても読める |
| API ⇔ 保存先 | `MetadataStore` / `ImageStore` ポート | サービス層はSQLite・FSを知らない |
| 日次サマリー | `CaptureService` のセッション終了イベントを購読 | レポート処理を外しても撮影機能は無傷 |

APIバックエンドの層（依存は上→下の一方向）:
`api(ルーター/スキーマ)` → `services` → `ports` ← `adapters` ／ `domain`（純粋。他に依存しない）。
具体実装の選択は `main.py`（コンポジションルート）のみ。`create_app()` に各ポート実装を注入できる（`tests/test_decoupling.py`）。

## 2. データモデル

```
Instrument(uid, name, category_path)  ← CSVが正本。階層はIDに含めない
Session → Declaration(items:[uid,count], confirmed, arrangement_no) → Image
                                                                  └→ Hint(InstanceHint) ×N
```
- **Declaration（宣言）**: 並べる器具と個数。`mode` は `single`（1器具1個）/ `multi`。確認(`confirm`)前は撮影不可。
- **arrangement_no**: 「配置し直しました」で増える。連写と置き直しを区別し、集計は枚数でなく**配置数**を主指標にする。
- **Image**: 無加工で保存。`tag_status` = untagged / tagged。
- **Hint**: `instrument_uid`, `instance_no`（点を打った順にサーバーが採番）, `center`（必須）, `end_a`/`end_b`（任意）, 各点 `status`(visible/estimated), `occluded`, `visible`（画面外=false）, `hint_source`(manual/auto_center/none), `added_after_capture`, `hint_quality`(full/center_only/none)。
  - 単体撮影の「点なし」は NULL でなく `hint_source=none` を**明示的に保存**（入力忘れと区別）。

## 3. 整合性チェック（保存時エラー／警告）

| 区分 | コード |
|---|---|
| エラー（保存拒否・422） | `COUNT_MISMATCH`, `UNDECLARED_INSTRUMENT`, `CENTER_REQUIRED`, `NONE_NOT_ALLOWED`, `NONE_WITH_POINTS`, `INVISIBLE_WITH_POINTS`, `UNKNOWN_INSTRUMENT`, `POINT_OUT_OF_RANGE` |
| 警告（保存可） | `CENTER_NOT_BETWEEN_ENDS`, `ENDS_COINCIDE`, `CLOSE_POINTS`（別器具の中心が近接＝取り違え疑い）, `DUPLICATE_POINT`, `ADDED_AFTER_CAPTURE` |

`POST /images/{id}/tags/validate` は保存せずに同じチェックのみ実行（UIのライブ検証用）。

## 4. API一覧

| メソッド/パス | 内容 |
|---|---|
| `GET /instruments?q=` | 器具検索（全角半角ゆれ吸収） |
| `POST /sessions` / `POST /sessions/{id}/close` | セッション開始/終了（終了時に日次レポート出力） |
| `POST /sessions/{id}/declarations` | 宣言作成（`copy_from` で前回宣言をコピー） |
| `POST /declarations/{id}/confirm` / `rearrange` | 配置確認 / 置き直し（配置番号+1） |
| `POST /declarations/{id}/images` | 画像アップロード（multipart: file, meta） |
| `GET /images?tag_status=&session_id=&date=` / `GET /images/{id}` / `GET /images/{id}/file` | 画像一覧・メタ・実体 |
| `GET|PUT /images/{id}/tags` | タグ取得 / 全置換保存 |
| `POST /images/{id}/tags/validate` | ドライラン検証 |
| `POST /images/{id}/tags/from-declaration` | 単体撮影: 宣言をそのままラベル確定（点なし） |
| `GET /stats/daily?date=` / `GET /stats/coverage` | 当日集計 / 全体カバレッジ（達成率・次に撮るべき器具） |
| `GET|POST /reports/daily` | 日次サマリーHTML表示 / ファイル出力（JSON+HTML） |

エラー形式: `{"code","message","details"}`（404 not_found / 409 conflict / 400 invalid_input / 422 tag_validation_failed）。

## 5. 集計の考え方
- 常に元データから都度計算（集計値は保存しない）。
- 器具ごと: 画像数・インスタンス数・遮蔽数・単体/複数の**配置数**・セッション数・達成率。
  達成率 = (min(単体配置, 目標) + min(複数配置, 目標)) / (目標合計)。
- 日次サマリーは「セッション終了」「`POST /reports/daily`」「API停止時」の3経路で出力（異常終了対策）。

## 6. 未実装・次の検討事項
- **認証/認可・監査ログ**（現状なし。医療環境での運用前に必須。CORSも限定すること）
- 実マスタ（チーム作成の登録処理の出力）への `InstrumentCatalog` アダプタ追加。`status=deprecated` は宣言不可として対応済み
- 連写時の「直前タグのコピー」（`copied_from_image_id`、目視確認必須）
- 点→SAM等によるmask/bbox自動生成と `Annotation`（source, review_status）
- 学習データセット出力（階層バージョン指定での展開、セッション単位のtrain/val/test分割）
- 患者情報・手術室の映り込み防止ルールの運用設計
- 大規模化時の集計キャッシュ、SQLiteからの移行
