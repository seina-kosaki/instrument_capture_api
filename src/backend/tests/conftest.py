import io
import sqlite3
import sys
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.main import create_app


@pytest.fixture
def catalog_db(tmp_path: Path) -> Path:
    """既存APIテスト用の器具レコードを持つSQLiteマスタを作成する。"""
    catalog_path = tmp_path / "catalog.sqlite"
    # 本番と同じ列構成にし、APIテストでは既存のINS-*期待値を維持する。
    with sqlite3.connect(catalog_path) as connection:
        connection.execute("CREATE TABLE sample_details (id TEXT PRIMARY KEY, hierarchy_path TEXT)")
        connection.executemany(
            "INSERT INTO sample_details (id, hierarchy_path) VALUES (?, ?)",
            [
                ("INS-000001", "鉗子/ペアン鉗子 直 14cm"),
                ("INS-000002", "鉗子/ペアン鉗子 曲 14cm"),
                ("INS-000003", "鉗子/ケリー鉗子 曲 14cm"),
                ("INS-000004", "鑷子/アドソン鑷子 有鈎 12cm"),
                ("INS-000005", "剪刀/メッツェンバウム剪刀"),
            ],
        )
    return catalog_path


@pytest.fixture
def client(tmp_path: Path, catalog_db: Path) -> Iterator[TestClient]:
    s = Settings(data_dir=tmp_path / "data", catalog_db=catalog_db, target_single_arrangements=2, target_multi_arrangements=2)
    fixed = datetime(2026, 10, 5, 10, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    with TestClient(create_app(s, clock=lambda: fixed)) as c:
        c.data_dir = s.data_dir
        yield c


def png_bytes(w=64, h=48, color=(120, 130, 140)) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (w, h), color).save(b, "PNG")
    return b.getvalue()


def make_decl(client, items, confirm=True):
    sid = client.post("/sessions", json={"operator": "t"}).json()["session_id"]
    d = client.post(f"/sessions/{sid}/declarations", json={"items": items}).json()
    if confirm:
        client.post(f"/declarations/{d['declaration_id']}/confirm")
    return sid, d["declaration_id"]


def upload(client, did, meta="{}"):
    return client.post(f"/declarations/{did}/images", files={"file": ("a.png", png_bytes(), "image/png")}, data={"meta": meta})
