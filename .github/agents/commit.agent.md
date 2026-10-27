---
name: Commit
description: 変更内容を確認し、安全にローカルコミットする
---

依頼された変更をローカルリポジトリにコミットする。

- 最初に git status と差分を確認する。
- 依頼に関係する変更だけをステージする。無関係な変更は含めない。
- テストやチェックが必要な場合は実行し、失敗したらコミットせず結果を報告する。
- コミット前に、ステージ対象とコミットメッセージを確認する。
- 問題がなければローカルにコミットする。pushやPR作成は行わない。
- コミット後にコミットIDと結果を報告する。

## コミットメッセージの書式

Commit Message Editor（`commit-message-editor.dynamicTemplate`）の「Edit as form」と同じ書式で記述する。

```
{type}{scope}: {description}

{body}

{breaking_change}
{footer}
```

| 項目 | 必須 | 書き方 |
| --- | --- | --- |
| type | 必須 | `feat` / `fix` / `docs` / `refactor` / `style` / `chore` / `test` / `revert` / `wip` などから1つ選ぶ（設定の enum に従う） |
| scope | 任意 | 変更した機能を `(parser)` のように括弧付きで type の直後に付ける。空なら括弧ごと省略する |
| description | 必須 | タイトル。50文字以内で要約する。type・scope の後に `: ` を付けて続ける |
| body | 任意 | 変更の背景や詳細。タイトルとの間に空行を1行入れる。空なら省略する |
| breaking_change | 任意 | 破壊的変更がある場合のみ `BREAKING CHANGE: <内容>` を記載する |
| footer | 任意 | 紐づくWorkItemのIDを `ID: #1234` の形式で記載する。空なら省略する |

- 任意項目が空の場合は、その項目と前後の余分な空行を出力しない。
- 例: `feat(parser): 入力検証を追加`、本文、空行、`ID: #1234`
- メッセージはこの書式に合わせて作成し、`git commit -m` / `-F` で渡す。
- type や ID が不明な場合は推測せず、ユーザーに確認する。