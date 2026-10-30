"""日付/セッション単位のSQLiteメタデータを既存ポートへ集約する。

各セッションDBを正本として維持しながら、既存サービスが使うMetadataStore契約を提供する。
セッション数が増えた場合は、検索用の小さなインデックスを追加できる構成とする。
"""

from __future__ import annotations

import shutil
import threading
from contextlib import suppress
from datetime import date
from pathlib import Path
from typing import Optional

from ..domain.models import Declaration, Hint, Image, Session
from ..ports import MetadataStore
from .sqlite_store import SqliteMetadataStore

METADATA_FILENAME = "metadata.sqlite3"


class SessionBundleMetadataStore:
    """MetadataStore操作を対応するセッションDBへルーティングする。"""

    def __init__(self, data_dir: Path):
        """セッションバンドルのルートディレクトリを設定する。

        Args:
            data_dir: 日付ディレクトリを含むデータルート。
        """
        self._root = Path(data_dir)
        self._root.mkdir(parents=True, exist_ok=True)
        self._stores: dict[str, SqliteMetadataStore] = {}
        self._paths = {path.parent.name: path for path in self._database_paths()}
        self._lock = threading.RLock()

    def add_session(self, session: Session) -> None:
        """セッション専用DBを作成し、セッションを保存する。"""
        store = self._store_for_new_session(session)
        store.add_session(session)

    def get_session(self, session_id: str) -> Session | None:
        """指定セッションの記録を取得する。"""
        store = self._store_for_existing_session(session_id)
        return None if store is None else store.get_session(session_id)

    def update_session(self, session: Session) -> None:
        """セッションDBの記録を更新する。"""
        store = self._store_for_existing_session(session.session_id)
        if store is not None:
            store.update_session(session)

    def delete_session(self, session_id: str) -> bool:
        """セッションバンドル全体を削除し、削除済みDBのキャッシュを破棄する。

        Args:
            session_id: 削除対象セッションのID。

        Returns:
            バンドルを削除した場合はTrue。対象がない場合はFalse。
        """
        self._refresh_paths()
        with self._lock:
            path = self._paths.get(session_id)
            if path is None:
                return False
            bundle_dir = path.parent
            if not bundle_dir.resolve().is_relative_to(self._root.resolve()):
                raise ValueError(f"データルート外のセッションは削除できない: {session_id}")
            shutil.rmtree(bundle_dir)
            self._paths.pop(session_id, None)
            self._stores.pop(session_id, None)
        with suppress(OSError):
            bundle_dir.parent.rmdir()
        return True

    def add_declaration(self, declaration: Declaration) -> None:
        """宣言を所属セッションのDBへ保存する。"""
        self._require_session_store(declaration.session_id).add_declaration(declaration)

    def get_declaration(self, declaration_id: str) -> Declaration | None:
        """宣言IDから全セッションDBを検索する。"""
        for store in self._all_stores():
            declaration = store.get_declaration(declaration_id)
            if declaration is not None:
                return declaration
        return None

    def update_declaration(self, declaration: Declaration) -> None:
        """宣言の状態を所有するセッションDBで更新する。"""
        store = self._find_declaration_store(declaration.declaration_id)
        if store is not None:
            store.update_declaration(declaration)

    def list_declarations(self, session_id: str | None = None) -> list[Declaration]:
        """指定セッション、または全セッションの宣言を取得する。"""
        if session_id is not None:
            store = self._store_for_existing_session(session_id)
            return [] if store is None else store.list_declarations(session_id)
        declarations = [declaration for store in self._all_stores() for declaration in store.list_declarations()]
        return sorted(declarations, key=lambda declaration: (declaration.created_at, declaration.declaration_id))

    def add_image(self, image: Image) -> None:
        """画像メタデータを所属セッションDBへ保存する。"""
        self._require_session_store(image.session_id).add_image(image)

    def get_image(self, image_id: str) -> Image | None:
        """画像IDから全セッションDBを検索する。"""
        for store in self._all_stores():
            image = store.get_image(image_id)
            if image is not None:
                return image
        return None

    def update_image(self, image: Image) -> None:
        """タグ状態を画像所有セッションのDBで更新する。"""
        store = self._store_for_existing_session(image.session_id)
        if store is not None:
            store.update_image(image)

    def delete_image(self, image_id: str) -> Image | None:
        """画像と関連タグを所有セッションDBから削除する。"""
        store = self._find_image_store(image_id)
        return None if store is None else store.delete_image(image_id)

    def list_images(self, *, session_id: str | None = None, declaration_id: str | None = None, tag_status: str | None = None, date: str | None = None, limit: int = 200, offset: int = 0) -> list[Image]:
        """条件に合う画像をセッション横断で取得し、全体順でページングする。"""
        if limit <= 0:
            return []
        if session_id is not None:
            store = self._store_for_existing_session(session_id)
            stores = [] if store is None else [store]
        else:
            stores = self._all_stores(date=date)

        per_store_limit = limit + offset
        images = [
            image
            for store in stores
            for image in store.list_images(
                declaration_id=declaration_id,
                tag_status=tag_status,
                date=date,
                limit=per_store_limit,
                offset=0,
            )
        ]
        images.sort(key=lambda image: (image.captured_at, image.image_id))
        return images[offset : offset + limit]

    def replace_hints(self, image_id: str, hints: list[Hint]) -> None:
        """画像に属するタグを全置換する。"""
        store = self._find_image_store(image_id)
        if store is not None:
            store.replace_hints(image_id, hints)

    def list_hints(self, image_id: str) -> list[Hint]:
        """指定画像のタグを取得する。"""
        store = self._find_image_store(image_id)
        return [] if store is None else store.list_hints(image_id)

    def list_hints_for_images(self, image_ids: list[str]) -> dict[str, list[Hint]]:
        """複数画像のタグをDB単位にまとめて取得する。"""
        grouped: dict[int, tuple[SqliteMetadataStore, list[str]]] = {}
        for image_id in image_ids:
            store = self._find_image_store(image_id)
            if store is None:
                continue
            key = id(store)
            if key not in grouped:
                grouped[key] = (store, [])
            grouped[key][1].append(image_id)

        results: dict[str, list[Hint]] = {}
        for store, ids in grouped.values():
            results.update(store.list_hints_for_images(ids))
        return results

    def _store_for_new_session(self, session: Session) -> SqliteMetadataStore:
        session_date = date.fromisoformat(session.started_at[:10]).isoformat()
        if Path(session.session_id).name != session.session_id:
            raise ValueError("不正なsession_idです")
        path = self._root / session_date / session.session_id / METADATA_FILENAME
        return self._store_for_path(session.session_id, path)

    def _store_for_existing_session(self, session_id: str) -> SqliteMetadataStore | None:
        self._refresh_paths()
        with self._lock:
            cached = self._stores.get(session_id)
            if cached is not None:
                return cached
            path = self._paths.get(session_id)
        if path is None:
            return None
        store = self._store_for_path(session_id, path)
        return store if store.get_session(session_id) is not None else None

    def _store_for_path(self, session_id: str, path: Path) -> SqliteMetadataStore:
        with self._lock:
            store = self._stores.get(session_id)
            if store is None:
                store = SqliteMetadataStore(path)
                self._stores[session_id] = store
                self._paths[session_id] = path
            return store

    def _require_session_store(self, session_id: str) -> SqliteMetadataStore:
        store = self._store_for_existing_session(session_id)
        if store is None:
            raise ValueError(f"セッションDBが見つかりません: {session_id}")
        return store

    def _database_paths(self, session_date: str | None = None) -> list[Path]:
        paths: list[Path] = []
        if not self._root.is_dir():
            return paths
        for date_dir in self._root.iterdir():
            if not date_dir.is_dir() or date_dir.name.startswith("."):
                continue
            try:
                parsed_date = date.fromisoformat(date_dir.name)
            except ValueError:
                continue
            if session_date is not None and parsed_date.isoformat() != session_date:
                continue
            paths.extend(date_dir.glob(f"*/{METADATA_FILENAME}"))
        return sorted(paths)

    def _all_stores(self, date: str | None = None) -> list[SqliteMetadataStore]:
        self._refresh_paths()
        with self._lock:
            entries = list(self._paths.items())
        return [self._store_for_path(session_id, path) for session_id, path in entries if date is None or path.parent.parent.name == date]

    def _refresh_paths(self) -> None:
        """削除済みバンドルを再走査で除外し、古いDBキャッシュを破棄する。"""
        paths = {path.parent.name: path for path in self._database_paths()}
        with self._lock:
            removed_session_ids = set(self._paths) - set(paths)
            self._paths = paths
            self._stores = {session_id: store for session_id, store in self._stores.items() if session_id in paths}

    def _find_declaration_store(self, declaration_id: str) -> SqliteMetadataStore | None:
        for store in self._all_stores():
            if store.get_declaration(declaration_id) is not None:
                return store
        return None

    def _find_image_store(self, image_id: str) -> SqliteMetadataStore | None:
        for store in self._all_stores():
            if store.get_image(image_id) is not None:
                return store
        return None
