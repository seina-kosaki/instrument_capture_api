"""既存の共有SQLite/画像構成をセッションバンドルへ非破壊移行する。"""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import tempfile
import uuid
from contextlib import closing
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Optional

from ..domain.models import DeclarationItem
from ..ports import InstrumentCatalog
from .sqlite_store import SqliteMetadataStore

LOGGER = logging.getLogger(__name__)
LEGACY_DATABASE = "meta.sqlite3"
SESSION_DATABASE = "metadata.sqlite3"


def relocate_legacy_data_root(legacy_root: Path, data_root: Path) -> bool:
    """旧src/data一式をrepo/dataへコピー配置し、元データを残す。

    Args:
        legacy_root: 旧データルート。
        data_root: 新しいデータルート。

    Returns:
        コピー配置を実行した場合はTrue。
    """
    legacy_root = Path(legacy_root)
    data_root = Path(data_root)
    if not legacy_root.is_dir() or legacy_root.resolve() == data_root.resolve():
        return False
    if data_root.exists():
        LOGGER.info("Using existing data root %s; legacy data remains at %s", data_root, legacy_root)
        return False
    for suffix in ("-wal", "-shm"):
        if (legacy_root / f"{LEGACY_DATABASE}{suffix}").exists():
            raise RuntimeError("旧データベースにWALファイルがあります。旧APIを停止してから移行してください")

    staging = data_root.parent / f".{data_root.name}.migrating-{uuid.uuid4().hex[:8]}"
    try:
        shutil.copytree(legacy_root, staging)
        os.replace(staging, data_root)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    LOGGER.info("Copied legacy data root %s to %s; source retained", legacy_root, data_root)
    return True


def migrate_legacy_storage(data_dir: Path, catalog: Optional[InstrumentCatalog] = None) -> int:
    """既存データを日付/セッションフォルダーへコピーする。

    元データは削除せず、各セッションは同じファイルシステム内で一時フォルダーから
    原子的に配置する。途中失敗時も元DBと元画像を保持できるため、この方法を採る。

    Args:
        data_dir: 旧DB/画像と新セッションバンドルを含むデータルート。
        catalog: 旧宣言に器具名スナップショットを補完するカタログ。

    Returns:
        今回移行したセッション数。
    """
    root = Path(data_dir)
    legacy_path = root / LEGACY_DATABASE
    if not legacy_path.is_file():
        return 0

    with tempfile.TemporaryDirectory(prefix="legacy-storage-read-", dir=root) as temporary_dir:
        legacy_copy = Path(temporary_dir) / LEGACY_DATABASE
        shutil.copy2(legacy_path, legacy_copy)
        legacy_store = SqliteMetadataStore(legacy_copy)
        with closing(sqlite3.connect(legacy_copy)) as connection:
            connection.row_factory = sqlite3.Row
            sessions = connection.execute("SELECT * FROM sessions ORDER BY started_at, session_id").fetchall()

        return _migrate_sessions(root, legacy_store, sessions, catalog)


def _migrate_sessions(data_dir: Path, legacy_store: SqliteMetadataStore,
                      sessions: list[sqlite3.Row], catalog: Optional[InstrumentCatalog]) -> int:
    """既存DBのセッション行を個別バンドルへコピーする。"""
    migrated = 0
    for row in sessions:
        session = legacy_store.get_session(row["session_id"])
        if session is None:
            continue
        session_date = date.fromisoformat(session.started_at[:10]).isoformat()
        date_dir = data_dir / session_date
        bundle_dir = date_dir / session.session_id
        if (bundle_dir / SESSION_DATABASE).is_file():
            continue

        date_dir.mkdir(parents=True, exist_ok=True)
        staging_dir = date_dir / f".{session.session_id}.migrating"
        if staging_dir.exists():
            shutil.rmtree(staging_dir)

        try:
            target_store = SqliteMetadataStore(staging_dir / SESSION_DATABASE)
            target_store.add_session(session)
            declarations = legacy_store.list_declarations(session.session_id)
            for declaration in declarations:
                declaration.items = [
                    DeclarationItem(
                        item.instrument_uid,
                        item.instrument_name or _instrument_name(catalog, item.instrument_uid),
                    )
                    for item in declaration.items
                ]
                target_store.add_declaration(declaration)

            images = legacy_store.list_images(session_id=session.session_id, limit=1_000_000)
            for image in images:
                relative_source = _legacy_relative_path(image.path)
                source = (data_dir / "images" / relative_source).resolve()
                if (data_dir / "images").resolve() not in source.parents:
                    raise ValueError(f"旧画像パスがデータルート外です: {image.path}")
                if not source.is_file():
                    raise FileNotFoundError(f"移行対象画像がありません: {source}")

                filename = source.name
                raw_target = staging_dir / "raw" / filename
                raw_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, raw_target)

                legacy_capture_date = relative_source.parts[0]
                legacy_debug = data_dir / "debug_tagged" / legacy_capture_date / session.session_id / f"{image.image_id}.jpg"
                if legacy_debug.is_file():
                    debug_target = staging_dir / "debug" / f"{image.image_id}.jpg"
                    debug_target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(legacy_debug, debug_target)

                image.path = PurePosixPath(session_date, session.session_id, "raw", filename).as_posix()
                image.camera_name = str(image.meta.get("camera_name") or "unknown")
                image.camera_status = str(image.meta.get("camera_status") or "unknown")
                image.location = session.location
                image.meta = {"schema_version": 1, **image.meta}
                target_store.add_image(image)

            hints = legacy_store.list_hints_for_images([image.image_id for image in images])
            for image_id, image_hints in hints.items():
                target_store.replace_hints(image_id, image_hints)

            if bundle_dir.exists():
                raise FileExistsError(f"セッションバンドルが既に存在します: {bundle_dir}")
            os.replace(staging_dir, bundle_dir)
            migrated += 1
        except Exception:
            if staging_dir.exists():
                shutil.rmtree(staging_dir)
            raise

    if migrated:
        LOGGER.info("Migrated %s legacy session bundles; original database retained", migrated)
    return migrated


def _legacy_relative_path(path: str) -> Path:
    """Windows/Posix区切りの旧DB相対キーを安全な相対パスにする。"""
    parts = PurePosixPath(path.replace("\\", "/")).parts
    if not parts or any(part in ("", ".", "..") for part in parts) or PurePosixPath(path).is_absolute():
        raise ValueError(f"不正な旧画像パスです: {path}")
    return Path(*parts)


def _instrument_name(catalog: Optional[InstrumentCatalog], instrument_uid: str) -> str:
    if catalog is None:
        return ""
    instrument = catalog.get(instrument_uid)
    return "" if instrument is None else instrument.name