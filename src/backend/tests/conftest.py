import io
import json
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
    with sqlite3.connect(catalog_path) as connection:
        connection.execute(
            """CREATE TABLE samples (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                model_number TEXT,
                place TEXT,
                date TEXT,
                occluded TEXT NOT NULL,
                overlapping TEXT NOT NULL,
                camera TEXT,
                camera_mount TEXT,
                height REAL,
                size REAL,
                sync_group_id TEXT,
                status TEXT,
                hierarchy_path TEXT NOT NULL,
                hierarchy TEXT NOT NULL,
                data_path TEXT NOT NULL,
                annotations TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                name_ja TEXT NOT NULL DEFAULT ''
            )"""
        )
        connection.execute(
            """CREATE TABLE version_samples (
                version TEXT NOT NULL,
                id TEXT NOT NULL,
                snapshot TEXT NOT NULL,
                PRIMARY KEY (version, id)
            )"""
        )
        connection.execute(
            """CREATE TABLE versions (
                version TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                note TEXT,
                sample_count INTEGER NOT NULL,
                snapshot_sha256 TEXT NOT NULL
            )"""
        )
        connection.executemany(
            """INSERT INTO samples
                (id, name, model_number, hierarchy_path, data_path, occluded, overlapping,
                 hierarchy, annotations, created_at, updated_at, name_ja, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                ("INS-000001", "ペアン鉗子 直 14cm", "PN-0001", "鉗子/ペアン鉗子 直 14cm", json.dumps({"color": "raw/INS-000001.png"}), "false", "false", "[]", "[]", "2026-01-01", "2026-01-01", "ペアン鉗子（直）", "train"),
                ("INS-000002", "ペアン鉗子 曲 14cm", None, "鉗子/ペアン鉗子 曲 14cm", json.dumps({"color": "raw/missing.png"}), "false", "false", "[]", "[]", "2026-01-01", "2026-01-01", "ペアン鉗子（曲）", "train"),
                ("INS-000003", "ケリー鉗子 曲 14cm", "PN-0003", "鉗子/ケリー鉗子 曲 14cm", json.dumps({"color": "../outside.png"}), "false", "false", "[]", "[]", "2026-01-01", "2026-01-01", "ケリー鉗子", "train"),
                ("INS-000004", "アドソン鑷子 有鈎 12cm", None, "鑷子/アドソン鑷子 有鈎 12cm", json.dumps({"color": None}), "false", "false", "[]", "[]", "2026-01-01", "2026-01-01", "アドソン鑷子", "train"),
                ("INS-000005", "メッツェンバウム剪刀", "PN-0005", "剪刀/メッツェンバウム剪刀", json.dumps({}), "false", "false", "[]", "[]", "2026-01-01", "2026-01-01", "メッツェンバウム剪刀", "train"),
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
