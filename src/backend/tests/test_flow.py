from .conftest import make_decl, upload


def pt(x, y, status="visible"):
    return {"x": x, "y": y, "status": status}


def test_catalog_mock_has_five_instruments(client):
    r = client.get("/instruments")
    assert r.status_code == 200 and len(r.json()) == 5
    assert set(r.json()[0]) >= {"instrument_uid", "name", "category_path"}
    assert len(client.get("/instruments", params={"q": "ペアン"}).json()) == 2
    assert len(client.get("/instruments", params={"q": "ＩＮＳ-000004"}).json()) == 1   # 全角ゆれ吸収


def test_cannot_upload_before_confirm(client):
    _, did = make_decl(client, [{"instrument_uid": "INS-000001", "count": 1}], confirm=False)
    assert upload(client, did).status_code == 409


def test_unknown_instrument_rejected(client):
    sid = client.post("/sessions", json={}).json()["session_id"]
    r = client.post(f"/sessions/{sid}/declarations", json={"items": [{"instrument_uid": "INS-999999", "count": 1}]})
    assert r.status_code == 400


def test_single_mode_accept_declaration_without_points(client):
    _, did = make_decl(client, [{"instrument_uid": "INS-000001", "count": 1}])
    img = upload(client, did).json()
    assert img["tag_status"] == "untagged" and img["width"] == 64
    r = client.post(f"/images/{img['image_id']}/tags/from-declaration")
    assert r.status_code == 200
    h = r.json()["hints"][0]
    assert h["hint_source"] == "none" and h["hint_quality"] == "none" and h["center"] is None   # NULLでなく明示状態
    assert client.get(f"/images/{img['image_id']}").json()["tag_status"] == "tagged"


def test_single_mode_with_manual_points(client):
    _, did = make_decl(client, [{"instrument_uid": "INS-000002", "count": 1}])
    iid = upload(client, did).json()["image_id"]
    body = {"hints": [{"instrument_uid": "INS-000002", "center": pt(.5, .5), "end_a": pt(.2, .5), "end_b": pt(.8, .5)}]}
    r = client.put(f"/images/{iid}/tags", json=body)
    assert r.status_code == 200 and r.json()["hints"][0]["hint_quality"] == "full" and not r.json()["warnings"]


def test_multi_mode_numbering_and_count_check(client):
    _, did = make_decl(client, [{"instrument_uid": "INS-000001", "count": 2}, {"instrument_uid": "INS-000003", "count": 1}])
    assert client.get(f"/declarations/{did}").json()["mode"] == "multi"
    iid = upload(client, did).json()["image_id"]
    # 個数不足 → 422
    bad = {"hints": [{"instrument_uid": "INS-000001", "center": pt(.2, .2)}]}
    r = client.put(f"/images/{iid}/tags", json=bad)
    assert r.status_code == 422
    assert {e["code"] for e in r.json()["details"]["errors"]} == {"COUNT_MISMATCH"}
    ok = {"hints": [
        {"instrument_uid": "INS-000001", "center": pt(.2, .2)},
        {"instrument_uid": "INS-000003", "center": pt(.5, .5), "occluded": True},
        {"instrument_uid": "INS-000001", "center": pt(.8, .8)}]}
    r = client.put(f"/images/{iid}/tags", json=ok)
    assert r.status_code == 200
    nums = [(h["instrument_uid"], h["instance_no"]) for h in client.get(f"/images/{iid}/tags").json()["hints"]]
    assert ("INS-000001", 1) in nums and ("INS-000001", 2) in nums


def test_none_not_allowed_in_multi_and_invisible_counts(client):
    _, did = make_decl(client, [{"instrument_uid": "INS-000001", "count": 1}, {"instrument_uid": "INS-000002", "count": 1}])
    iid = upload(client, did).json()["image_id"]
    assert client.post(f"/images/{iid}/tags/from-declaration").status_code == 409
    body = {"hints": [{"instrument_uid": "INS-000001", "center": pt(.3, .3)},
                      {"instrument_uid": "INS-000002", "visible": False}]}   # 画面外・完全隠蔽
    assert client.put(f"/images/{iid}/tags", json=body).status_code == 200


def test_undeclared_instrument_needs_flag(client):
    _, did = make_decl(client, [{"instrument_uid": "INS-000001", "count": 1}, {"instrument_uid": "INS-000002", "count": 1}])
    iid = upload(client, did).json()["image_id"]
    base = [{"instrument_uid": "INS-000001", "center": pt(.2, .2)}, {"instrument_uid": "INS-000002", "center": pt(.6, .6)}]
    extra = {"instrument_uid": "INS-000005", "center": pt(.9, .9)}
    r = client.put(f"/images/{iid}/tags", json={"hints": base + [extra]})
    assert r.status_code == 422 and r.json()["details"]["errors"][0]["code"] == "UNDECLARED_INSTRUMENT"
    r = client.put(f"/images/{iid}/tags", json={"hints": base + [{**extra, "added_after_capture": True}]})
    assert r.status_code == 200 and any(w["code"] == "ADDED_AFTER_CAPTURE" for w in r.json()["warnings"])


def test_geometry_and_proximity_warnings(client):
    _, did = make_decl(client, [{"instrument_uid": "INS-000001", "count": 1}, {"instrument_uid": "INS-000002", "count": 1}])
    iid = upload(client, did).json()["image_id"]
    body = {"hints": [
        {"instrument_uid": "INS-000001", "center": pt(.9, .5), "end_a": pt(.2, .5), "end_b": pt(.5, .5)},
        {"instrument_uid": "INS-000002", "center": pt(.905, .5)}]}
    codes = {w["code"] for w in client.post(f"/images/{iid}/tags/validate", json=body).json()["warnings"]}
    assert {"CENTER_NOT_BETWEEN_ENDS", "CLOSE_POINTS"} <= codes
    assert client.get(f"/images/{iid}").json()["tag_status"] == "untagged"     # validate は保存しない


def test_out_of_range_point_rejected_by_schema(client):
    _, did = make_decl(client, [{"instrument_uid": "INS-000001", "count": 1}])
    iid = upload(client, did).json()["image_id"]
    r = client.put(f"/images/{iid}/tags", json={"hints": [{"instrument_uid": "INS-000001", "center": pt(1.5, .5)}]})
    assert r.status_code == 422


def test_arrangement_counts_and_stats(client):
    _, did = make_decl(client, [{"instrument_uid": "INS-000001", "count": 1}])
    for _ in range(3):                      # 同一配置の連写3枚
        upload(client, did)
    client.post(f"/declarations/{did}/rearrange")
    upload(client, did)                     # 置き直し後の1枚
    d = client.get("/stats/daily", params={"date": "2026-10-05"}).json()
    row = d["instruments"][0]
    assert d["images"] == 4 and d["arrangements"] == 2 and d["tagged_images"] == 0 and len(d["untagged_images"]) == 4
    assert row["single_arrangements"] == 2 and row["multi_arrangements"] == 0
    cov = client.get("/stats/coverage").json()
    assert len(cov["instruments"]) == 5
    r1 = next(r for r in cov["instruments"] if r["instrument_uid"] == "INS-000001")
    assert r1["achievement"] == 0.5          # 単体2/2 + 複数0/2 → 2/4
    assert "INS-000001" not in cov["next_to_shoot"][:1]


def test_session_close_writes_daily_report(client):
    sid, did = make_decl(client, [{"instrument_uid": "INS-000001", "count": 1}])
    iid = upload(client, did).json()["image_id"]
    client.post(f"/images/{iid}/tags/from-declaration")
    assert client.post(f"/sessions/{sid}/close").json()["closed_at"]
    assert (client.data_dir / "reports" / "daily_2026-10-05.html").exists()
    assert (client.data_dir / "reports" / "daily_2026-10-05.json").exists()
    assert upload(client, did).status_code == 409          # 終了後は撮影不可
    assert "日次サマリー" in client.get("/reports/daily").text


def test_image_file_roundtrip_and_bad_upload(client):
    _, did = make_decl(client, [{"instrument_uid": "INS-000001", "count": 1}])
    img = upload(client, did).json()
    r = client.get(img["file_url"])
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    bad = client.post(f"/declarations/{did}/images", files={"file": ("a.png", b"not an image", "image/png")})
    assert bad.status_code == 400
    assert client.post(f"/declarations/{did}/images", files={"file": ("a.txt", b"x", "text/plain")}).status_code == 400
