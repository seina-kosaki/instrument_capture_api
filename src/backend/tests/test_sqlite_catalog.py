"""SQLite器具カタログの変換と再読込を検証する。

責務: sample_detailsのID・階層変換、検索、DB更新後の再読込を確認する。
処理の流れ: テスト用SQLiteを用意する。アダプターから器具を取得・検索する。再読込後の値を検証する。
関連ファイル: app/adapters/sqlite_catalog.py、conftest.py。
設計意図: 実DBを変更せず、一時DBでSQLiteアダプターの契約を検証する。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.adapters.sqlite_catalog import SqliteInstrumentCatalog


def test_catalog_maps_sample_detail_id_and_hierarchy(catalog_db: Path) -> None:
    """sample_detailsのIDと最下層を器具ID・名前へ変換する。"""
    # Arrange
    catalog = SqliteInstrumentCatalog(catalog_db)

    # Act
    instrument = catalog.get("INS-000001")

    # Assert
    assert instrument is not None
    assert instrument.name == "ペアン鉗子 直 14cm"
    assert instrument.category_path == "鉗子/ペアン鉗子 直 14cm"
    assert instrument.status == "active"


def test_catalog_search_normalizes_full_width_uid(catalog_db: Path) -> None:
    """全角UIDでもSQLiteカタログから器具を検索できる。"""
    # Arrange
    catalog = SqliteInstrumentCatalog(catalog_db)

    # Act
    instruments = catalog.list(q="ＩＮＳ-000004")

    # Assert
    assert [instrument.instrument_uid for instrument in instruments] == ["INS-000004"]


def test_catalog_reload_applies_updated_database_rows(catalog_db: Path) -> None:
    """DB更新後のreloadでメモリ上の器具名を更新する。"""
    # Arrange
    catalog = SqliteInstrumentCatalog(catalog_db)
    with sqlite3.connect(catalog_db) as connection:
        connection.execute(
            "UPDATE sample_details SET hierarchy_path = ? WHERE id = ?",
            ("鉗子/更新後の器具", "INS-000001"),
        )

    # Act
    catalog.reload()

    # Assert
    instrument = catalog.get("INS-000001")
    assert instrument is not None and instrument.name == "更新後の器具"
