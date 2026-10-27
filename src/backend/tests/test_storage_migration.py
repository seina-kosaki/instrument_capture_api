"""旧共有ストレージからセッションバンドルへの移行を検証する。"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from app.adapters.legacy_storage_migration import migrate_legacy_storage, relocate_legacy_data_root
from app.adapters.session_bundle_store import SessionBundleMetadataStore
from app.adapters.sqlite_store import SqliteMetadataStore
from app.domain.models import Declaration, DeclarationItem, Image, Session


def test_sqlite_existing_images_receive_nullable_depth_path(tmp_path: Path) -> None:
    """旧画像レコードを失わずにdepth_path列を追加し、再起動時も維持する。"""
    database_path = tmp_path / "metadata.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute("""CREATE TABLE images(
            image_id TEXT PRIMARY KEY, declaration_id TEXT NOT NULL, session_id TEXT NOT NULL,
            arrangement_no INTEGER NOT NULL, path TEXT NOT NULL, sha256 TEXT, width INTEGER, height INTEGER,
            content_type TEXT, captured_at TEXT NOT NULL, meta_json TEXT,
            tag_status TEXT NOT NULL DEFAULT 'untagged', tag_revision INTEGER NOT NULL DEFAULT 0,
            tagged_at TEXT, tagged_by TEXT NOT NULL DEFAULT '')""")
        connection.execute("""INSERT INTO images(
            image_id, declaration_id, session_id, arrangement_no, path, captured_at
        ) VALUES(?, ?, ?, ?, ?, ?)""", ("old-image", "declaration", "session", 1, "raw/old.jpg", "2026-10-22"))

    SqliteMetadataStore(database_path)
    store = SqliteMetadataStore(database_path)

    image = store.get_image("old-image")
    assert image is not None
    assert image.path == "raw/old.jpg"
    assert image.depth_path is None
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT depth_path FROM images").fetchone() == (None,)


def test_relocate_legacy_data_root_when_destination_missing_copies_and_keeps_source(tmp_path: Path) -> None:
    # Arrange
    source = tmp_path / "src" / "data"
    destination = tmp_path / "data"
    legacy_file = source / "2026-10-08" / "session-1" / "metadata.sqlite3"
    legacy_file.parent.mkdir(parents=True)
    legacy_file.write_bytes(b"session metadata")

    # Act
    relocated = relocate_legacy_data_root(source, destination)

    # Assert
    assert relocated is True
    assert (destination / "2026-10-08" / "session-1" / "metadata.sqlite3").read_bytes() == b"session metadata"
    assert legacy_file.read_bytes() == b"session metadata"


def test_relocate_legacy_data_root_when_destination_exists_does_not_overwrite(tmp_path: Path) -> None:
    # Arrange
    source = tmp_path / "src" / "data"
    destination = tmp_path / "data"
    source.mkdir(parents=True)
    destination.mkdir()
    marker = destination / "keep.txt"
    marker.write_text("current data", encoding="utf-8")

    # Act
    relocated = relocate_legacy_data_root(source, destination)

    # Assert
    assert relocated is False
    assert marker.read_text(encoding="utf-8") == "current data"


def test_migrate_legacy_storage_when_source_exists_copies_session_and_keeps_source(tmp_path: Path) -> None:
    # Arrange
    session_id = "session-legacy"
    image_id = "image-legacy"
    session_date = "2026-10-08"
    legacy_store = SqliteMetadataStore(tmp_path / "meta.sqlite3")
    session = Session(session_id=session_id, started_at=f"{session_date}T10:00:00+09:00", location="YTC")
    legacy_store.add_session(session)
    legacy_store.add_declaration(Declaration(
        declaration_id="declaration-legacy",
        session_id=session_id,
        items=[DeclarationItem("INS-000001", "ペアン")],
        created_at=session.started_at,
        confirmed=True,
    ))
    legacy_image_path = Path(session_date) / session_id / f"{image_id}.jpg"
    source_image = tmp_path / "images" / legacy_image_path
    source_image.parent.mkdir(parents=True)
    source_image.write_bytes(b"legacy-image")
    legacy_store.add_image(Image(
        image_id=image_id,
        declaration_id="declaration-legacy",
        session_id=session_id,
        arrangement_no=1,
        path=legacy_image_path.as_posix(),
        sha256="legacy-hash",
        width=10,
        height=10,
        content_type="image/jpeg",
        captured_at=f"{session_date}T10:01:00+09:00",
        meta={"driver": "vendor"},
    ))
    legacy_database_hash = hashlib.sha256((tmp_path / "meta.sqlite3").read_bytes()).hexdigest()

    # Act
    migrated_count = migrate_legacy_storage(tmp_path)
    migrated_store = SessionBundleMetadataStore(tmp_path)
    migrated_image = migrated_store.get_image(image_id)

    # Assert
    bundle = tmp_path / session_date / session_id
    assert migrated_count == 1
    assert migrated_image is not None
    assert migrated_image.path == f"{session_date}/{session_id}/raw/{image_id}.jpg"
    assert migrated_image.camera_name == "unknown"
    assert (bundle / "raw" / f"{image_id}.jpg").read_bytes() == b"legacy-image"
    assert source_image.read_bytes() == b"legacy-image"
    assert (tmp_path / "meta.sqlite3").is_file()
    assert hashlib.sha256((tmp_path / "meta.sqlite3").read_bytes()).hexdigest() == legacy_database_hash


def test_migrate_legacy_storage_when_bundle_already_exists_skips_duplicate(tmp_path: Path) -> None:
    # Arrange
    legacy_store = SqliteMetadataStore(tmp_path / "meta.sqlite3")
    legacy_store.add_session(Session(session_id="session-1", started_at="2026-10-08T10:00:00+09:00"))
    bundle = tmp_path / "2026-10-08" / "session-1"
    bundle.mkdir(parents=True)
    (bundle / "metadata.sqlite3").touch()

    # Act
    migrated_count = migrate_legacy_storage(tmp_path)

    # Assert
    assert migrated_count == 0