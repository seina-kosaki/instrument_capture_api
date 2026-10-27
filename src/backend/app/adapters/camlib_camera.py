"""camlibを使う唯一のカメラアダプター。

SDK importを接続時まで遅らせ、APIやテストが実機用共有ライブラリなしで起動できるようにする。
"""
from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any, Callable, Protocol

import numpy as np
from PIL import Image
import tifffile
import yaml

from ..ports import CameraCapture, DEPTH_PNG_CONTENT_TYPE, DEPTH_TIFF_CONTENT_TYPE

JPEG_QUALITY = 90
DEPTH_BUFFER_NAME = "depth"
DEPTH_IMAGE_FORMAT = "PNG"
DEPTH_PNG_DTYPES = {np.dtype("u1"), np.dtype("<u2")}
DEPTH_NUMERIC_KINDS = frozenset("uif")
DEPTH_DIMENSIONS = 2
logger = logging.getLogger(__name__)


class CameraManagerPort(Protocol):
    """camlib CameraManagerの必要最小限の契約。"""

    def connect(self, name: str) -> bool:
        """指定したカメラを接続する。"""
        ...

    def disconnect(self, name: str) -> bool:
        """指定したカメラを切断する。"""
        ...

    def get_frame(self, name: str, buffer_name: str) -> Any:
        """指定バッファから最新フレームを取得する。"""
        ...


class CamlibCamera:
    """設定されたcamlibカメラをJPEGのプレビュー/撮影データへ変換する。

    Note:
        camlibのフレームはBGR配列として返るため、JPEG化前にRGBへ変換する。
        SDK importはHALCON/Arena等のネイティブ依存を要求する場合があるためopen内で行う。
    """

    def __init__(self, param_path: Path, id_path: Path, camera_name: str | None,
                 buffer_name: str = "color",
                 manager_factory: Callable[[str, str], CameraManagerPort] | None = None) -> None:
        """カメラ設定とcamlibマネージャー生成関数を受け取る。

        Args:
            param_path: camlibのカメラパラメータYAML。
            id_path: camlibのデバイスID YAML。
            camera_name: 複数カメラ時の対象キー。未指定時は一意なカメラを選ぶ。
            buffer_name: プレビューと撮影に使う画像バッファ名。
            manager_factory: テスト時にcamlib依存を置き換える生成関数。
        """
        self._param_path = param_path
        self._id_path = id_path
        self._camera_name = camera_name
        self._active_camera_name: str | None = None
        self._buffer_name = buffer_name
        self._manager_factory = manager_factory
        self._manager: CameraManagerPort | None = None

    def open(self) -> None:
        """設定ファイルを読み込み、対象カメラだけ接続する。"""
        if self._manager is not None:
            return
        camera_name = self._resolve_camera_name()
        manager = self._create_manager()
        try:
            connected = manager.connect(camera_name)
        except Exception:
            manager.disconnect(camera_name)
            raise
        if not connected:
            manager.disconnect(camera_name)
            raise RuntimeError(f"カメラ {camera_name} の接続に失敗しました")
        self._manager = manager
        self._active_camera_name = camera_name

    def close(self) -> None:
        """対象カメラを切断する。"""
        if self._manager is None:
            return
        manager = self._manager
        camera_name = self._active_camera_name or self._camera_name
        if camera_name is None or not manager.disconnect(camera_name):
            raise RuntimeError(f"カメラ {camera_name} の切断に失敗しました")
        self._manager = None
        self._active_camera_name = None

    def preview(self) -> bytes:
        """最新フレームをJPEGへ変換して返す。"""
        frame, _ = self._read_frame()
        return self._encode_jpeg(frame)

    def capture(self) -> CameraCapture:
        """RGBと取得可能な深度画像を、同じ撮影結果として返す。

        Returns:
            JPEGのRGB画像、撮影メタデータ、型と深度値を保持する任意のPNGまたはTIFF。

        Raises:
            RuntimeError: RGBフレームを取得できない場合。

        Note:
            PNGでは保持できない整数型や浮動小数点型はTIFFに保存し、
            型変換による桁あふれや小数部・無効深度値の喪失を防ぐ。
        """
        frame, timestamp = self._read_frame()
        image = self._to_rgb_image(frame)
        metadata: dict[str, object] = {
            "driver": "camlib",
            "camera_name": self.camera_name,
            "camera_status": "ready",
            "resolution": f"{image.width}x{image.height}",
        }
        if timestamp is not None:
            metadata["timestamp"] = timestamp
        depth_data: bytes | None = None
        depth_content_type = DEPTH_PNG_CONTENT_TYPE
        try:
            depth_frame, depth_timestamp = self._read_frame(DEPTH_BUFFER_NAME)
            if not isinstance(depth_frame, np.ndarray):
                raise TypeError("depthフレームがNumPy配列ではありません")
            if depth_frame.ndim != DEPTH_DIMENSIONS or depth_frame.size == 0:
                raise ValueError("depthフレームは空でない2次元配列である必要があります")
            if depth_frame.dtype.kind not in DEPTH_NUMERIC_KINDS:
                raise ValueError(f"depthフレームは実数の数値配列である必要があります: {depth_frame.dtype}")
            output = io.BytesIO()
            png_dtype = depth_frame.dtype.newbyteorder("<")
            if png_dtype in DEPTH_PNG_DTYPES:
                depth_image: Image.Image = Image.fromarray(depth_frame.astype(png_dtype, copy=False))
                depth_image.save(output, format=DEPTH_IMAGE_FORMAT)
            else:
                tifffile.imwrite(output, depth_frame)
                depth_content_type = DEPTH_TIFF_CONTENT_TYPE
            depth_data = output.getvalue()
            metadata["depth_dtype"] = depth_frame.dtype.str
            metadata["depth_content_type"] = depth_content_type
            if depth_timestamp is not None:
                metadata["depth_timestamp"] = depth_timestamp
        except Exception:
            logger.debug("depth画像を取得できないためRGBのみを保存します", exc_info=True)
        return CameraCapture(self._encode_image(image), metadata, depth_data, depth_content_type)

    def _create_manager(self) -> CameraManagerPort:
        if self._manager_factory is not None:
            return self._manager_factory(str(self._param_path), str(self._id_path))
        try:
            from camlib import CameraManager
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:
            raise RuntimeError("camlibまたはカメラSDKのランタイムを読み込めません") from exc

        return CameraManager(str(self._param_path), str(self._id_path))

    @property
    def camera_name(self) -> str:
        """接続中、または設定済みのcamera_id.yamlキーを返す。"""
        return self._active_camera_name or self._camera_name or "unknown"

    def _resolve_camera_name(self) -> str:
        """camera_id.yamlのキーからカメラ名を選択する。"""
        try:
            config = yaml.safe_load(self._id_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise RuntimeError(f"カメラID設定を読み込めません: {self._id_path}") from exc
        cameras = config.get("cameras")
        if not isinstance(cameras, dict) or not cameras:
            raise RuntimeError("camera_id.yamlにカメラが登録されていません")
        if self._camera_name is not None:
            if self._camera_name not in cameras:
                raise RuntimeError(f"camera_id.yamlにカメラ名がありません: {self._camera_name}")
            return self._camera_name
        if len(cameras) == 1:
            return next(iter(cameras))
        raise RuntimeError("複数カメラが登録されています。IC_CAMERA_NAMEで使用するキーを指定してください")

    def _read_frame(self, buffer_name: str | None = None) -> tuple[Any, float | None]:
        if self._manager is None:
            raise RuntimeError("camlibカメラが接続されていません")
        camera_name = self._active_camera_name or self._camera_name
        if camera_name is None:
            raise RuntimeError("接続中カメラ名がありません")
        result = self._manager.get_frame(camera_name, buffer_name if buffer_name is not None else self._buffer_name)
        timestamp: float | None = None
        if isinstance(result, tuple):
            result, raw_timestamp = result
            if raw_timestamp is not None:
                timestamp = float(raw_timestamp)
        if result is None:
            raise RuntimeError("camlibからフレームを取得できません")
        return result, timestamp

    @staticmethod
    def _to_rgb_image(frame: Any) -> Image.Image:
        image = Image.fromarray(frame[..., ::-1])
        return image.convert("RGB") if image.mode != "RGB" else image

    @classmethod
    def _encode_jpeg(cls, frame: Any) -> bytes:
        return cls._encode_image(cls._to_rgb_image(frame))

    @staticmethod
    def _encode_image(image: Image.Image) -> bytes:
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=JPEG_QUALITY)
        return output.getvalue()