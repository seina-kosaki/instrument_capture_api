import io
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings          # noqa: E402
from app.main import create_app          # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def client(tmp_path):
    s = Settings(data_dir=tmp_path / "data", catalog_csv=ROOT / "master" / "instruments_mock.csv",
                 target_single_arrangements=2, target_multi_arrangements=2)
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
