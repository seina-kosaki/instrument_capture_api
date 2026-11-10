# 解析画面の器具セル表示仕様

## 目的・対象

達成状況タブおよび日次集計タブの器具セルを、宣言画面に近い器具情報とサンプル画像の表示に変更し、器具を識別しやすくする。

## システム要否・技術

| 項目 | 決定 |
|---|---|
| AI開発 | いいえ。学習・評価・推論の要件なし |
| フロントエンド | Yes — 既存React / TypeScript UI |
| バックエンド/API | Yes — 既存Python / FastAPIの集計API応答を拡張 |
| DB | 変更なし — 既存器具カタログを参照 |

## 入出力・表示動作

- 入力は達成状況・日次集計の集計データと、同じ器具カタログから取得する器具情報・サンプル画像参照を使用する。
- 両画面の器具セルでは階層パス中心の表示をやめ、宣言画面に近い表記として `name`、`name_ja`、`model_number`、`instrument_uid` を表示する。
- `model_number` が `null` または未設定の場合は「未登録」と表示する。
- `data_path.color` に由来するサンプル画像を表示する。サンプル画像がない場合は画像参照を `null` として扱い、画面では画像なし状態を表示してよい。
- 器具情報と画像の追加は表示目的に限る。集計操作・数値列・集計値には変更を加えない。

## API概要

既存の集計API応答を拡張する。器具行に既存の集計項目を維持したまま、`name_ja`、`model_number`、`sample_image_url` を含める。項目の型と画像参照元は [器具マスタ・API契約](./contracts/instrument-catalog.md) に従う。

| エンドポイント | 現在の用途・入力 | 表示要件との関係 |
|---|---|---|
| `GET /stats/coverage` | 達成状況の集計取得。入力なし | 器具行に `name_ja`、`model_number`、`sample_image_url` を含む |
| `GET /stats/daily?date=...` | 指定日の集計取得。`date` は対象日 | 器具行に `name_ja`、`model_number`、`sample_image_url` を含む |
| `GET /instruments/{uid}/sample-image` | 器具マスタのサンプル画像取得 | 集計APIが返す参照先として `data_path.color` 由来の画像を配信 |

## 制約・対象外

- 対象画面は達成状況・日次集計のみ。宣言画面そのもの、その他の画面、集計ロジック、集計操作、数値列、CSV出力および日次レポート動作は変更しない。
- DBスキーマ、集計ロジック、撮影・タグ付け動作は変更しない。
- 関連実装箇所: `frontend/src/AnalysisView.tsx`、`frontend/src/styles.css`、`src/backend/app/api/routers/stats.py`、`docs/contracts/instrument-catalog.md`。

## 受け入れ条件

1. 達成状況および日次集計の両方で、階層パス中心ではなく宣言画面に近い器具表示になっている。
2. 両画面の器具セルに `name`、`name_ja`、`model_number`、`instrument_uid` が表示される。
3. `model_number` が `null` または未設定の場合は「未登録」と表示される。
4. `data_path.color` 由来のサンプル画像を表示し、画像がない場合は `null` の画像参照を画像なしとして表示できる。
5. 集計操作・数値列・集計値に変更がなく、対象外画面にも変更がない。
6. 集計API応答の追加項目を外部契約に反映し、既存の器具カタログとサンプル画像APIを利用する。

## 未解決事項

なし。
