"""SQLite器具カタログの変換と再読込を検証する。

責務: samplesの項目変換、検索、DB更新後の再読込、サンプル画像APIを確認する。
処理の流れ: テスト用SQLiteを用意する。アダプターから器具を取得・検索する。再読込後の値を検証する。
関連ファイル: app/adapters/sqlite_catalog.py、conftest.py。
設計意図: 実DBを変更せず、一時DBでSQLiteアダプターの契約を検証する。
"""

from __future__ import annotations

import sqlite3
from http import HTTPStatus
from pathlib import Path

from app.adapters.sqlite_catalog import SqliteInstrumentCatalog
from fastapi.testclient import TestClient

from .conftest import png_bytes


def test_catalog_maps_sample_id_and_database_names(catalog_db: Path) -> None:
    """samplesのID・名称・階層を器具モデルへ変換する。"""
    # Arrange
    catalog = SqliteInstrumentCatalog(catalog_db)

    # Act
    instrument = catalog.get("INS-000001")

    # Assert
    assert instrument is not None
    assert instrument.name == "ペアン鉗子 直 14cm"
    assert instrument.name_ja == "ペアン鉗子（直）"
    assert instrument.model_number == "PN-0001"
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
            "UPDATE samples SET name = ? WHERE id = ?",
            ("更新後の器具", "INS-000001"),
        )

    # Act
    catalog.reload()

    # Assert
    instrument = catalog.get("INS-000001")
    assert instrument is not None and instrument.name == "更新後の器具"


def test_instrument_api_exposes_names_and_existing_sample_image(catalog_db: Path, client: TestClient) -> None:
    """一覧・詳細APIは名称と存在する画像の相対URLを返す。"""
    image_path = catalog_db.parent / "raw" / "INS-000001.png"
    image_path.parent.mkdir()
    image_path.write_bytes(png_bytes())
    listed = client.get("/instruments").json()[0]
    detail = client.get("/instruments/INS-000001").json()
    assert listed["sample_image_url"] == "/instruments/INS-000001/sample-image"
    assert listed["name"] == "ペアン鉗子 直 14cm"
    assert listed["name_ja"] == "ペアン鉗子（直）"
    assert listed["model_number"] == "PN-0001"
    assert detail["sample_image_url"] == listed["sample_image_url"]


def test_sample_image_route_serves_existing_file_and_returns_404_for_missing(catalog_db: Path, client: TestClient) -> None:
    """画像APIはDB親フォルダー内の画像を配信し、未存在なら404を返す。"""
    image_path = catalog_db.parent / "raw" / "INS-000001.png"
    image_path.parent.mkdir()
    image_data = png_bytes()
    image_path.write_bytes(image_data)
    response = client.get("/instruments/INS-000001/sample-image")
    assert response.status_code == HTTPStatus.OK
    assert response.headers["content-type"] == "image/png"
    assert response.content == image_data
    assert client.get("/instruments/INS-000002/sample-image").status_code == HTTPStatus.NOT_FOUND
    assert client.get("/instruments/INS-000002").json()["sample_image_url"] is None


def test_sample_image_route_rejects_paths_outside_database_parent(catalog_db: Path, client: TestClient) -> None:
    """存在ファイルであってもDB親フォルダー外の画像は配信しない。"""
    outside_path = catalog_db.parent.parent / "outside.png"
    outside_path.write_bytes(png_bytes())
    assert client.get("/instruments/INS-000003/sample-image").status_code == HTTPStatus.NOT_FOUND
    assert client.get("/instruments/INS-000003").json()["sample_image_url"] is None
