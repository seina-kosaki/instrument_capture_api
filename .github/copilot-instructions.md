# プロジェクト共通指示

- ユーザーが別の言語を指定しない限り、質問・説明・通知・作業結果の報告は日本語で行う。
- 合意済みの仕様に従い、要件が不明確な場合は実装前に確認する。
- 秘密値は `.env` で管理し、ソースコード・ログ・出力に含めない。Hookは補助手段であり、OS全体のアクセス制御ではない。
- 外部から見えるAPIまたはDB契約を変更する場合は、関連する `docs/contracts/` のMarkdownも同じ変更内で更新する。
- 仕様確認・仕様書作成・Python実装・フロントエンド・デバッグ・コード整備では、該当するAgentを使用する。Pythonの作業手順は適用対象のInstructionsに従い、必要な場合だけ関連Skillを使用する。工程の詳細は各Agent・Instructions・Skillに置き、ここへ重ねて記載しない。
- 変更は依頼範囲に絞り、今回の変更と無関係な既存の問題を修正しない。

## プロジェクト構成

- 言語: Python（`.python-version` と `pyproject.toml` の `requires-python` に従う）および React / TypeScript。
- Pythonパッケージは `src/backend/app/` にあり、`api/`、`adapters/`、`domain/`、`services/` に責務を分けている。
- フロントエンドは `frontend/src/` にある。
- パッケージとPython環境の管理には `uv` を使用する。依存追加は適用対象のPython設定指示に従う。

## セットアップと検証

```powershell
uv sync
uvx ruff check .
uvx mypy src
uv run pytest -q
```

`.github/instructions/` の対象別指示と `pyproject.toml` の設定に従う。検証が失敗した場合は今回の変更が原因かを切り分け、未解消の失敗を完了報告に明記する。

## 変更・PR

- 新しいロジックには対応するテストを追加する。
- Pythonの公開関数・クラスには有用な型注釈とGoogle style docstringを付ける。
- スキーマ変更がある場合はPR説明に明記する。公開APIを破壊的に変更する場合はその旨を明記する。
- PRタイトルは `<type>: <概要>` 形式とし、説明には変更内容・理由・実行した検証と結果を含める。

## 利用可能なプロジェクトSkills

- [`ai-development`](./skills/ai-development/SKILL.md): AI学習・評価・推論の設計や実装。
- [`external-contract-review`](./skills/external-contract-review/SKILL.md): 外部プロジェクト契約と `docs/contracts/` の照合。
- [`ui-design-interview`](./skills/ui-design-interview/SKILL.md): React / TypeScript UIの設計ヒアリング。
