# AGENTS.md

このファイルはCoding Agent（GitHub Copilot coding agent等）がタスクを自律実行する際に自動で読み込む前提ファイルです。
人間向けのCustom Instructionsとは別に、エージェントが**実行・検証まで一貫して行う**ために必要な情報を書きます。

## プロジェクト概要

- 言語: Python（バージョンは `.python-version` と `pyproject.toml` の `requires-python` に従う）
- パッケージ管理: `uv`
- ディレクトリ: src レイアウト（アプリケーションコードは全て `src/` 以下）
- アーキテクチャ: レイヤードアーキテクチャ（`src/<パッケージ名>/domain/` / `usecase/` / `infrastructure/` / `interface/`）
- 詳細な設計・コーディング規約は `.github/copilot-instructions.md` を参照すること（このファイルと矛盾する場合はそちらを優先する）

## セットアップ

```bash
uv sync
```

依存を追加する場合は `pip install` ではなく `uv add <package>`（開発用は `uv add --dev <package>`）を使うこと。
Pythonバージョンを変更する場合は `uv python pin <version>` を使い、`.python-version` と `pyproject.toml` の両方が更新されることを確認する。

## ビルド・検証コマンド

エージェントはコード変更後、必ず以下を実行してから完了報告すること。

```bash
# Lint（ruff.toml の設定に従う）
uv run ruff check .

# 型チェック（mypy.toml の設定に従う）
uv run mypy src

# テスト
uv run pytest -q
```

いずれかが失敗した状態でタスクを完了報告してはいけない。失敗した場合は原因を修正するか、修正できない場合はその理由を明記する。

## 変更時のルール

- 新規ロジックには対応するテストを必ず追加する
- 依存追加は `uv add` で行い、`pyproject.toml` の変更（および `uv.lock` の更新）を伴うことを前提とする。無断でグローバル環境を変更しない
- 全ての public な関数・クラスに型ヒントとGoogle style docstringを付与する。特にモジュール・クラスのdocstringには「なぜその設計にしたか」を記載する（コードから設計書を生成する運用を見据えているため、この点は省略しない）
- マイグレーションやスキーマ変更を伴う場合は、その旨をPR説明に明記する
- 既存の公開API（関数シグネチャ、CLIオプション等）を変更する場合は破壊的変更として明示する

## PR作成時のルール

- タイトルは `<type>: <概要>` 形式（例: `fix: 残高計算の丸め誤差を修正`）
- 説明には「変更内容」「変更理由」「実行した検証コマンドとその結果」を含める
- レビュー観点は `.github/agents/reviewer.agent.md` の基準に従うこと

## 利用可能なSkills

再利用可能な作業手順は `.github/skills/` 配下にまとめてある。該当するタスクの場合は必ず参照すること。

- `docstring-writer`：docstring・インラインコメント・設計意図の補完作業
- `pattern-refactor`：ハードコーディング検出とデザインパターン適用のリファクタリング作業
