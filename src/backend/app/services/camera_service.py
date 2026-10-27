"""カメラの状態と操作を管理するユースケース。

FastAPIの各リクエストから共有されるカメラを直列化し、camlibの接続状態をHTTP境界へ公開する。
"""
from __future__ import annotations

import threading
from typing import Literal

from ..ports import CameraCapture, CameraPort

CameraState = Literal["closed", "ready", "error"]


class CameraService:
    """単一カメラを排他制御しながら操作する。"""

    def __init__(self, camera: CameraPort):
        """カメラ操作ポートを注入する。

        Args:
            camera: カメラ接続と画像取得を担うアダプター。
        """
        self._camera = camera
        self._lock = threading.Lock()
        self._state: CameraState = "closed"
        self._last_error: str | None = None

    def status(self) -> dict[str, str | None]:
        """接続状態と直近のカメラエラーを返す。"""
        with self._lock:
            return {"state": self._state, "error": self._last_error}

    def open(self) -> dict[str, str | None]:
        """カメラを接続し、成功後の状態を返す。"""
        with self._lock:
            if self._state == "ready":
                return self._status_unlocked()
            try:
                self._camera.open()
            except Exception as exc:
                self._state = "error"
                self._last_error = str(exc)
                raise RuntimeError("カメラを接続できません") from exc
            self._state = "ready"
            self._last_error = None
            return self._status_unlocked()

    def close(self) -> dict[str, str | None]:
        """カメラを切断し、状態をclosedへ戻す。"""
        with self._lock:
            try:
                self._camera.close()
            except Exception as exc:
                self._state = "error"
                self._last_error = str(exc)
                raise RuntimeError("カメラを切断できません") from exc
            self._state = "closed"
            self._last_error = None
            return self._status_unlocked()

    def preview(self) -> bytes:
        """JPEG形式の最新プレビューフレームを取得する。"""
        with self._lock:
            self._require_ready()
            try:
                return self._camera.preview()
            except Exception as exc:
                self._record_error(exc)
                raise RuntimeError("カメラのプレビューを取得できません") from exc

    def capture(self) -> CameraCapture:
        """RGB・任意の深度画像と撮影メタデータを排他取得する。"""
        with self._lock:
            self._require_ready()
            try:
                return self._camera.capture()
            except Exception as exc:
                self._record_error(exc)
                raise RuntimeError("カメラで撮影できません") from exc

    def _require_ready(self) -> None:
        if self._state != "ready":
            raise RuntimeError("カメラが接続されていません")

    def _record_error(self, exc: Exception) -> None:
        self._state = "error"
        self._last_error = str(exc)

    def _status_unlocked(self) -> dict[str, str | None]:
        return {"state": self._state, "error": self._last_error, "camera_name": self._camera.camera_name}