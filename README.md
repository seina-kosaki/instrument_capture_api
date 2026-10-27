# 器具撮影・タグ付けシステム（PoC）— FastAPI + React

手術器械の画像データ収集と、撮影時の簡易タグ付け（点クリック＋器具ID）を行う。APIとcamlib制御はPython/FastAPI、画面はReact + TypeScript。

```
instrument-capture/
├─ frontend/                    React + TypeScript（Vite）
├─ src/backend/app/             FastAPI・業務処理・camlibアダプター
├─ src/backend/tests/           API・業務フローテスト
├─ src/config/hardware/         camlibカメラ設定
├─ src/master/                  器具マスタCSV
└─ src/docs/                    アーキテクチャ設計メモ
```

## 起動

```bash
# 1) APIサーバー（カメラ接続PC）
uv sync
uv run uvicorn app.asgi:app --app-dir src/backend --host 127.0.0.1 --port 8001

# 2) React画面（Node.js 22 LTS、別ターミナル）
cd frontend
npm install
npm run dev
```

- ブラウザで http://127.0.0.1:5173 を開く
- API接続先を変更する場合は `frontend/.env.local` に `VITE_API_PROXY_TARGET=http://127.0.0.1:8001` を設定（開発中はVite経由でAPIへ接続）
- APIサーバーはカメラ接続PCで起動し、ReactはHTTP API経由でcamlibを操作する
- API仕様の確認・手動実行: http://localhost:8001/docs

## 機能と対応画面

| やりたいこと | 場所 |
|---|---|
| マスタCSVとの連携 | APIが`IC_CATALOG_CSV`（既定`src/master/instruments_mock.csv`）を読む。CSV更新後は`POST /instruments/reload`で反映（API再起動不要） |
| 撮影前の対象物・情報の事前登録 | セッション（撮影者・場所・照明・カメラ型番）＋宣言（撮影候補となる器具の種類）＋配置確認 |
| カメラ接続・プレビュー・撮影 | FastAPIの`/camera/*` APIがcamlibだけを使用。設定は`src/config/hardware/` |
| 撮影後のタグ付け | 器具を選び、画像上で 中心 → 端点A → 端点B をクリック（端点は省略可） |
| 解析 | React画面の「解析」ビューで達成状況・次に撮影する器具・日次集計・CSV出力・日次HTMLレポートを操作 |

## カメラ設定
取得カメラ名は`camera_id.yaml`の`cameras`キーを採用する。カメラが1台なら自動選択し、複数台の場合は`IC_CAMERA_NAME`にキー名を指定する。画像バッファ名は`IC_CAMERA_BUFFER`（既定`color`）、パラメータYAMLとデバイスID YAMLは`IC_CAMERA_PARAM_YAML` / `IC_CAMERA_ID_YAML`で変更できる。カメラ操作と画像保存はAPI内で行い、ブラウザからSDKを直接呼び出さない。

撮影時はRGBに加えて`depth`バッファの取得を試みます。空でない2次元の整数・浮動小数点配列に対応し、`uint8`・`uint16`はPNG、それ以外はTIFFで保存します。深度値の正規化やビット数を落とす変換は行わず、浮動小数点の小数部・NaN・無限大も保持します。取得した型と保存形式は`meta.depth_dtype`・`meta.depth_content_type`へ記録します。depth非対応・未取得・形式不正の場合はRGBのみで撮影を継続します。RGBとdepthは順次取得するため、同一時刻のフレームである保証はありません。SDKが時刻を返す場合は`meta.timestamp`と`meta.depth_timestamp`にそれぞれ記録します。

独自の`CameraPort`実装を注入する場合、`capture()`は従来のタプルではなく`CameraCapture(data, meta, depth_data=None, depth_content_type="image/png")`を返します。TIFFの深度画像を渡す場合は`depth_content_type="image/tiff"`を指定します。

## 保存データ
保存単位はセッションです。セッション開始日の下にセッションIDフォルダーを作り、SQLメタデータ、生画像、タグ付きデバッグ画像をまとめます。

```text
data/YYYY-MM-DD/<session_id>/
├─ metadata.sqlite3
├─ raw/<image_id>.<ext>
├─ depth/<image_id>.png または <image_id>.tiff
└─ debug/<image_id>.jpg
```

`session_id`は`session_HHMMSS_microseconds_<random>`形式です。日付は親フォルダーが持つためIDには含めず、同じ日付フォルダー内では名前順がおおむね開始時刻順になります。

メタデータには撮影時点の器具ID/名称、画像相対パス、タグ状態、撮影場所、取得時刻、camera_id.yamlの名称、カメラ状態を保存します。RGBの相対パスは`images.path`、深度画像の相対パスは`images.depth_path`に保存し、depth未取得時は`NULL`になります。既存のセッションDBは読み込み時に`depth_path`列を自動追加し、既存レコードを維持します。撮影・画像取得・一覧APIの応答にも`depth_path`を含めます。

カメラ設定など増減する項目は`meta_json`にスキーマバージョン付きで格納します。画像を1件削除する場合は`DELETE /images/{image_id}`を利用し、SQL行・タグ・raw/depth/debug画像をまとめて削除します。

初回起動時、旧`meta.sqlite3`と旧画像領域が存在する場合はセッション単位にコピー移行します。移行元は自動削除せず残すため、移行後に確認してから手動で保管/削除してください。

## 撮影の流れ
1. セッション開始（カメラ接続PC上のFastAPIがcamlibを管理）
2. 今回の撮影候補となる器具を検索して宣言（個数は指定しない）
3. 器具を並べ、宣言リストと実物を照合 → チェック → 撮影へ（確認前は撮影不可）
4. 撮影（生画像は即保存）→ 写っている器具と個数に応じてタグ付け。宣言候補の一部のみ、同じ器具の複数個にも対応
5. 器具を置き直したら「配置し直しました」（配置番号を進める。集計は配置数が主指標）
6. セッション終了 → 日次サマリー出力

## 設定（APIサーバーの環境変数）
| 変数 | 既定 | 内容 |
|---|---|---|
| `IC_DATA_DIR` | `data` | DB・画像・レポートの保存先 |
| `IC_CATALOG_CSV` | `src/master/instruments_mock.csv` | 器具マスタCSV |
| `IC_CAMERA_PARAM_YAML` | `src/config/hardware/camera_param.yaml` | camlibカメラパラメータ |
| `IC_CAMERA_ID_YAML` | `src/config/hardware/camera_id.yaml` | camlibカメラID |
| `IC_CAMERA_NAME` / `IC_CAMERA_BUFFER` | 未指定 / `color` | 接続するcamera_id.yamlキー（複数台時）と画像バッファ |
| `IC_CORS_ORIGINS` | `http://127.0.0.1:5173,http://localhost:5173` | React開発画面の許可オリジン |
| `IC_TZ` | `Asia/Tokyo` | 日付の区切り |
| `IC_TARGET_SINGLE` / `IC_TARGET_MULTI` | 10 / 10 | 器具ごとの目標配置数（単体/複数） |
| `IC_MAX_UPLOAD_MB` | 20 | 画像の上限サイズ |

## テスト
```bash
uv run pytest src/backend/tests -q
cd frontend && npm run build
```
