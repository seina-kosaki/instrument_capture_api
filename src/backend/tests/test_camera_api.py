"""camlibカメラAPIのHTTP契約をFakeカメラで検証する。"""
from __future__ import annotations

import io
import sqlite3
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pytest
import tifffile
from fastapi.testclient import TestClient
from PIL import Image

from app.adapters.camlib_camera import CamlibCamera
from app.config import Settings
from app.main import create_app
from app.ports import CameraCapture, DEPTH_PNG_CONTENT_TYPE, DEPTH_TIFF_CONTENT_TYPE
from .conftest import ROOT


class FakeCamera:
    """実機なしで接続・プレビュー・撮影を再現する。"""

    def __init__(self) -> None:
        self.opened = False
        self.capture_count = 0
        self.depth_data: bytes | None = None
        self.depth_content_type = DEPTH_PNG_CONTENT_TYPE

    @property
    def camera_name(self) -> str:
        return "test-camera"

    def open(self) -> None:
        """Fakeカメラを接続状態にする。"""
        self.opened = True

    def close(self) -> None:
        """Fakeカメラを切断状態にする。"""
        self.opened = False

    def preview(self) -> bytes:
        """テスト用のJPEGプレビューを返す。"""
        return _jpeg_bytes()

    def capture(self) -> CameraCapture:
        """テスト用のJPEG撮影結果を返す。"""
        self.capture_count += 1
        return CameraCapture(
            _jpeg_bytes(), {"driver": "camlib", "camera_name": "test-camera"},
            self.depth_data, self.depth_content_type,
        )


def _jpeg_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (48, 32), (40, 120, 130)).save(output, format="JPEG")
    return output.getvalue()


@pytest.fixture
def camera_client(tmp_path: Path) -> Iterator[tuple[TestClient, FakeCamera]]:
    """各テストにFakeカメラを注入したAPIクライアントを提供する。"""
    camera = FakeCamera()
    settings = Settings(data_dir=tmp_path / "data", catalog_csv=ROOT / "master" / "instruments_mock.csv")
    fixed = datetime(2026, 10, 5, 10, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    with TestClient(create_app(settings, camera_port=camera, clock=lambda: fixed)) as client:
        yield client, camera


def test_camera_preview_when_closed_returns_service_unavailable(camera_client: tuple[TestClient, FakeCamera]) -> None:
    """未接続時のプレビュー要求はサービス利用不可を返す。"""
    # Arrange
    client, _ = camera_client

    # Act
    response = client.get("/camera/preview")

    # Assert
    assert response.status_code == 503


@pytest.mark.parametrize("depth_dtype", [None, "u1", "<u2", "<i2", "<u4", "<u8", "<f4", "<f8"])
def test_camera_capture_when_ready_saves_image(
    camera_client: tuple[TestClient, FakeCamera], tmp_path: Path, depth_dtype: str | None,
) -> None:
    """RGBと任意のdepthを保存し、DB・API・削除を同じ画像IDで関連付ける。"""
    # Arrange
    client, camera = camera_client
    depth_values: np.ndarray | None = None
    if depth_dtype is not None:
        depth_output = io.BytesIO()
        depth_values = np.array([[0, 1, 42, 123, 255]], dtype=depth_dtype)
        if depth_values.dtype.kind == "u" and depth_values.dtype.itemsize <= 2:
            Image.fromarray(depth_values).save(depth_output, format="PNG")
        else:
            tifffile.imwrite(depth_output, depth_values)
            camera.depth_content_type = DEPTH_TIFF_CONTENT_TYPE
        camera.depth_data = depth_output.getvalue()
    session_id = client.post("/sessions", json={}).json()["session_id"]
    declaration = client.post(
        f"/sessions/{session_id}/declarations",
        json={"items": [{"instrument_uid": "INS-000001"}]},
    ).json()
    declaration_id = declaration["declaration_id"]
    client.post(f"/declarations/{declaration_id}/confirm")
    client.post("/camera/open")

    # Act
    response = client.post(f"/declarations/{declaration_id}/capture")

    # Assert
    assert response.status_code == 201
    assert response.json()["content_type"] == "image/jpeg"
    assert response.json()["meta"]["camera_name"] == "test-camera"
    assert camera.capture_count == 1
    image = response.json()
    root = tmp_path / "data"
    rgb_path = root / image["relative_path"]
    assert rgb_path.is_file()
    depth_path = image["depth_path"]
    database_path = rgb_path.parent.parent / "metadata.sqlite3"
    with sqlite3.connect(database_path) as connection:
        saved_depth_path = connection.execute(
            "SELECT depth_path FROM images WHERE image_id = ?", (image["image_id"],),
        ).fetchone()[0]
    assert saved_depth_path == depth_path
    assert client.get(f"/images/{image['image_id']}").json()["depth_path"] == depth_path
    assert client.get("/images").json()[0]["depth_path"] == depth_path
    if depth_values is not None:
        extension = "png" if camera.depth_content_type == DEPTH_PNG_CONTENT_TYPE else "tiff"
        assert depth_path == f"2026-10-05/{session_id}/depth/{image['image_id']}.{extension}"
        assert (root / depth_path).read_bytes() == camera.depth_data
        if extension == "tiff":
            decoded = tifffile.imread(root / depth_path)
            assert decoded.dtype == depth_values.dtype
            np.testing.assert_array_equal(decoded, depth_values)
        else:
            with Image.open(root / depth_path) as depth_image:
                np.testing.assert_array_equal(np.asarray(depth_image), depth_values)
    else:
        assert depth_path is None
    assert client.delete(f"/images/{image['image_id']}").status_code == 204
    assert not rgb_path.exists()
    if depth_path is not None:
        assert not (root / depth_path).exists()


def test_camera_capture_when_declaration_unconfirmed_does_not_trigger_camera(
    camera_client: tuple[TestClient, FakeCamera],
) -> None:
    """未確認宣言の撮影要求ではカメラを駆動しない。"""
    # Arrange
    client, camera = camera_client
    session_id = client.post("/sessions", json={}).json()["session_id"]
    declaration = client.post(
        f"/sessions/{session_id}/declarations",
        json={"items": [{"instrument_uid": "INS-000001"}]},
    ).json()
    client.post("/camera/open")

    # Act
    response = client.post(f"/declarations/{declaration['declaration_id']}/capture")

    # Assert
    assert response.status_code == 409
    assert camera.capture_count == 0


@pytest.mark.parametrize("depth_dtype", [
    "u1", "<u2", ">u2", "<i2", "<i4", "<u4", "<i8", "<u8",
    "<f2", "<f4", ">f4", "<f8", ">f8",
])
@pytest.mark.parametrize("non_contiguous", [False, True])
def test_camlib_adapter_capture_when_frame_has_timestamp_encodes_bgr_and_metadata(
    tmp_path: Path, depth_dtype: str, non_contiguous: bool,
) -> None:
    """RGBの色と深度値を、配列のバイト順・連続性によらず保持する。"""
    depth_values = np.full((24, 32), 123, dtype=depth_dtype)
    if depth_values.dtype.kind == "f":
        depth_values[0, :5] = [-np.inf, -0.5, np.nan, np.inf, np.finfo(depth_values.dtype).max]
    elif depth_values.dtype.kind == "i":
        limits = np.iinfo(depth_values.dtype)
        depth_values[0, :5] = [limits.min, -1, 0, 1, limits.max]
    else:
        maximum = np.iinfo(depth_values.dtype).max
        depth_values[0, :5] = [0, 1, maximum // 2, maximum - 1, maximum]
    if non_contiguous:
        depth_values = depth_values[:, ::-1]

    class Manager:
        def connect(self, name: str) -> bool:
            return name == "realsense"

        def disconnect(self, name: str) -> bool:
            return name == "realsense"

        def get_frame(self, name: str, buffer_name: str) -> tuple[np.ndarray, float]:
            if buffer_name == "depth":
                return depth_values, 12.6
            frame = np.zeros((24, 32, 3), dtype=np.uint8)
            frame[:, :, 0] = 255
            return frame, 12.5

    id_path = tmp_path / "ids.yaml"
    id_path.write_text("cameras:\n  realsense:\n    device_id: test-device\n", encoding="utf-8")
    camera = CamlibCamera(tmp_path / "camera.yaml", id_path, "realsense", manager_factory=lambda *_: Manager())

    # Arrange
    camera.open()

    # Act
    result = camera.capture()

    # Assert
    with Image.open(io.BytesIO(result.data)) as captured:
        red, green, blue = captured.convert("RGB").getpixel((12, 12))
    assert red < 20 and green < 20 and blue > 230
    assert result.meta["timestamp"] == 12.5
    assert result.meta["resolution"] == "32x24"
    assert result.meta["depth_timestamp"] == 12.6
    assert result.meta["depth_dtype"] == depth_values.dtype.str
    assert result.meta["depth_content_type"] == result.depth_content_type
    assert result.depth_data is not None
    if depth_values.dtype.kind != "u" or depth_values.dtype.itemsize > 2:
        assert result.depth_content_type == DEPTH_TIFF_CONTENT_TYPE
        decoded = tifffile.imread(io.BytesIO(result.depth_data))
        assert decoded.dtype.newbyteorder("=") == depth_values.dtype.newbyteorder("=")
        np.testing.assert_array_equal(decoded, depth_values)
    else:
        assert result.depth_content_type == DEPTH_PNG_CONTENT_TYPE
        with Image.open(io.BytesIO(result.depth_data)) as depth_image:
            assert depth_image.format == "PNG"
            assert depth_image.size == (32, 24)
            assert depth_image.getpixel((12, 12)) == 123
            np.testing.assert_array_equal(np.asarray(depth_image), depth_values)


@pytest.mark.parametrize("depth_failure", [
    "exception", "none", "timestamped_none", "invalid_shape", "one_dimensional",
    "uint16_multichannel", "not_array", "object", "complex", "empty",
])
def test_camlib_adapter_attempts_depth_without_failing_rgb(tmp_path: Path, depth_failure: str) -> None:
    """depth非対応のカメラでもRGB撮影を継続する。"""
    requested_buffers: list[str] = []

    class Manager:
        """depthだけを拒否するカメラマネージャー。"""

        def connect(self, name: str) -> bool:
            """接続に成功する。"""
            return True

        def disconnect(self, name: str) -> bool:
            """切断に成功する。"""
            return True

        def get_frame(self, name: str, buffer_name: str) -> np.ndarray | tuple[None, float] | list[list[int]] | None:
            """RGBのみを返し、depth要求は例外にする。"""
            requested_buffers.append(buffer_name)
            if buffer_name == "depth":
                if depth_failure == "exception":
                    raise RuntimeError("Depth is unavailable")
                if depth_failure == "none":
                    return None
                if depth_failure == "timestamped_none":
                    return None, 12.5
                if depth_failure == "one_dimensional":
                    return np.zeros(32, dtype=np.uint16)
                if depth_failure == "uint16_multichannel":
                    return np.zeros((24, 32, 3), dtype=np.uint16)
                if depth_failure == "object":
                    return np.full((24, 32), object(), dtype=object)
                if depth_failure == "complex":
                    return np.full((24, 32), 1 + 2j, dtype=np.complex64)
                if depth_failure == "empty":
                    return np.zeros((0, 32), dtype=np.float32)
                if depth_failure == "not_array":
                    return [[12345]]
            return np.zeros((24, 32, 3), dtype=np.uint8)

    id_path = tmp_path / "ids.yaml"
    id_path.write_text("cameras:\n  rgb-only:\n    device_id: test-device\n", encoding="utf-8")
    camera = CamlibCamera(tmp_path / "camera.yaml", id_path, "rgb-only", manager_factory=lambda *_: Manager())
    camera.open()

    result = camera.capture()

    assert result
    assert result.depth_data is None
    assert requested_buffers == ["color", "depth"]


@pytest.mark.parametrize("depth_content_type", [DEPTH_PNG_CONTENT_TYPE, DEPTH_TIFF_CONTENT_TYPE])
def test_camera_capture_invalid_depth_removes_partial_rgb(
    camera_client: tuple[TestClient, FakeCamera], tmp_path: Path, depth_content_type: str,
) -> None:
    """深度画像の保存に失敗した場合はRGBだけのファイルを残さない。"""
    client, camera = camera_client
    camera.depth_data = b"invalid-png"
    camera.depth_content_type = depth_content_type
    session_id = client.post("/sessions", json={}).json()["session_id"]
    declaration_id = client.post(
        f"/sessions/{session_id}/declarations",
        json={"items": [{"instrument_uid": "INS-000001"}]},
    ).json()["declaration_id"]
    client.post(f"/declarations/{declaration_id}/confirm")
    client.post("/camera/open")

    response = client.post(f"/declarations/{declaration_id}/capture")

    assert response.status_code == 400
    assert client.get("/images").json() == []
    assert not list((tmp_path / "data").rglob("*.jpg"))
    assert not list((tmp_path / "data").rglob("*.png"))
    assert not list((tmp_path / "data").rglob("*.tiff"))