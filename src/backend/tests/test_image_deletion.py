import sqlite3

from .conftest import make_decl, upload


def _database_path(client, session_id):
    return client.data_dir / "2026-10-05" / session_id / "metadata.sqlite3"


def test_delete_image_removes_only_its_files_and_metadata(client):
    session_id, declaration_id = make_decl(
        client, [{"instrument_uid": "INS-000001"}]
    )
    target_id = upload(client, declaration_id).json()["image_id"]
    other_id = upload(client, declaration_id).json()["image_id"]
    tags = {"hints": [{"instrument_uid": "INS-000001", "center": {"x": 0.5, "y": 0.5}}]}
    assert client.put(f"/images/{target_id}/tags", json=tags).status_code == 200

    bundle = client.data_dir / "2026-10-05" / session_id
    raw_path = bundle / "raw" / f"{target_id}.png"
    depth_path = bundle / "depth" / f"{target_id}.tiff"
    depth_path.parent.mkdir()
    depth_path.write_bytes(b"depth")
    database_path = _database_path(client, session_id)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE images SET depth_path=? WHERE image_id=?",
            (depth_path.relative_to(client.data_dir).as_posix(), target_id),
        )
        connection.execute(
            """INSERT INTO annotation_revisions(
                session_id, image_id, tag_revision, revision, status,
                annotation_sha256, updated_at
            ) VALUES (?, ?, 1, 'r1', 'reviewed', 'hash', 'now')""",
            (session_id, target_id),
        )

    debug_path = bundle / "debug" / f"{target_id}.jpg"
    other_raw_path = bundle / "raw" / f"{other_id}.png"
    assert raw_path.exists() and depth_path.exists() and debug_path.exists()
    response = client.delete(f"/images/{target_id}")

    assert response.status_code == 204
    assert not raw_path.exists()
    assert not depth_path.exists()
    assert not debug_path.exists()
    assert other_raw_path.exists()
    assert client.get(f"/images/{target_id}").status_code == 404
    assert client.get(f"/images/{other_id}").status_code == 200
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT count(*) FROM images WHERE image_id=?", (target_id,)
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT count(*) FROM hints WHERE image_id=?", (target_id,)
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT count(*) FROM annotation_revisions WHERE session_id=? AND image_id=?",
            (session_id, target_id),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT count(*) FROM images WHERE image_id=?", (other_id,)
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT count(*) FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT count(*) FROM declarations WHERE declaration_id=?",
            (declaration_id,),
        ).fetchone()[0] == 1


def test_delete_image_missing_returns_404(client):
    assert client.delete("/images/not-found").status_code == 404


def test_delete_image_rejects_path_to_another_image(client):
    _, declaration_id = make_decl(client, [{"instrument_uid": "INS-000001"}])
    target_id = upload(client, declaration_id).json()["image_id"]
    other_id = upload(client, declaration_id).json()["image_id"]
    target = client.get(f"/images/{target_id}").json()
    session_id = target["session_id"]
    database_path = _database_path(client, session_id)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE images SET path=? WHERE image_id=?",
            (f"2026-10-05/{session_id}/raw/{other_id}.png", target_id),
        )

    client._transport.raise_server_exceptions = False
    response = client.delete(f"/images/{target_id}")

    assert response.status_code == 500
    assert (client.data_dir / "2026-10-05" / session_id / "raw" / f"{target_id}.png").exists()
    assert (client.data_dir / "2026-10-05" / session_id / "raw" / f"{other_id}.png").exists()
    assert client.get(f"/images/{target_id}").status_code == 200


def test_delete_image_rejects_traversal_path(client):
    _, declaration_id = make_decl(client, [{"instrument_uid": "INS-000001"}])
    image_id = upload(client, declaration_id).json()["image_id"]
    session_id = client.get(f"/images/{image_id}").json()["session_id"]
    database_path = _database_path(client, session_id)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE images SET path=? WHERE image_id=?",
            (f"../../outside/{image_id}.png", image_id),
        )

    client._transport.raise_server_exceptions = False
    response = client.delete(f"/images/{image_id}")

    assert response.status_code == 500
    assert (client.data_dir / "2026-10-05" / session_id / "raw" / f"{image_id}.png").exists()
    assert client.get(f"/images/{image_id}").status_code == 200


def test_delete_image_file_error_does_not_return_success(client, monkeypatch):
    _, declaration_id = make_decl(client, [{"instrument_uid": "INS-000001"}])
    image_id = upload(client, declaration_id).json()["image_id"]
    capture = client.app.state.c.capture
    monkeypatch.setattr(
        capture._images,
        "delete",
        lambda path: (_ for _ in ()).throw(OSError("delete failed")),
    )
    client._transport.raise_server_exceptions = False

    response = client.delete(f"/images/{image_id}")

    assert response.status_code == 500
    assert client.get(f"/images/{image_id}").status_code == 200
