"""SQLite形式の器具マスタをInstrumentCatalogとして提供する。

責務: samplesテーブルから器具情報を読み、検索可能なドメインモデルへ変換する。
処理の流れ: 読み取り専用でDBを開く。必要列を検証する。行をInstrumentへ変換する。検索用のメモリ辞書を置き換える。
関連ファイル: app/ports.py、app/domain/models.py、app/main.py。
設計意図: SQLiteへの依存をアダプターに閉じ込め、既存のInstrumentCatalog契約とサービス層を維持する。
Note: samples.statusは現行APIの状態値と異なるため、全レコードをactiveとして扱う。
"""

from __future__ import annotations

import json
import sqlite3
import unicodedata
from pathlib import Path

from ..domain.models import Instrument

REQUIRED_COLUMNS = frozenset({"id", "name", "name_ja", "model_number", "hierarchy_path", "data_path"})


def _norm(value: str) -> str:
    """検索文字列の全角・半角差を吸収する。"""
    return unicodedata.normalize("NFKC", value).lower()


class SqliteInstrumentCatalog:
    """samplesテーブルを読み取る器具カタログである。"""

    def __init__(self, path: Path) -> None:
        """DBパスを保持し、起動時に器具一覧を読み込む。

        Args:
            path: samplesテーブルを含むSQLiteファイル。
        """
        self._path = Path(path)
        self._items: dict[str, Instrument] = {}
        self._data_paths: dict[str, str] = {}
        # 起動時に読み込んでおくことで、API検索中にDB接続を保持しない。
        self.reload()

    def reload(self) -> None:
        """SQLiteから器具一覧を読み直し、成功時に現在の一覧を置き換える。

        Raises:
            ValueError: DBを読み込めない、または必要な列が存在しない場合。
        """
        try:
            # マスタDBを誤って変更しないよう、SQLiteの読み取り専用モードで接続する。
            database_uri = f"{self._path.resolve().as_uri()}?mode=ro"
            with sqlite3.connect(database_uri, uri=True) as connection:
                columns: set[str] = {row[1] for row in connection.execute("PRAGMA table_info(samples)")}
                missing_columns: frozenset[str] = REQUIRED_COLUMNS - columns
                if missing_columns:
                    raise ValueError(f"器具マスタSQLiteに必須列がありません: {sorted(missing_columns)}")
                rows: list[tuple[object, ...]] = connection.execute(
                    "SELECT id, name, name_ja, model_number, hierarchy_path, data_path FROM samples ORDER BY id"
                ).fetchall()
        except sqlite3.Error as exc:
            raise ValueError(f"器具マスタSQLiteを読み込めません: {exc}") from exc

        # 読み込み途中の失敗で既存カタログを壊さないよう、一時辞書を完成後に切り替える。
        items: dict[str, Instrument] = {}
        data_paths: dict[str, str] = {}
        for raw_uid, raw_name, raw_name_ja, raw_model_number, raw_path, raw_data_path in rows:
            instrument_uid = str(raw_uid or "").strip()
            if not instrument_uid:
                continue
            if instrument_uid in items:
                raise ValueError(f"instrument_uid が重複しています: {instrument_uid}")
            category_path = str(raw_path or "").strip()
            items[instrument_uid] = Instrument(
                instrument_uid=instrument_uid,
                name=str(raw_name or "").strip(),
                category_path=category_path,
                name_ja=str(raw_name_ja or "").strip(),
                model_number=str(raw_model_number).strip() if raw_model_number is not None else None,
            )
            data_paths[instrument_uid] = str(raw_data_path or "")
        self._items = items
        self._data_paths = data_paths

    def sample_image_path(self, uid: str) -> Path | None:
        """器具のcolor画像をDB親フォルダー内に限定して返す。"""
        try:
            data_path = json.loads(self._data_paths.get(uid, ""))
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(data_path, dict):
            return None
        color_path = data_path.get("color")
        if not isinstance(color_path, str) or not color_path.strip():
            return None
        relative_path = Path(color_path.strip())
        if relative_path.is_absolute():
            return None
        try:
            root = self._path.resolve().parent
            image_path = (root / relative_path).resolve()
            if not image_path.is_relative_to(root) or not image_path.is_file():
                return None
        except (OSError, RuntimeError, ValueError):
            return None
        return image_path

    def list(self, q: str | None = None, include_inactive: bool = False) -> list[Instrument]:
        """器具を一覧し、指定時はID・名前・階層で絞り込む。

        Args:
            q: 任意の検索語。
            include_inactive: 非active器具も含めるか。

        Returns:
            条件に一致した器具一覧。
        """
        # samples.statusの値は現行APIのactive状態と異なるため、全件をactiveとして扱う。
        items = [item for item in self._items.values() if include_inactive or item.status == "active"]
        if q:
            normalized_query = _norm(q)
            # 全角・半角を正規化して、CSV版と同じ検索感を維持する。
            items = [
                item for item in items
                if normalized_query in _norm(item.name)
                or normalized_query in _norm(item.name_ja)
                or (item.model_number is not None and normalized_query in _norm(item.model_number))
                or normalized_query in _norm(item.category_path)
                or normalized_query in _norm(item.instrument_uid)
            ]
        return items

    def get(self, uid: str) -> Instrument | None:
        """UIDに一致する器具を返す。

        Args:
            uid: 器具UID。

        Returns:
            一致する器具。存在しない場合はNone。
        """
        return self._items.get(uid)
