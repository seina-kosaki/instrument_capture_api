import hashlib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app
from .conftest import ROOT, make_decl, upload


def pt(x, y, status="visible"):
    return {"x": x, "y": y, "status": status}


def tag_multi(client):
    sid, did = make_decl(client, [{"instrument_uid": "INS-000001"}, {"instrument_uid": "INS-000003"}])
    iid = upload(client, did).json()["image_id"]
    body = {"hints": [
        {"instrument_uid": "INS-000001", "center": pt(.3, .3), "end_a": pt(.2, .3), "end_b": pt(.4, .3)},
        {"instrument_uid": "INS-000001", "center": pt(.7, .7), "occluded": True},
        {"instrument_uid": "INS-000003", "visible": False}]}
    assert client.put(f"/images/{iid}/tags", json=body).status_code == 200
    return sid, iid


def test_debug_image_saved_separately_and_original_untouched(client):
    sid, iid = tag_multi(client)
    original = client.data_dir / "2026-10-05" / sid / "raw" / f"{iid}.png"
    before = hashlib.sha256(original.read_bytes()).hexdigest()
    debug = client.data_dir / "2026-10-05" / sid / "debug" / f"{iid}.jpg"
    assert debug.exists()
    assert "debug" not in original.parts                                       # 生画像と生成画像を分離
    with Image.open(debug) as im, Image.open(original) as src:
        assert im.size == src.size == (64, 48)
        assert im.convert("RGB").getpixel((int(.3 * 63), int(.3 * 47))) != src.convert("RGB").getpixel((int(.3 * 63), int(.3 * 47)))   # 点が描かれている
    assert hashlib.sha256(original.read_bytes()).hexdigest() == before          # 生画像は無加工のまま


def test_retag_overwrites_and_on_demand_endpoint(client):
    sid, iid = tag_multi(client)
    debug = client.data_dir / "2026-10-05" / sid / "debug" / f"{iid}.jpg"
    first = debug.read_bytes()
    body = {"hints": [
        {"instrument_uid": "INS-000001", "center": pt(.5, .5)}, {"instrument_uid": "INS-000001", "center": pt(.8, .2)},
        {"instrument_uid": "INS-000003", "center": pt(.1, .9)}]}
    assert client.put(f"/images/{iid}/tags", json=body).status_code == 200
    assert debug.read_bytes() != first                                          # 再タグ付けで上書き
    r = client.get(f"/images/{iid}/tagged")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert client.get("/images/nonexistent/tagged").status_code == 404


def test_single_mode_declared_only_is_rendered(client):
    sid, did = make_decl(client, [{"instrument_uid": "INS-000002"}])
    iid = upload(client, did).json()["image_id"]
    assert client.put(f"/images/{iid}/tags", json={"hints": []}).status_code == 200
    assert (client.data_dir / "2026-10-05" / sid / "debug" / f"{iid}.jpg").exists()


def test_can_be_disabled(tmp_path):
    s = Settings(data_dir=tmp_path, catalog_csv=ROOT / "master" / "instruments_mock.csv", save_debug_images=False)
    fixed = datetime(2026, 10, 5, 10, tzinfo=ZoneInfo("Asia/Tokyo"))
    with TestClient(create_app(s, clock=lambda: fixed)) as c:
        c.data_dir = tmp_path
        tag_multi(c)
        assert not list(tmp_path.glob("*/*/debug/*.jpg"))


def test_render_failure_does_not_break_tagging(client):
    client.app.state.c.debug.render_jpeg = lambda image_id: (_ for _ in ()).throw(RuntimeError("render error"))
    sid, did = make_decl(client, [{"instrument_uid": "INS-000001"}])
    iid = upload(client, did).json()["image_id"]
    assert client.put(f"/images/{iid}/tags", json={"hints": [{"instrument_uid": "INS-000001", "center": pt(.5, .5)}]}).status_code == 200
    assert client.get(f"/images/{iid}").json()["tag_status"] == "tagged"
