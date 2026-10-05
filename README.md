# 器具撮影・タグ付けAPI（PoC）

手術器械の画像データ収集と、撮影時の簡易タグ付け（点タップ＋器具ID）を行うシステム。
**API / 撮影アプリ / タグ付けUI の3つを独立させ、HTTP契約とpostMessageだけで接続**している。

```
instrument-capture/
├─ master/instruments_mock.csv      器具マスタ（モック5件: instrument_uid, name, category_path）
├─ backend/                         API（FastAPI + SQLite + ローカルFS）
├─ apps/capture/                    撮影アプリ（宣言→配置確認→撮影）
├─ apps/tagger/                     タグ付けUI（単独でも、撮影アプリ内iframeでも動作）
├─ scripts/dev.sh                   開発用起動
├─ scripts/e2e.py                   ブラウザE2E（擬似カメラ）
└─ docs/architecture.md             設計・API契約・拡張点
```

## 起動

```bash
cd backend && pip install -r requirements.txt && cd ..
./scripts/dev.sh
```

| URL | 内容 |
|---|---|
| http://localhost:8081/capture/index.html | 撮影アプリ |
| http://localhost:8081/tagger/index.html | タグ付けUI（未タグ画像の一覧から選択） |
| http://localhost:8000/docs | API仕様（OpenAPI） |
| http://localhost:8000/reports/daily | 当日の日次サマリー（HTML） |

カメラが無い環境では、撮影アプリの「カメラ入力」で **テスト用（擬似画像）** を選ぶと一通り試せる。

## 撮影の流れ
1. セッション開始（撮影者・場所・照明など）
2. 並べる器具を検索して選択（個数も指定）。宣言1器具1個 → 単体撮影、それ以外 → 複数撮影
3. 器具を並べ、宣言リストと実物を照合 → 確認チェック → 撮影へ
4. 撮影（生画像は即保存）→ タグ付け（器具を選び、中心→端点A→端点Bをタップ。端点は省略可）
   - 単体撮影は「点なしで自動タグ付け」も可（宣言＝ラベル）
   - 器具を置き直したら「配置し直しました」（配置番号を進める）
5. セッション終了 → 日次サマリー（取得枚数・配置数・全体の達成率）を出力

## 設定（環境変数）
| 変数 | 既定 | 内容 |
|---|---|---|
| `IC_DATA_DIR` | `./data` | DB・画像・レポートの保存先 |
| `IC_CATALOG_CSV` | `master/instruments_mock.csv` | 器具マスタCSV |
| `IC_TZ` | `Asia/Tokyo` | 日付境界のタイムゾーン |
| `IC_CORS_ORIGINS` | `*` | 許可オリジン（本番は限定すること） |
| `IC_TARGET_SINGLE` / `IC_TARGET_MULTI` | 10 / 10 | 器具ごとの目標配置数（単体/複数） |

アプリ側は URL パラメータで接続先を切替: `?api=http://host:8000`（撮影アプリは `&tagger=...` も可）。

## テスト
```bash
cd backend && python -m pytest -q      # API単体・結合テスト（14件）
python scripts/e2e.py                  # ブラウザE2E（要 playwright + chromium）
```
