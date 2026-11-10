from fastapi.testclient import TestClient

from .conftest import make_decl, png_bytes, upload


def test_start_session_when_created_uses_time_sortable_unique_id(client):
    # Arrange
    payload = {"operator": "test"}

    # Act
    first = client.post("/sessions", json=payload).json()
    second = client.post("/sessions", json=payload).json()

    # Assert
    assert first["session_id"].startswith("session_100000_000000_")
    assert second["session_id"].startswith("session_100000_000000_")
    assert first["session_id"] != second["session_id"]


def pt(x, y, status="visible"):
    return {"x": x, "y": y, "status": status}


def test_catalog_lists_five_instruments_from_sqlite(client):
    r = client.get("/instruments")
    assert r.status_code == 200 and len(r.json()) == 5
    assert set(r.json()[0]) >= {"instrument_uid", "name", "category_path"}
    assert len(client.get("/instruments", params={"q": "ペアン"}).json()) == 2
    assert len(client.get("/instruments", params={"q": "ＩＮＳ-000004"}).json()) == 1  # 全角ゆれ吸収


def test_cannot_upload_before_confirm(client):
    _, did = make_decl(client, [{"instrument_uid": "INS-000001"}], confirm=False)
    assert upload(client, did).status_code == 409


def test_unknown_instrument_rejected(client):
    sid = client.post("/sessions", json={}).json()["session_id"]
    r = client.post(f"/sessions/{sid}/declarations", json={"items": [{"instrument_uid": "INS-999999"}]})
    assert r.status_code == 400


def test_declaration_rejects_count_field(client):
    # Arrange
    session_id = client.post("/sessions", json={}).json()["session_id"]

    # Act
    response = client.post(
        f"/sessions/{session_id}/declarations",
        json={"items": [{"instrument_uid": "INS-000001", "count": 1}]},
    )

    # Assert
    assert response.status_code == 422


def test_save_empty_hints_when_no_declared_instrument_is_visible(client):
    _, did = make_decl(client, [{"instrument_uid": "INS-000001"}])
    img = upload(client, did).json()
    assert img["tag_status"] == "untagged" and img["width"] == 64
    r = client.put(f"/images/{img['image_id']}/tags", json={"hints": []})
    assert r.status_code == 200
    assert r.json()["hints"] == []
    assert client.get(f"/images/{img['image_id']}").json()["tag_status"] == "tagged"


def test_single_mode_with_manual_points(client):
    _, did = make_decl(client, [{"instrument_uid": "INS-000002"}])
    iid = upload(client, did).json()["image_id"]
    body = {"hints": [{"instrument_uid": "INS-000002", "center": pt(0.5, 0.5), "end_a": pt(0.2, 0.5), "end_b": pt(0.8, 0.5)}]}
    r = client.put(f"/images/{iid}/tags", json=body)
    assert r.status_code == 200 and r.json()["hints"][0]["hint_quality"] == "full" and not r.json()["warnings"]


def test_declaration_set_allows_missing_and_repeated_instrument_hints(client):
    _, did = make_decl(client, [{"instrument_uid": "INS-000001"}, {"instrument_uid": "INS-000003"}])
    declaration = client.get(f"/declarations/{did}").json()
    assert declaration["instrument_type_count"] == 2
    assert all("count" not in item for item in declaration["items"])
    iid = upload(client, did).json()["image_id"]
    partial = {"hints": [{"instrument_uid": "INS-000001", "center": pt(0.2, 0.2)}]}
    assert client.put(f"/images/{iid}/tags", json=partial).status_code == 200
    repeated = {"hints": [{"instrument_uid": "INS-000001", "center": pt(0.2, 0.2)}, {"instrument_uid": "INS-000001", "center": pt(0.4, 0.4)}, {"instrument_uid": "INS-000003", "center": pt(0.8, 0.8), "occluded": True}]}
    r = client.put(f"/images/{iid}/tags", json=repeated)
    assert r.status_code == 200
    nums = [(h["instrument_uid"], h["instance_no"]) for h in client.get(f"/images/{iid}/tags").json()["hints"]]
    assert ("INS-000001", 1) in nums and ("INS-000001", 2) in nums


def test_declaration_when_duplicate_instrument_uids_are_submitted_stores_one_candidate(client):
    # Arrange
    session_id = client.post("/sessions", json={}).json()["session_id"]

    # Act
    response = client.post(
        f"/sessions/{session_id}/declarations",
        json={"items": [{"instrument_uid": "INS-000001"}, {"instrument_uid": "INS-000001"}]},
    )

    # Assert
    assert response.status_code == 201
    assert response.json()["instrument_type_count"] == 1
    assert len(response.json()["items"]) == 1


def test_empty_hints_and_invisible_declared_instrument_are_valid(client):
    _, did = make_decl(client, [{"instrument_uid": "INS-000001"}, {"instrument_uid": "INS-000002"}])
    iid = upload(client, did).json()["image_id"]
    assert client.put(f"/images/{iid}/tags", json={"hints": []}).status_code == 200
    body = {"hints": [{"instrument_uid": "INS-000001", "center": pt(0.3, 0.3)}, {"instrument_uid": "INS-000002", "visible": False}]}  # 画面外・完全隠蔽
    assert client.put(f"/images/{iid}/tags", json=body).status_code == 200


def test_undeclared_instrument_needs_flag(client):
    _, did = make_decl(client, [{"instrument_uid": "INS-000001"}, {"instrument_uid": "INS-000002"}])
    iid = upload(client, did).json()["image_id"]
    base = [{"instrument_uid": "INS-000001", "center": pt(0.2, 0.2)}, {"instrument_uid": "INS-000002", "center": pt(0.6, 0.6)}]
    extra = {"instrument_uid": "INS-000005", "center": pt(0.9, 0.9)}
    r = client.put(f"/images/{iid}/tags", json={"hints": base + [extra]})
    assert r.status_code == 422 and r.json()["details"]["errors"][0]["code"] == "UNDECLARED_INSTRUMENT"
    r = client.put(f"/images/{iid}/tags", json={"hints": base + [{**extra, "added_after_capture": True}]})
    assert r.status_code == 200 and any(w["code"] == "ADDED_AFTER_CAPTURE" for w in r.json()["warnings"])


def test_geometry_and_proximity_warnings(client):
    _, did = make_decl(client, [{"instrument_uid": "INS-000001"}, {"instrument_uid": "INS-000002"}])
    iid = upload(client, did).json()["image_id"]
    body = {"hints": [{"instrument_uid": "INS-000001", "center": pt(0.9, 0.5), "end_a": pt(0.2, 0.5), "end_b": pt(0.5, 0.5)}, {"instrument_uid": "INS-000002", "center": pt(0.905, 0.5)}]}
    codes = {w["code"] for w in client.post(f"/images/{iid}/tags/validate", json=body).json()["warnings"]}
    assert {"CENTER_NOT_BETWEEN_ENDS", "CLOSE_POINTS"} <= codes
    assert client.get(f"/images/{iid}").json()["tag_status"] == "untagged"  # validate は保存しない


def test_out_of_range_point_rejected_by_schema(client):
    _, did = make_decl(client, [{"instrument_uid": "INS-000001"}])
    iid = upload(client, did).json()["image_id"]
    r = client.put(f"/images/{iid}/tags", json={"hints": [{"instrument_uid": "INS-000001", "center": pt(1.5, 0.5)}]})
    assert r.status_code == 422


def test_arrangement_counts_and_stats(client):
    _, did = make_decl(client, [{"instrument_uid": "INS-000001"}])
    images = [upload(client, did).json() for _ in range(3)]
    one_hint = {"hints": [{"instrument_uid": "INS-000001", "center": pt(0.3, 0.3)}]}
    assert client.put(f"/images/{images[0]['image_id']}/tags", json=one_hint).status_code == 200
    client.post(f"/declarations/{did}/rearrange")
    multi_image = upload(client, did).json()
    two_hints = {
        "hints": [
            {"instrument_uid": "INS-000001", "center": pt(0.2, 0.2)},
            {"instrument_uid": "INS-000001", "center": pt(0.8, 0.8)},
        ]
    }
    assert client.put(f"/images/{multi_image['image_id']}/tags", json=two_hints).status_code == 200
    d = client.get("/stats/daily", params={"date": "2026-10-05"}).json()
    row = d["instruments"][0]
    assert d["images"] == 4 and d["arrangements"] == 2 and d["tagged_images"] == 2 and len(d["untagged_images"]) == 2
    assert row["images"] == 2
    assert row["single_arrangements"] == 1 and row["multi_arrangements"] == 1
    cov = client.get("/stats/coverage").json()
    assert len(cov["instruments"]) == 5
    r1 = next(r for r in cov["instruments"] if r["instrument_uid"] == "INS-000001")
    assert r1["achievement"] == 0.5  # 単体2/2 + 複数0/2 → 2/4
    assert "INS-000001" not in cov["next_to_shoot"][:1]


def test_stats_rows_include_catalog_details_and_sample_image_url(client, catalog_db):
    image_path = catalog_db.parent / "raw" / "INS-000001.png"
    image_path.parent.mkdir()
    image_path.write_bytes(png_bytes())

    _, did = make_decl(client, [{"instrument_uid": "INS-000001"}])
    image_id = upload(client, did).json()["image_id"]
    response = client.put(
        f"/images/{image_id}/tags",
        json={"hints": [{"instrument_uid": "INS-000001", "center": pt(0.3, 0.3)}]},
    )
    assert response.status_code == 200

    daily = client.get("/stats/daily", params={"date": "2026-10-05"}).json()
    daily_row = daily["instruments"][0]
    assert daily_row["name_ja"] == "ペアン鉗子（直）"
    assert daily_row["model_number"] == "PN-0001"
    assert daily_row["sample_image_url"] == "/instruments/INS-000001/sample-image"

    coverage = client.get("/stats/coverage").json()
    coverage_row = next(row for row in coverage["instruments"] if row["instrument_uid"] == "INS-000001")
    assert coverage_row["name_ja"] == "ペアン鉗子（直）"
    assert coverage_row["model_number"] == "PN-0001"
    assert coverage_row["sample_image_url"] == "/instruments/INS-000001/sample-image"
    missing_image_row = next(row for row in coverage["instruments"] if row["instrument_uid"] == "INS-000004")
    assert missing_image_row["name_ja"] == "アドソン鑷子"
    assert missing_image_row["model_number"] is None
    assert missing_image_row["sample_image_url"] is None


def test_session_close_writes_daily_report(client):
    sid, did = make_decl(client, [{"instrument_uid": "INS-000001"}])
    iid = upload(client, did).json()["image_id"]
    client.put(f"/images/{iid}/tags", json={"hints": []})
    assert client.post(f"/sessions/{sid}/close").json()["closed_at"]
    assert (client.data_dir / "reports" / "daily_2026-10-05.html").exists()
    assert (client.data_dir / "reports" / "daily_2026-10-05.json").exists()
    assert upload(client, did).status_code == 409  # 終了後は撮影不可
    assert "日次サマリー" in client.get("/reports/daily").text


def test_image_file_roundtrip_and_bad_upload(client):
    _, did = make_decl(client, [{"instrument_uid": "INS-000001"}])
    img = upload(client, did).json()
    r = client.get(img["file_url"])
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    bad = client.post(f"/declarations/{did}/images", files={"file": ("a.png", b"not an image", "image/png")})
    assert bad.status_code == 400
    assert client.post(f"/declarations/{did}/images", files={"file": ("a.txt", b"x", "text/plain")}).status_code == 400


def test_session_bundle_when_capture_saved_contains_metadata_and_assets(client):
    # Arrange
    session_id, declaration_id = make_decl(client, [{"instrument_uid": "INS-000001"}])
    response = upload(client, declaration_id)

    # Act
    image = response.json()
    bundle = client.data_dir / "2026-10-05" / session_id

    # Assert
    assert (bundle / "metadata.sqlite3").is_file()
    assert not (client.data_dir / "metadata.sqlite3").exists()
    assert (bundle / "raw" / f"{image['image_id']}.png").is_file()
    assert image["location"] == ""
    assert image["camera_name"] == "unknown"
    declaration = client.get(f"/declarations/{declaration_id}").json()
    assert declaration["items"][0]["instrument_name"]


def test_delete_session_when_closed_removes_its_entire_bundle(client: TestClient) -> None:
    """終了済みセッションの削除で専用DBと撮影ファイルをまとめて除去する。"""
    # Arrange
    session_id, declaration_id = make_decl(client, [{"instrument_uid": "INS-000001"}])
    image = upload(client, declaration_id).json()
    client.post(f"/sessions/{session_id}/close")
    bundle = client.data_dir / "2026-10-05" / session_id
    daily_report = client.data_dir / "reports" / "daily_2026-10-05.json"
    assert daily_report.is_file()

    # Act
    response = client.delete(f"/sessions/{session_id}")

    # Assert
    assert response.status_code == 204
    assert not bundle.exists()
    assert not (client.data_dir / "metadata.sqlite3").exists()
    assert client.get(f"/sessions/{session_id}").status_code == 404
    assert client.get(f"/images/{image['image_id']}").status_code == 404
    assert not daily_report.exists()
    assert not daily_report.parent.exists()


def test_delete_session_when_open_keeps_its_bundle(client: TestClient) -> None:
    """撮影中のセッション削除を拒否してデータを保持する。"""
    # Arrange
    session_id, _ = make_decl(client, [{"instrument_uid": "INS-000001"}])
    bundle = client.data_dir / "2026-10-05" / session_id

    # Act
    response = client.delete(f"/sessions/{session_id}")

    # Assert
    assert response.status_code == 409
    assert bundle.is_dir()
    assert (bundle / "metadata.sqlite3").is_file()


def test_delete_image_when_session_has_multiple_images_removes_only_target(client):
    # Arrange
    session_id, declaration_id = make_decl(client, [{"instrument_uid": "INS-000001"}])
    first = upload(client, declaration_id).json()
    second = upload(client, declaration_id).json()
    client.put(f"/images/{first['image_id']}/tags", json={"hints": []})
    bundle = client.data_dir / "2026-10-05" / session_id

    # Act
    response = client.delete(f"/images/{first['image_id']}")

    # Assert
    assert response.status_code == 204
    assert client.get(f"/images/{first['image_id']}").status_code == 404
    assert client.get(f"/images/{second['image_id']}/file").status_code == 200
    assert not (bundle / "raw" / f"{first['image_id']}.png").exists()
    assert not (bundle / "debug" / f"{first['image_id']}.jpg").exists()
    assert (bundle / "raw" / f"{second['image_id']}.png").is_file()


def test_catalog_reload_and_export(client):
    assert client.post("/instruments/reload").json() == {"count": 5}
    _, did = make_decl(client, [{"instrument_uid": "INS-000001"}])
    iid = upload(client, did).json()["image_id"]
    body = {"hints": [{"instrument_uid": "INS-000001", "center": pt(0.2, 0.2), "end_a": pt(0.1, 0.2), "end_b": pt(0.3, 0.2)}, {"instrument_uid": "INS-000001", "center": pt(0.7, 0.7), "occluded": True}]}
    assert client.put(f"/images/{iid}/tags", json=body).status_code == 200
    rows = client.get("/export/hints").json()
    assert len(rows) == 2
    r = rows[0]
    assert r["instrument_name"].startswith("ペアン") and r["hint_quality"] == "full" and r["end_a_x"] == 0.1 and r["mode"] == "multi"
    assert rows[1]["occluded"] is True and rows[1]["end_a_x"] is None
