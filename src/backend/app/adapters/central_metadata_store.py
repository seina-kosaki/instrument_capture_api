"""Route capture metadata to one SQLite source of truth.

Existing session databases are imported transactionally and retained as migration
evidence. The API continues to depend on the MetadataStore port, while annotation
and training workflows can query the same database across session boundaries.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .sqlite_store import SqliteMetadataStore

LOGGER = logging.getLogger(__name__)
METADATA_FILENAME = "metadata.sqlite3"
ROOT_DATABASE_NAME = "metadata.sqlite3"
SESSION_DATABASE_GLOB = "*/*/metadata.sqlite3"
IMPORT_TABLES = ("sessions", "declarations", "images", "hints")
SELECT_STATEMENTS = {
    "sessions": "SELECT * FROM sessions",
    "declarations": "SELECT * FROM declarations",
    "images": "SELECT * FROM images",
    "hints": "SELECT * FROM hints",
}
INSERT_FIELDS = {
    "sessions": ("session_id", "started_at", "closed_at", "operator", "location", "lighting", "camera_model", "notes"),
    "declarations": ("declaration_id", "session_id", "items_json", "created_at", "confirmed", "confirmed_at", "arrangement_no", "copied_from"),
    "images": (
        "image_id", "declaration_id", "session_id", "arrangement_no", "path", "depth_path",
        "sha256", "width", "height", "content_type", "captured_at", "meta_json", "tag_status",
        "tag_revision", "tagged_at", "tagged_by", "camera_name", "camera_status", "location",
    ),
    "hints": ("image_id", "instrument_uid", "instance_no", "visible", "hint_source", "center_json", "end_a_json", "end_b_json", "occluded", "added_after_capture"),
}
INSERT_STATEMENTS = {
    "sessions": "INSERT INTO sessions(session_id, started_at, closed_at, operator, location, lighting, camera_model, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
    "declarations": "INSERT INTO declarations(declaration_id, session_id, items_json, created_at, confirmed, confirmed_at, arrangement_no, copied_from) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
    "images": (
        "INSERT INTO images(image_id, declaration_id, session_id, arrangement_no, path, depth_path, "
        "sha256, width, height, content_type, captured_at, meta_json, tag_status, tag_revision, "
        "tagged_at, tagged_by, camera_name, camera_status, location) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    ),
    "hints": "INSERT INTO hints(image_id, instrument_uid, instance_no, visible, hint_source, center_json, end_a_json, end_b_json, occluded, added_after_capture) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
}
READ_ONLY_QUERY = "?mode=ro"
HASH_CHUNK_SIZE = 1024 * 1024


class CentralMetadataStore(SqliteMetadataStore):
    """Use a single database for capture, annotation, and training metadata."""

    def __init__(self, database_path: Path) -> None:
        """Initialize the central database while preserving the existing store port."""
        self.database_path = database_path.resolve()
        super().__init__(database_path)


def migrate_session_databases(data_root: Path) -> int:
    """Import existing session databases without deleting or rewriting their files.

    Args:
        data_root: Configured ``IC_DATA_DIR`` containing session directories.

    Returns:
        Number of session databases newly imported.

    """
    root = data_root.resolve()
    central_path = root / ROOT_DATABASE_NAME
    store = CentralMetadataStore(central_path)
    imported = 0
    for source in sorted(root.glob(SESSION_DATABASE_GLOB)):
        if source.resolve() == central_path.resolve():
            continue
        imported += int(_import_session_database(store, source, root))
    if imported:
        LOGGER.info("Imported %s session metadata databases into %s", imported, central_path)
    return imported


def _import_session_database(store: CentralMetadataStore, source: Path, data_root: Path) -> bool:
    """Validate one immutable source snapshot before committing its rows.

    Returns:
        Whether this source was newly imported.

    Raises:
        RuntimeError: The source is active, changed, or conflicts with central data.
    """
    source = source.resolve()
    if any(Path(f"{source}{suffix}").exists() for suffix in ("-wal", "-shm")):
        raise RuntimeError(f"Stop writers and checkpoint the session database before migration: {source}")
    source_hash = _digest_file(source)
    relative_source = source.relative_to(data_root).as_posix()
    try:
        with closing(sqlite3.connect(source.as_uri() + READ_ONLY_QUERY, uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN")
            snapshot = {
                table: [dict(row) for row in connection.execute(SELECT_STATEMENTS[table])]
                for table in IMPORT_TABLES
            }
    except sqlite3.Error as error:
        raise RuntimeError(f"Unable to read session database {source}: {error}") from error
    if len(snapshot["sessions"]) != 1:
        raise RuntimeError(f"Expected exactly one session in bundle database: {source}")

    with _central_connection(store.database_path) as connection:
        existing = connection.execute(
            "SELECT source_sha256 FROM legacy_imports WHERE source_path = ?",
            (relative_source,),
        ).fetchone()
        if existing is not None:
            if existing["source_sha256"] != source_hash:
                raise RuntimeError(f"Imported source changed after migration: {source}")
            return False

        session_id = str(snapshot["sessions"][0]["session_id"])
        if connection.execute("SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)).fetchone():
            raise RuntimeError(f"Session already exists in central database: {session_id}")
        for table in IMPORT_TABLES:
            _insert_rows(connection, table, snapshot[table])
        if _digest_file(source) != source_hash:
            raise RuntimeError(f"Source changed during migration: {source}")
        connection.execute(
            "INSERT INTO legacy_imports(source_path, source_sha256, imported_at) VALUES (?, ?, ?)",
            (relative_source, source_hash, datetime.now(timezone.utc).isoformat()),
        )
    return True


def _insert_rows(connection: sqlite3.Connection, table: str, rows: list[dict[str, Any]]) -> None:
    """Copy columns shared by the old and current schema, preserving new defaults."""
    if not rows:
        return
    connection.executemany(
        INSERT_STATEMENTS[table],
        [tuple(row.get(column, _COLUMN_DEFAULTS.get(table, {}).get(column)) for column in INSERT_FIELDS[table]) for row in rows],
    )


_COLUMN_DEFAULTS: dict[str, dict[str, Any]] = {
    "images": {"depth_path": None, "camera_name": "unknown", "camera_status": "unknown", "location": ""},
}


@contextmanager
def _central_connection(database_path: Path) -> Iterator[sqlite3.Connection]:
    """Commit each imported session atomically to the central metadata database.

    Yields:
        Active central database connection within a commit-or-rollback boundary.
    """
    with closing(sqlite3.connect(database_path)) as connection:
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise


def _digest_file(path: Path) -> str:
    """Return a streaming SHA-256 digest for migration immutability checks."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()
